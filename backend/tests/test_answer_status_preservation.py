"""Draft is a first-class review state: reviewer-edited answers stay visible and protected.

Regression for a bug where saving an edit dropped answers into an untracked "draft" status —
invisible in every filter and count — and a follow-up where regeneration silently overwrote
hand-typed answers because only "approved" was protected.
"""
from sqlalchemy import select
from app.models import Answer
from app.services import apply_version_restore, run_generation, new_progress
from tests.test_generation_progress import make_workspace

def test_restore_lands_in_the_draft_bucket_with_a_clear_reason(tmp_path):
    db,customer,item=make_workspace(tmp_path,["Do you encrypt data at rest?"])
    run_generation(db,item,new_progress(item.id,customer.id))
    answer=db.scalar(select(Answer).where(Answer.customer_id==customer.id))
    generated_text=answer.text  # generation already snapshotted this as version 1
    answer.status="approved";answer.text="Approved wording.";db.commit()
    next_version=apply_version_restore(db,answer,1)
    db.commit()
    assert next_version==2
    assert answer.status=="draft"  # awaiting one Approve click, visible in the Draft filter
    assert answer.text==generated_text
    assert "restored by reviewer" in answer.classification_reason

def test_restore_missing_version_returns_none(tmp_path):
    db,customer,item=make_workspace(tmp_path,["Do you encrypt data at rest?"])
    run_generation(db,item,new_progress(item.id,customer.id))
    answer=db.scalar(select(Answer).where(Answer.customer_id==customer.id))
    assert apply_version_restore(db,answer,999) is None

def test_regeneration_never_overwrites_reviewer_edited_drafts(tmp_path):
    db,customer,item=make_workspace(tmp_path,["Do you encrypt data at rest?","Do you support MFA?","Is support available 24x7?"])
    run_generation(db,item,new_progress(item.id,customer.id))
    answers=list(db.scalars(select(Answer).where(Answer.customer_id==customer.id).order_by(Answer.id)))
    answers[0].status="approved";answers[0].text="Approved answer."
    answers[1].status="draft";answers[1].text="Hand-typed manual answer.";db.commit()
    progress=new_progress(item.id,customer.id)
    run_generation(db,item,progress)
    assert progress["total"]==1  # only the untouched third question is regenerated
    db.refresh(answers[0]);db.refresh(answers[1])
    assert answers[0].text=="Approved answer."
    assert answers[1].text=="Hand-typed manual answer." and answers[1].status=="draft"
    explicit=new_progress(item.id,customer.id)
    run_generation(db,item,explicit,include_approved=True)
    assert explicit["total"]==3  # the deliberate include-everything path still replaces all
