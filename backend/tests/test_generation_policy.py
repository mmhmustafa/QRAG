"""Integration tests for the generate-then-verify answer policy."""
from pathlib import Path
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.models import Customer, ProviderConfig, GlobalProviderConfig, Question
from app.services import ingest, build_questionnaire, generate_one, config_for
from app.providers import get_llm, MANUAL

COLLECTIONS=["Product A"]

def make_db():
    engine=create_engine("sqlite:///:memory:");Base.metadata.create_all(engine)
    db=sessionmaker(bind=engine,expire_on_commit=False)()
    db.add(GlobalProviderConfig(id=1));customer=Customer(name="Tenant");db.add(customer);db.flush();db.add(ProviderConfig(customer_id=customer.id));db.commit()
    return db,customer

def add_doc(db,customer,tmp_path,name,content,category):
    path=tmp_path/name;path.write_text(content,encoding="utf-8")
    return ingest(db,path,name,customer.id,category,COLLECTIONS)

def answer_for(db,customer,tmp_path,question):
    path=tmp_path/"question.txt";path.write_text(question,encoding="utf-8")
    item=build_questionnaire(db,path,"question.txt",customer.id,COLLECTIONS)
    q=db.scalar(select(Question).where(Question.questionnaire_id==item.id))
    answer=generate_one(db,q,config_for(db,customer.id),get_llm(config_for(db,customer.id)));db.commit()
    return answer

def test_one_authoritative_document_is_enough(tmp_path):
    db,customer=make_db()
    add_doc(db,customer,tmp_path,"product-guide.txt","Data is encrypted at rest using AES-256 encryption for all customer data.","Products")
    answer=answer_for(db,customer,tmp_path,"Do you encrypt data at rest?")
    assert answer.status=="approved_candidate"
    assert answer.classification_reason.startswith("Answered from product-guide.txt")
    assert answer.sources[0]["role"]=="primary"

def test_supporting_documents_raise_confidence(tmp_path):
    db,customer=make_db()
    add_doc(db,customer,tmp_path,"product-guide.txt","Data is encrypted at rest using AES-256 encryption for all customer data.","Products")
    single=answer_for(db,customer,tmp_path,"Do you encrypt data at rest?")
    single_confidence=single.confidence
    add_doc(db,customer,tmp_path,"security-guide.txt","All customer data is encrypted at rest using AES-256 encryption.","Security")
    supported=answer_for(db,customer,tmp_path,"Do you encrypt data at rest?")
    assert supported.status=="approved_candidate"
    assert supported.confidence>single_confidence
    assert "supported by" in supported.classification_reason

def test_peer_conflict_keeps_draft_and_names_documents(tmp_path):
    db,customer=make_db()
    add_doc(db,customer,tmp_path,"current-policy.txt","The platform supports MFA authentication for administrator access.","Security")
    add_doc(db,customer,tmp_path,"legacy-policy.txt","The platform does not support MFA authentication for administrator users.","Security")
    answer=answer_for(db,customer,tmp_path,"Do you support MFA authentication for administrators?")
    assert answer.status=="manual_review"
    assert answer.text!=MANUAL  # the draft is never erased
    assert "Documentation disagrees" in answer.classification_reason
    assert "current-policy.txt" in answer.classification_reason and "legacy-policy.txt" in answer.classification_reason

def test_low_authority_contradiction_is_superseded_not_manual(tmp_path):
    db,customer=make_db()
    add_doc(db,customer,tmp_path,"product-guide.txt","Single sign-on SSO is supported via SAML for enterprise users.","Products")
    add_doc(db,customer,tmp_path,"old-marketing.txt","Single sign-on SSO is not supported for enterprise users.","Marketing")
    answer=answer_for(db,customer,tmp_path,"Do you support single sign-on SSO for enterprise users?")
    assert answer.status=="approved_candidate"
    assert answer.debug_data["superseded_documents"]==["old-marketing.txt"]

def test_no_relevant_documentation_still_routes_to_manual(tmp_path):
    db,customer=make_db()
    add_doc(db,customer,tmp_path,"product-guide.txt","Data is encrypted at rest using AES-256.","Products")
    answer=answer_for(db,customer,tmp_path,"Provide your employee salary bands.")
    assert answer.status=="manual_review" and answer.text==MANUAL
    assert answer.classification_reason=="No relevant documentation found in this product scope."
