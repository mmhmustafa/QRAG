from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Text, Float, ForeignKey, DateTime, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

def utcnow(): return datetime.now(timezone.utc).replace(tzinfo=None)

class Customer(Base):
    __tablename__="customers"
    id: Mapped[int]=mapped_column(primary_key=True)
    name: Mapped[str]=mapped_column(String(255),unique=True,index=True)
    description: Mapped[str]=mapped_column(Text,default="")
    archived: Mapped[bool]=mapped_column(Boolean,default=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow)
    updated_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow,onupdate=utcnow)
    settings: Mapped[Optional["ProviderConfig"]]=relationship(cascade="all, delete-orphan",uselist=False)

class Document(Base):
    __tablename__="documents"
    id: Mapped[int]=mapped_column(primary_key=True)
    customer_id: Mapped[int]=mapped_column(ForeignKey("customers.id",ondelete="CASCADE"),index=True)
    name: Mapped[str]=mapped_column(String(255)); category: Mapped[str]=mapped_column(String(50),default="Company")
    kind: Mapped[str]=mapped_column(String(30),default="knowledge"); path: Mapped[str]=mapped_column(String(500))
    status: Mapped[str]=mapped_column(String(30),default="uploaded"); size_bytes: Mapped[int]=mapped_column(default=0)
    mime_type: Mapped[str]=mapped_column(String(100),default="application/octet-stream")
    extracted_text_length: Mapped[int]=mapped_column(default=0); embedding_count: Mapped[int]=mapped_column(default=0); vector_count: Mapped[int]=mapped_column(default=0)
    embedding_provider: Mapped[str]=mapped_column(String(50),default="mock"); embedding_model: Mapped[str]=mapped_column(String(150),default="mock-hash-v1"); embedding_dimension: Mapped[int]=mapped_column(default=0); settings_source: Mapped[str]=mapped_column(String(30),default="global_default")
    indexed_chunk_size: Mapped[int]=mapped_column(default=0); indexed_chunk_overlap: Mapped[int]=mapped_column(default=0)
    last_indexed_at: Mapped[Optional[datetime]]=mapped_column(DateTime); error_message: Mapped[Optional[str]]=mapped_column(Text)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow); updated_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow,onupdate=utcnow)
    # Knowledge Collections: user-defined groupings ("Product Alpha", "Security", "Cloud Deployment"); a document belongs to one or more.
    collections: Mapped[list]=mapped_column(JSON,default=list); enabled: Mapped[bool]=mapped_column(Boolean,default=True)
    # Authority tier: 3=Product, 4=Security, 5=Prior questionnaires, 6=Company, 7=Support/Operations, 8=Compliance/Legal, 9=Marketing. Tiers 1-2 are reserved for Golden/Approved answers.
    authority: Mapped[int]=mapped_column(default=6)
    chunks: Mapped[list["DocumentChunk"]]=relationship(cascade="all, delete-orphan",passive_deletes=True)

class DocumentChunk(Base):
    __tablename__="document_chunks"
    id: Mapped[int]=mapped_column(primary_key=True); customer_id: Mapped[int]=mapped_column(ForeignKey("customers.id",ondelete="CASCADE"),index=True)
    document_id: Mapped[int]=mapped_column(ForeignKey("documents.id",ondelete="CASCADE"),index=True)
    content: Mapped[str]=mapped_column(Text); embedding: Mapped[list]=mapped_column(JSON); ordinal: Mapped[int]; page_number: Mapped[Optional[int]]=mapped_column()

class Questionnaire(Base):
    __tablename__="questionnaires"
    id: Mapped[int]=mapped_column(primary_key=True); customer_id: Mapped[int]=mapped_column(ForeignKey("customers.id",ondelete="CASCADE"),index=True)
    name: Mapped[str]=mapped_column(String(255)); status: Mapped[str]=mapped_column(String(30),default="draft")
    path: Mapped[str]=mapped_column(String(500),default=""); created_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow)
    # Knowledge Collections this questionnaire searches; retrieval and answer reuse stay inside them.
    collections: Mapped[list]=mapped_column(JSON,default=list)
    questions: Mapped[list["Question"]]=relationship(cascade="all, delete-orphan",passive_deletes=True)

