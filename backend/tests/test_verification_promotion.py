"""Borderline answers with reliable evidence are promoted to Ready only when the model verifies grounding."""
from sqlalchemy import select
from app.models import Answer, GlobalProviderConfig, Question
from app.services import generate_one, config_for, run_generation, new_progress
from app.providers import MockLLMProvider
import app.services as services
from tests.test_generation_progress import make_workspace

class VerifyingLLM(MockLLMProvider):
    """Real-provider stand-in: generates like the mock but answers the verification prompt."""
    def __init__(self, verdict): self.verdict = verdict
    def chat(self, messages, stream=False):
        if "Reply with exactly YES or NO" in messages[0].get("content", ""): return self.verdict
        return super().chat(messages, stream)

def borderline_question(db, item, customer):
    """A question whose mock answer lands in needs_review with a reliable top source."""
    run_generation(db, item, new_progress(item.id, customer.id))
    for q in db.scalars(select(Question).where(Question.questionnaire_id == item.id)):
        a = db.scalar(select(Answer).where(Answer.question_id == q.id))
        if a and a.status == "needs_review" and a.sources and a.sources[0]["score"] >= services.RELIABLE_SCORE and a.confidence >= services.VERIFY_PROMOTION_MIN:
            return q
    raise AssertionError("workspace produced no borderline needs_review answer to test with")

def promote_setup(tmp_path, monkeypatch, verdict):
    db, customer, item = make_workspace(tmp_path, ["Do you encrypt data at rest?", "Do you support MFA?", "Is support available 24x7?"])
    q = borderline_question(db, item, customer)
    db.get(GlobalProviderConfig, 1).llm_provider = "openrouter"; db.commit()
    monkeypatch.setattr(services, "get_llm", lambda cfg: VerifyingLLM(verdict))
    cfg = config_for(db, customer.id)
    answer = generate_one(db, q, cfg, VerifyingLLM(verdict)); db.commit()
    return answer

def test_verified_borderline_answer_becomes_ready(tmp_path, monkeypatch):
    answer = promote_setup(tmp_path, monkeypatch, "YES")
    assert answer.status == "approved_candidate"
    assert "Verified against source documentation." in answer.classification_reason
    assert answer.debug_data["llm_verified"] is True

def test_unverified_borderline_answer_stays_in_review(tmp_path, monkeypatch):
    answer = promote_setup(tmp_path, monkeypatch, "NO")
    assert answer.status == "needs_review"
    assert answer.debug_data["llm_verified"] is False

def test_mock_provider_never_promotes(tmp_path, monkeypatch):
    db, customer, item = make_workspace(tmp_path, ["Do you encrypt data at rest?", "Do you support MFA?", "Is support available 24x7?"])
    q = borderline_question(db, item, customer)
    cfg = config_for(db, customer.id)
    answer = generate_one(db, q, cfg, MockLLMProvider()); db.commit()
    assert answer.status == "needs_review"  # offline mock has no verifier; the band never auto-promotes
