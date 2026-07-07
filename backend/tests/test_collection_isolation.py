"""Knowledge Collections must isolate retrieval exactly like the former product scope."""
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.models import Customer, ProviderConfig, GlobalProviderConfig
from app.services import ingest, retrieve

def make_db():
    engine=create_engine("sqlite:///:memory:");Base.metadata.create_all(engine)
    db=sessionmaker(bind=engine,expire_on_commit=False)()
    db.add(GlobalProviderConfig(id=1));customer=Customer(name="Tenant");db.add(customer);db.flush();db.add(ProviderConfig(customer_id=customer.id));db.commit()
    return db,customer

def test_retrieval_stays_inside_selected_collections(tmp_path):
    db,customer=make_db()
    alpha=tmp_path/"alpha.txt";alpha.write_text("Product Alpha encrypts data at rest with AES-256.",encoding="utf-8")
    beta=tmp_path/"beta.txt";beta.write_text("Product Beta encrypts data at rest with AES-128.",encoding="utf-8")
    ingest(db,alpha,"alpha.txt",customer.id,"Products",["Product Alpha","Security"])
    ingest(db,beta,"beta.txt",customer.id,"Products",["Product Beta"])
    alpha_results=retrieve(db,"Do you encrypt data at rest?",customer.id,collections=["Product Alpha"])
    assert {x["document"] for x in alpha_results}=={"alpha.txt"}
    beta_results=retrieve(db,"Do you encrypt data at rest?",customer.id,collections=["Product Beta"])
    assert {x["document"] for x in beta_results}=={"beta.txt"}
    both=retrieve(db,"Do you encrypt data at rest?",customer.id,collections=["Product Alpha","Product Beta"])
    assert {x["document"] for x in both}=={"alpha.txt","beta.txt"}
    # A collection selection matching nothing retrieves nothing.
    assert retrieve(db,"Do you encrypt data at rest?",customer.id,collections=["Regional Documentation"])==[]
    # Shared collection reaches documents from both products.
    shared=retrieve(db,"Do you encrypt data at rest?",customer.id,collections=["Security"])
    assert {x["document"] for x in shared}=={"alpha.txt"}

def test_documents_default_to_general_collection(tmp_path):
    db,customer=make_db()
    doc_path=tmp_path/"untagged.txt";doc_path.write_text("Support is available 24x7.",encoding="utf-8")
    doc=ingest(db,doc_path,"untagged.txt",customer.id)
    assert doc.collections==["General"]
    assert retrieve(db,"Is support available 24x7?",customer.id,collections=["General"])