class Question(Base):
    __tablename__="questions"
    id: Mapped[int]=mapped_column(primary_key=True); customer_id: Mapped[int]=mapped_column(ForeignKey("customers.id",ondelete="CASCADE"),index=True)
    questionnaire_id: Mapped[int]=mapped_column(ForeignKey("questionnaires.id",ondelete="CASCADE"),index=True)
    text: Mapped[str]=mapped_column(Text); ordinal: Mapped[int]
    retrieval_cache: Mapped[Optional[list]]=mapped_column(JSON); retrieval_cache_key: Mapped[Optional[str]]=mapped_column(String(255))
    answer: Mapped[Optional["Answer"]]=relationship(cascade="all, delete-orphan",uselist=False,passive_deletes=True)

class Answer(Base):
    __tablename__="answers"
    id: Mapped[int]=mapped_column(primary_key=True); customer_id: Mapped[int]=mapped_column(ForeignKey("customers.id",ondelete="CASCADE"),index=True)
    question_id: Mapped[int]=mapped_column(ForeignKey("questions.id",ondelete="CASCADE"),unique=True)
    text: Mapped[str]=mapped_column(Text); confidence: Mapped[float]=mapped_column(Float,default=0); status: Mapped[str]=mapped_column(String(30),default="draft")
    sources: Mapped[list]=mapped_column(JSON,default=list); debug_data: Mapped[dict]=mapped_column(JSON,default=dict); updated_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow,onupdate=utcnow)
    classification_reason: Mapped[str]=mapped_column(String(255),default=""); golden: Mapped[bool]=mapped_column(Boolean,default=False); global_approved: Mapped[bool]=mapped_column(Boolean,default=False); reviewer: Mapped[str]=mapped_column(String(150),default=""); approved_at: Mapped[Optional[datetime]]=mapped_column(DateTime); reused_from_answer_id: Mapped[Optional[int]]=mapped_column(); review_started_at: Mapped[Optional[datetime]]=mapped_column(DateTime,default=utcnow); review_duration_seconds: Mapped[int]=mapped_column(default=0); category: Mapped[str]=mapped_column(String(80),default="General"); collections: Mapped[list]=mapped_column(JSON,default=list); evidence_document_ids: Mapped[list]=mapped_column(JSON,default=list)

class AnswerVersion(Base):
    __tablename__="answer_versions"
    id: Mapped[int]=mapped_column(primary_key=True); customer_id: Mapped[int]=mapped_column(ForeignKey("customers.id",ondelete="CASCADE"),index=True); answer_id: Mapped[int]=mapped_column(ForeignKey("answers.id",ondelete="CASCADE"),index=True)
    version: Mapped[int]; text: Mapped[str]=mapped_column(Text); confidence: Mapped[float]=mapped_column(Float); status: Mapped[str]=mapped_column(String(30)); sources: Mapped[list]=mapped_column(JSON,default=list); created_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow)

