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

