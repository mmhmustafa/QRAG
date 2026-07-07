"""Editing an answer or restoring a prior version must not drop it into an untracked status.

Regression for a bug where saving an edit (or restoring an old version) forced status to a fixed
"draft" value that isn't one of the four triage buckets (Ready to Approve / Check Suggested /
Needs Manual / Approved) — the answer would silently vanish from every filter and count, visible
only under "All", even though the Approve button still worked.
"""
from sqlalchemy import select
from app.models import Answer, AnswerVersion
from app.services import apply_version_restore, run_generation, new_progress
from tests.test_generation_progress import make_workspace

def test_restore_uses_the_snapshots_own_status_not_a_fixed_value(tmp_path):
    db,customer,item=make_workspace(tmp_path,["Do you encrypt data at rest?"])
    run_generation(db,item,new_progress(item.id,customer.id))
    answer=db.scalar(select(Answer).where(Answer.customer_id==customer.id))
    original_status=answer.status
    # Simulate a reviewer approving it (version 1 = original, version 2 = approved).
    db.add(AnswerVersion(customer_id=customer.id,answer_id=answer.id,version=1,text=answer.text,confidence=answer.confidence,status=original_status,sources=answer.sources))
    answer.status="approved";answer.text="Reviewer-approved wording.";db.commit()
    db.add(AnswerVersion(customer_id=customer.id,answer_id=answer.id,version=2,text=answer.text,confidence=answer.confidence,status="approved",sources=answer.sources));db.commit()
    next_version=apply_version_restore(db,answer,1)
    db.commit()
    assert next_version==3
    assert answer.status==original_status  # restored to what version 1 actually was, not "draft"
    assert answer.status!="draft"

def test_restore_missing_version_returns_none(tmp_path):
    db,customer,item=make_workspace(tmp_path,["Do you encrypt data at rest?"])
    run_generation(db,item,new_progress(item.id,customer.id))
    answer=db.scalar(select(Answer).where(Answer.customer_id==customer.id))
    assert apply_version_restore(db,answer,999) is None
