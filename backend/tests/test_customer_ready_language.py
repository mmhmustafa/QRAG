"""Answers that describe the internal documentation instead of answering are never customer-ready.

Regression for a real answer that reached Ready to Approve: "The only ownership statement in the
provided documents is for the company profile and organization handbook... The product suite guide
and product architecture guide do not contain an explicit ownership declaration in the supplied
sources." Grounded, verified — and completely unsendable to a customer.
"""
from sqlalchemy import select
from app.models import Question
from app.services import references_internal_context, generate_one, config_for, run_generation, new_progress
from app.providers import MockLLMProvider
from tests.test_generation_progress import make_workspace

LEAKY=("The only ownership statement in the provided documents is for the company profile and "
       "organization handbook, which is owned by Corporate Operations. The product suite guide and "
       "product architecture guide do not contain an explicit ownership declaration in the supplied sources.")

def test_meta_language_is_detected():
    assert references_internal_context(LEAKY)
    assert references_internal_context("Based on the provided documentation, MFA is supported.")
    assert references_internal_context("The sources do not mention penetration testing.")
    assert references_internal_context("There is no explicit statement of ownership in the material.")

def test_legitimate_answers_are_not_flagged():
    assert not references_internal_context("Corporate Operations owns customer-facing product documentation.")
    assert not references_internal_context("Our information security policy requires MFA for all administrators.")
    assert not references_internal_context("Data is encrypted at rest using AES-256, per the incident response plan.")
    assert not references_internal_context("Support documentation is available to customers through the portal.")

class LeakyLLM(MockLLMProvider):
    def generate_answer(self,question,context,instructions=""):return LEAKY

def test_leaky_answer_lands_in_check_suggested_never_ready(tmp_path):
    db,customer,item=make_workspace(tmp_path,["Do you encrypt data at rest?"])
    run_generation(db,item,new_progress(item.id,customer.id))
    q=db.scalar(select(Question).where(Question.questionnaire_id==item.id))
    cfg=config_for(db,customer.id)
    answer=generate_one(db,q,cfg,LeakyLLM());db.commit()
    assert answer.status=="needs_review"
    assert "rephrase" in answer.classification_reason.lower()
    assert answer.text.startswith("The only ownership statement")  # draft kept for the reviewer to fix