class ProviderConfig(Base):
    __tablename__="providers_config"
    id: Mapped[int]=mapped_column(primary_key=True); customer_id: Mapped[int]=mapped_column(ForeignKey("customers.id",ondelete="CASCADE"),unique=True,index=True); is_override: Mapped[bool]=mapped_column(Boolean,default=False)
    llm_provider: Mapped[str]=mapped_column(String(50),default="mock"); llm_model: Mapped[str]=mapped_column(String(150),default="mock-grounded-v1")
    embedding_provider: Mapped[str]=mapped_column(String(50),default="mock"); embedding_model: Mapped[str]=mapped_column(String(150),default="mock-hash-v1")
    base_url: Mapped[Optional[str]]=mapped_column(String(500)); api_key: Mapped[Optional[str]]=mapped_column(Text)
    ai_base_url: Mapped[Optional[str]]=mapped_column(String(500)); ai_api_key: Mapped[Optional[str]]=mapped_column(Text); embedding_base_url: Mapped[Optional[str]]=mapped_column(String(500)); embedding_api_key: Mapped[Optional[str]]=mapped_column(Text)
    provider_display_name: Mapped[str]=mapped_column(String(150),default=""); custom_headers: Mapped[Optional[str]]=mapped_column(Text); chat_endpoint_path: Mapped[str]=mapped_column(String(255),default="/chat/completions"); embedding_endpoint_path: Mapped[str]=mapped_column(String(255),default="/embeddings"); openai_compatible_mode: Mapped[bool]=mapped_column(Boolean,default=True)
    temperature: Mapped[float]=mapped_column(Float,default=.1); top_p: Mapped[float]=mapped_column(Float,default=1); top_k: Mapped[int]=mapped_column(default=4)
    max_tokens: Mapped[int]=mapped_column(default=500); timeout: Mapped[int]=mapped_column(default=60); retry_count: Mapped[int]=mapped_column(default=2)
    chunk_size: Mapped[int]=mapped_column(default=900); chunk_overlap: Mapped[int]=mapped_column(default=120)
    prompt_instructions: Mapped[str]=mapped_column(Text,default="Answer only from retrieved context. Never invent facts. Use 'Manual Review Required' when evidence is insufficient.")

class GlobalProviderConfig(Base):
    __tablename__="global_provider_config"
    id: Mapped[int]=mapped_column(primary_key=True,default=1)
    llm_provider: Mapped[str]=mapped_column(String(50),default="mock"); llm_model: Mapped[str]=mapped_column(String(150),default="mock-grounded-v1")
    embedding_provider: Mapped[str]=mapped_column(String(50),default="mock"); embedding_model: Mapped[str]=mapped_column(String(150),default="mock-hash-v1")
    ai_base_url: Mapped[Optional[str]]=mapped_column(String(500)); ai_api_key: Mapped[Optional[str]]=mapped_column(Text); embedding_base_url: Mapped[Optional[str]]=mapped_column(String(500)); embedding_api_key: Mapped[Optional[str]]=mapped_column(Text)
    provider_display_name: Mapped[str]=mapped_column(String(150),default=""); custom_headers: Mapped[Optional[str]]=mapped_column(Text); chat_endpoint_path: Mapped[str]=mapped_column(String(255),default="/chat/completions"); embedding_endpoint_path: Mapped[str]=mapped_column(String(255),default="/embeddings"); openai_compatible_mode: Mapped[bool]=mapped_column(Boolean,default=True)
    temperature: Mapped[float]=mapped_column(Float,default=.1); top_p: Mapped[float]=mapped_column(Float,default=1); top_k: Mapped[int]=mapped_column(default=4)
    max_tokens: Mapped[int]=mapped_column(default=500); timeout: Mapped[int]=mapped_column(default=60); retry_count: Mapped[int]=mapped_column(default=2)
    chunk_size: Mapped[int]=mapped_column(default=900); chunk_overlap: Mapped[int]=mapped_column(default=120)
    prompt_instructions: Mapped[str]=mapped_column(Text,default="Answer only from retrieved context. Never invent facts. Use 'Manual Review Required' when evidence is insufficient.")

class AuditLog(Base):
    __tablename__="audit_logs"
    id: Mapped[int]=mapped_column(primary_key=True); customer_id: Mapped[Optional[int]]=mapped_column(ForeignKey("customers.id",ondelete="CASCADE"),index=True)
    action: Mapped[str]=mapped_column(String(80)); entity_type: Mapped[str]=mapped_column(String(50)); entity_id: Mapped[Optional[int]]
    details: Mapped[dict]=mapped_column(JSON,default=dict); created_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow)
