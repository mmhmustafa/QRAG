from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.models import Customer,ProviderConfig,GlobalProviderConfig
from app.services import config_for
from app.providers import custom_headers

def test_global_defaults_and_customer_override():
    engine=create_engine("sqlite:///:memory:");Base.metadata.create_all(engine);db=sessionmaker(bind=engine,expire_on_commit=False)()
    global_cfg=GlobalProviderConfig(id=1,embedding_provider="openrouter",embedding_model="global/embed",llm_provider="openrouter",llm_model="global/chat")
    customer=Customer(name="Inherited");db.add_all([global_cfg,customer]);db.flush();row=ProviderConfig(customer_id=customer.id,is_override=False,embedding_provider="mock",embedding_model="old");db.add(row);db.commit()
    effective=config_for(db,customer.id);assert effective.embedding_provider=="openrouter";assert effective.settings_source=="global_default"
    row.is_override=True;row.embedding_provider="ollama";row.embedding_model="local/embed";db.commit();effective=config_for(db,customer.id);assert effective.embedding_provider=="ollama";assert effective.settings_source=="customer_override"

def test_custom_enterprise_headers():
    cfg=type("Config",(),{"custom_headers":'{"X-Organization":"MedNova","X-Token":"secret"}'})()
    assert custom_headers(cfg)=={"X-Organization":"MedNova","X-Token":"secret"}
