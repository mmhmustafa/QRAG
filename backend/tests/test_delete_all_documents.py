"""Delete-all removes one customer's documents, chunks, and files without touching other tenants."""
from pathlib import Path
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.models import Customer, ProviderConfig, GlobalProviderConfig, Document, DocumentChunk
from app.services import ingest, delete_all_documents

def make_tenant(db, tmp_path, name):
    customer=Customer(name=name);db.add(customer);db.flush();db.add(ProviderConfig(customer_id=customer.id));db.commit()
    source=tmp_path/f"{name}.txt";source.write_text(f"{name} data is encrypted at rest using AES-256.",encoding="utf-8")
    doc=ingest(db,source,f"{name}.txt",customer.id,"Security",["General"])
    return customer,Path(doc.path)

def test_delete_all_documents_scoped_to_customer(tmp_path):
    engine=create_engine("sqlite:///:memory:");Base.metadata.create_all(engine)
    db=sessionmaker(bind=engine,expire_on_commit=False)()
    db.add(GlobalProviderConfig(id=1));db.commit()
    alpha,alpha_path=make_tenant(db,tmp_path,"alpha")
    beta,beta_path=make_tenant(db,tmp_path,"beta")
    assert delete_all_documents(db,alpha.id)==1
    assert db.scalar(select(func.count(Document.id)).where(Document.customer_id==alpha.id))==0
    assert db.scalar(select(func.count(DocumentChunk.id)).where(DocumentChunk.customer_id==alpha.id))==0
    assert not alpha_path.exists()  # stored file removed from disk
    assert db.scalar(select(func.count(Document.id)).where(Document.customer_id==beta.id))==1
    assert db.scalar(select(func.count(DocumentChunk.id)).where(DocumentChunk.customer_id==beta.id))>0
    assert beta_path.exists()  # other tenant untouched
    assert delete_all_documents(db,alpha.id)==0  # idempotent on an empty knowledge base
