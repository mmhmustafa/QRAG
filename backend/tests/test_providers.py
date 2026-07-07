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
