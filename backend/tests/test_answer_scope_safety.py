from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.models import Customer, Questionnaire, Question, Answer, Document
from app.services import approved_suggestions

def test_approved_answers_are_collection_and_customer_scoped_unless_global():
    engine=create_engine("sqlite:///:memory:");Base.metadata.create_all(engine);db=sessionmaker(bind=engine,expire_on_commit=False)()
    first=Customer(name="Vendor Product A");second=Customer(name="Vendor Product B");db.add_all([first,second]);db.flush()
    questionnaire=Questionnaire(customer_id=first.id,name="A",path="a",collections=["Product Alpha","Security"]);db.add(questionnaire);db.flush()
    question=Question(customer_id=first.id,questionnaire_id=questionnaire.id,text="Do you support MFA?",ordinal=1);doc=Document(customer_id=first.id,name="security.txt",path="security.txt",category="Security",collections=["Product Alpha","Security"],status="indexed",enabled=True);db.add_all([question,doc]);db.flush()
    answer=Answer(customer_id=first.id,question_id=question.id,text="MFA is supported.",confidence=.9,status="approved",category="Security",collections=["Product Alpha","Security"],evidence_document_ids=[doc.id],sources=[{"document_id":doc.id,"document":"security.txt"}],approved_at=datetime.now()+timedelta(seconds=1));db.add(answer);db.commit()
    # Same customer, overlapping collection: reusable.
    assert approved_suggestions(db,"Is MFA supported?",first.id,["Product Alpha"],category="Security")
    # Same customer, disjoint collection: not reusable.
    assert approved_suggestions(db,"Is MFA supported?",first.id,["Product Beta"],category="Security")==[]
    # Different customer: never reusable without explicit global approval.
    assert approved_suggestions(db,"Is MFA supported?",second.id,["Product Alpha"],category="Security")==[]
    answer.global_approved=True;db.commit()
    assert approved_suggestions(db,"Is MFA supported?",second.id,["Product Beta"],category="Security")[0]["match_badge"]=="Global Approved Answer"
