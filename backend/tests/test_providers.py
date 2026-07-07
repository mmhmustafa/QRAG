from app.providers import MockEmbeddingProvider, MockLLMProvider, MANUAL

def test_mock_embedding_is_deterministic():
    p=MockEmbeddingProvider()
    assert p.embed_text("hello world")==p.embed_text("hello world")
    assert len(p.embed_text("hello"))==128

def test_llm_requires_context():
    assert MockLLMProvider().generate_answer("Unknown?",[])==MANUAL

def test_question_extraction():
    text="1. Do you encrypt data at rest?\n2. Describe your support model."
    assert len(MockLLMProvider().extract_questions(text))==2


def test_question_extraction_qnumbered_wrapped_pdf_lines():
    """PDF text wraps questions mid-sentence and repeats page headers; every numbered question must survive."""
    text="""ACME Corp - Enterprise Test Pack v1.0
Page 1
Enterprise Customer Questionnaire
Instructions: answer only from approved documents,
never invent details.
Organization and Governance
Q1. Provide a brief overview of your organization.
Q2. Where are your support operations located?
Q3. Who owns customer-facing product documentation? Include any relevant details, limitations, or source
references. Variant 2.
ACME Corp - Enterprise Test Pack v1.0
Page 2
Q4. Describe your incident response process. Include any relevant details, limitations, or source
references. Variant 2.
Q5. Do you support single sign-on?
"""
    questions=MockLLMProvider().extract_questions(text)
    assert len(questions)==5
    assert questions[0]=="Provide a brief overview of your organization."
    assert questions[2]=="Who owns customer-facing product documentation? Include any relevant details, limitations, or source references. Variant 2."
    assert questions[3]=="Describe your incident response process. Include any relevant details, limitations, or source references. Variant 2."
    assert not any("ACME Corp" in q or q.lower().startswith("page ") for q in questions)

def test_question_extraction_plain_numbering_skips_section_headings():
    text="1. Introduction\n2. Do you encrypt data at rest?\n3. Describe your SDLC.\n4. List your certifications."
    questions=MockLLMProvider().extract_questions(text)
    assert questions==["Do you encrypt data at rest?","Describe your SDLC.","List your certifications."]

def test_question_extraction_unnumbered_lines_still_work():
    text="Do you support MFA?\nInternal note without question form\nHow is data encrypted?"
    questions=MockLLMProvider().extract_questions(text)
    assert questions==["Do you support MFA?","How is data encrypted?"]

def test_clean_customer_answer_strips_markdown():
    from app.services import clean_customer_answer
    raw="**Key governance bodies**\n- Executive board oversees `risk`.\n## Cadence\nMeetings are held monthly."
    cleaned=clean_customer_answer(raw,[])
    assert "**" not in cleaned and "`" not in cleaned and "##" not in cleaned
    assert "Key governance bodies" in cleaned and "Meetings are held monthly." in cleaned

def test_null_provider_content_is_retried_then_fails_with_clear_error(monkeypatch):
    import pytest
    from types import SimpleNamespace
    import app.providers as providers
    calls={"n":0}
    class FakeResponse:
        def raise_for_status(self):pass
        def json(self):return {"choices":[{"message":{"content":None}}]}
    def fake_post(*args,**kwargs):
        calls["n"]+=1
        return FakeResponse()
    monkeypatch.setattr(providers.httpx,"post",fake_post)
    monkeypatch.setattr(providers.time,"sleep",lambda s:None)
    cfg=SimpleNamespace(ai_base_url="http://llm.local/v1",llm_model="test-model",temperature=0,max_tokens=10,top_p=1,retry_count=2,timeout=5,ai_api_key=None,api_key=None,custom_headers=None,openai_compatible_mode=True,chat_endpoint_path="/chat/completions")
    with pytest.raises(RuntimeError,match="empty response"):
        providers.OpenAICompatibleProvider(cfg).chat([{"role":"user","content":"hi"}])
    assert calls["n"]==3  # null content is retried like any transient failure

def test_recovered_content_after_transient_null(monkeypatch):
    from types import SimpleNamespace
    import app.providers as providers
    responses=[{"choices":[{"message":{"content":None}}]},{"choices":[{"message":{"content":"Recovered answer"}}]}]
    class FakeResponse:
        def __init__(self,body):self._body=body
        def raise_for_status(self):pass
        def json(self):return self._body
    monkeypatch.setattr(providers.httpx,"post",lambda *a,**k:FakeResponse(responses.pop(0)))
    monkeypatch.setattr(providers.time,"sleep",lambda s:None)
    cfg=SimpleNamespace(ai_base_url="http://llm.local/v1",llm_model="test-model",temperature=0,max_tokens=10,top_p=1,retry_count=2,timeout=5,ai_api_key=None,api_key=None,custom_headers=None,openai_compatible_mode=True,chat_endpoint_path="/chat/completions")
    assert providers.OpenAICompatibleProvider(cfg).chat([{"role":"user","content":"hi"}])=="Recovered answer"
