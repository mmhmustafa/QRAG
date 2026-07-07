"""Upload-time transparency: detected numbered questions are reported so silent extraction loss is visible."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.models import Customer, ProviderConfig, GlobalProviderConfig
from app.services import build_questionnaire, detect_numbered_questions

def test_detect_numbered_questions_counts_distinct_markers():
    assert detect_numbered_questions("Q1. First?\nfiller\nQ2. Second?\nQ2. Duplicate marker")==2
    assert detect_numbered_questions("Do you support MFA?\nNo numbering here")==0

def test_build_questionnaire_reports_detected_count(tmp_path):
    engine=create_engine("sqlite:///:memory:");Base.metadata.create_all(engine)
    db=sessionmaker(bind=engine,expire_on_commit=False)()
    db.add(GlobalProviderConfig(id=1));customer=Customer(name="Tenant");db.add(customer);db.flush();db.add(ProviderConfig(customer_id=customer.id));db.commit()
    source=tmp_path/"q.txt";source.write_text("Q1. Do you encrypt data at rest?\nQ2. Provide your certifications.",encoding="utf-8")
    item=build_questionnaire(db,source,"q.txt",customer.id,["General"])
    assert len(item.questions)==2
    assert item.detected_question_count==2
