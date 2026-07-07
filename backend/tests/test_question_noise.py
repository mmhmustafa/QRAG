"""Questionnaire boilerplate ("Include any relevant details... Variant 2.") must not dilute
retrieval or reuse matching. Measured on real data: stripping it lifted mean top retrieval
score ~20% and moved every tested Needs-Manual question across the relevance gate."""
from sqlalchemy import select
from app.models import Answer, Question
from app.services import shared_question_noise, core_question, run_generation, new_progress, generate_one, config_for
from app.providers import get_llm
from tests.test_generation_progress import make_workspace

SUFFIX="Include any relevant details, limitations, or source references."

def test_repeated_trailing_sentences_are_noise_first_sentences_never():
    questions=[
        f"Do you encrypt data at rest? {SUFFIX} Variant 2.",
        f"Do you support MFA? {SUFFIX} Variant 2.",
        f"Is support available 24x7? {SUFFIX} Variant 2.",
        "Do you encrypt data at rest?",  # repeated core question, always first sentence
        "Do you encrypt data at rest?",
        "Do you encrypt data at rest?",
    ]
    noise=shared_question_noise(questions)
    assert SUFFIX in noise and "Variant 2." in noise
    assert "Do you encrypt data at rest?" not in noise  # first sentences are protected
    assert core_question(questions[0],noise)=="Do you encrypt data at rest?"
    assert core_question("Do you encrypt data at rest?",noise)=="Do you encrypt data at rest?"

def test_variant_questions_autoreuse_the_approved_base_answer(tmp_path):
    base="Do you encrypt data at rest?"
    db,customer,item=make_workspace(tmp_path,[base,f"{base} {SUFFIX} Variant 2.",f"Do you support MFA? {SUFFIX} Variant 2.",f"Is support available 24x7? {SUFFIX} Variant 2."])
    run_generation(db,item,new_progress(item.id,customer.id))
    questions=list(db.scalars(select(Question).where(Question.questionnaire_id==item.id).order_by(Question.ordinal)))
    first=db.scalar(select(Answer).where(Answer.question_id==questions[0].id))
    first.status="approved";first.text="Yes, AES-256 at rest.";first.approved_at=__import__("app.services",fromlist=["now"]).now();first.reviewer="Reviewer";db.commit()
    cfg=config_for(db,customer.id)
    regenerated=generate_one(db,questions[1],cfg,get_llm(cfg));db.commit()
    # The suffixed variant matches the approved base answer at full similarity and reuses it.
    assert regenerated.reused_from_answer_id==first.id
    assert regenerated.status=="approved_candidate"
    assert regenerated.text=="Yes, AES-256 at rest."
