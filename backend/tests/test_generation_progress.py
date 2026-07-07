"""Live generation progress: per-question commits, cancellation, and failure isolation."""
from pathlib import Path
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.models import Customer, ProviderConfig, GlobalProviderConfig, Question, Answer
from app.services import ingest, build_questionnaire, run_generation, new_progress
from app.providers import MockLLMProvider
import app.services as services

COLLECTIONS=["Product A"]

def make_workspace(tmp_path,questions):
    engine=create_engine("sqlite:///:memory:");Base.metadata.create_all(engine)
    db=sessionmaker(bind=engine,expire_on_commit=False)()
    db.add(GlobalProviderConfig(id=1));customer=Customer(name="Tenant");db.add(customer);db.flush();db.add(ProviderConfig(customer_id=customer.id));db.commit()
    doc=tmp_path/"guide.txt";doc.write_text("Data is encrypted at rest using AES-256. MFA is supported for administrators. Support is available 24x7.",encoding="utf-8")
    ingest(db,doc,"guide.txt",customer.id,"Products",COLLECTIONS)
    qfile=tmp_path/"questions.txt";qfile.write_text("\n".join(questions),encoding="utf-8")
    item=build_questionnaire(db,qfile,"questions.txt",customer.id,COLLECTIONS)
    return db,customer,item

def test_progress_reports_totals_statuses_and_summary(tmp_path):
    db,customer,item=make_workspace(tmp_path,["Do you encrypt data at rest?","Do you support MFA?","Provide your salary bands."])
    progress=new_progress(item.id,customer.id)
    stages=[];run_generation(db,item,progress,on_question_complete=lambda p:stages.append(p["stage"]))
    assert progress["state"]=="completed" and progress["stage"]=="completed"
    assert progress["total"]==3 and progress["completed"]==3 and progress["failed_count"]==0
    statuses=list(progress["question_status"].values())
    assert statuses.count("generated")==2 and statuses.count("manual_review")==1
    summary=progress["summary"]
    assert summary["processed"]==3 and summary["manual"]==1 and summary["failed"]==0
    assert summary["ready"]+summary["check"]+summary["manual"]==3
    assert summary["elapsed_seconds"]>=0 and summary["average_seconds"]>=0
    assert item.status=="generated"

def test_cancel_keeps_completed_answers_and_stops_remaining(tmp_path):
    db,customer,item=make_workspace(tmp_path,["Do you encrypt data at rest?","Do you support MFA?","Is support available 24x7?"])
    progress=new_progress(item.id,customer.id)
    def cancel_after_first(p):
        if p["completed"]==1:p["cancel"]=True
    run_generation(db,item,progress,on_question_complete=cancel_after_first)
    assert progress["state"]=="cancelled"
    assert progress["completed"]==1
    answers=db.scalar(select(Answer).where(Answer.customer_id==customer.id))
    assert answers is not None  # the first answer was committed and survives
    statuses=list(progress["question_status"].values())
    assert statuses.count("cancelled")==2  # remaining questions were never processed
    assert item.status=="generated"  # partially generated questionnaires remain reviewable

def test_resume_after_cancel_only_generates_missing_answers(tmp_path):
    db,customer,item=make_workspace(tmp_path,["Do you encrypt data at rest?","Do you support MFA?","Is support available 24x7?"])
    progress=new_progress(item.id,customer.id)
    def cancel_after_first(p):
        if p["completed"]==1:p["cancel"]=True
    run_generation(db,item,progress,on_question_complete=cancel_after_first)
    assert progress["state"]=="cancelled" and progress["completed"]==1
    resume=new_progress(item.id,customer.id)
    run_generation(db,item,resume,only_missing=True)
    assert resume["state"]=="completed"
    assert resume["total"]==2 and resume["completed"]==2  # only the questions without answers were processed
    questions=list(db.scalars(select(Question).where(Question.questionnaire_id==item.id)))
    assert all(db.scalar(select(Answer).where(Answer.question_id==q.id)) for q in questions)

def test_regeneration_with_approved_suggestions_stores_debug_data(tmp_path):
    """Suggestions embed approved_at inside the debug_data JSON column; a raw datetime there fails the whole question."""
    db,customer,item=make_workspace(tmp_path,["Do you encrypt data at rest?","Is data encrypted at rest?"])
    run_generation(db,item,new_progress(item.id,customer.id))
    answer=db.scalar(select(Answer).where(Answer.customer_id==customer.id).order_by(Answer.id))
    answer.status="approved";answer.approved_at=services.now();answer.reviewer="Reviewer";db.commit()
    progress=new_progress(item.id,customer.id)
    run_generation(db,item,progress)
    assert progress["failed_count"]==0,progress["question_errors"]
    assert progress["state"]=="completed"

def test_full_regeneration_keeps_approved_answers_by_default(tmp_path):
    db,customer,item=make_workspace(tmp_path,["Do you encrypt data at rest?","Do you support MFA?"])
    run_generation(db,item,new_progress(item.id,customer.id))
    first=db.scalar(select(Answer).where(Answer.customer_id==customer.id).order_by(Answer.id))
    first.status="approved";first.text="Reviewed final wording.";first.approved_at=services.now();db.commit()
    progress=new_progress(item.id,customer.id)
    run_generation(db,item,progress)
    assert progress["total"]==1  # the approved answer was skipped
    db.refresh(first)
    assert first.status=="approved" and first.text=="Reviewed final wording."
    explicit=new_progress(item.id,customer.id)
    run_generation(db,item,explicit,include_approved=True)
    assert explicit["total"]==2
    db.refresh(first)
    assert first.status!="approved"  # explicit opt-in regenerates approved answers too

def test_one_failed_question_does_not_stop_the_rest(tmp_path,monkeypatch):
    db,customer,item=make_workspace(tmp_path,["Do you encrypt data at rest?","Do you support MFA?","Is support available 24x7?"])
    class ExplodingLLM(MockLLMProvider):
        def generate_answer(self,question,context,instructions=""):
            if "MFA" in question:raise RuntimeError("provider timeout")
            return super().generate_answer(question,context,instructions)
    monkeypatch.setattr(services,"get_llm",lambda cfg:ExplodingLLM())
    progress=new_progress(item.id,customer.id)
    run_generation(db,item,progress)
    assert progress["state"]=="completed"
    assert progress["failed_count"]==1
    statuses=list(progress["question_status"].values())
    assert statuses.count("failed")==1 and statuses.count("generated")==2
    assert progress["summary"]["failed"]==1
    assert list(progress["question_errors"].values())==["provider timeout"]  # failure reason recorded per question
    questions=list(db.scalars(select(Question).where(Question.questionnaire_id==item.id).order_by(Question.ordinal)))
    failed_id=[qid for qid,status in progress["question_status"].items() if status=="failed"][0]
    assert db.scalar(select(Answer).where(Answer.question_id==failed_id)) is None
    assert all(db.scalar(select(Answer).where(Answer.question_id==q.id)) for q in questions if q.id!=failed_id)
