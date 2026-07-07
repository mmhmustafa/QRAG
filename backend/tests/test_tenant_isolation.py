from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from pathlib import Path
from app.db import Base
from app.models import Customer,ProviderConfig,GlobalProviderConfig,DocumentChunk
from app.services import ingest,retrieve

def test_retrieval_never_crosses_customers():
    engine=create_engine("sqlite:///:memory:");Base.metadata.create_all(engine);db=sessionmaker(bind=engine,expire_on_commit=False)()
    db.add(GlobalProviderConfig(id=1));a,b=Customer(name="A"),Customer(name="B");db.add_all([a,b]);db.flush();db.add_all([ProviderConfig(customer_id=a.id),ProviderConfig(customer_id=b.id)]);db.commit()
    secret=Path(__file__).parent/"fixtures"/"tenant-secret.txt";ingest(db,secret,secret.name,a.id)
    assert retrieve(db,"What is the launch codename?",a.id)
    assert retrieve(db,"What is the launch codename?",b.id)==[]
