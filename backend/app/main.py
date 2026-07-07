from pathlib import Path
from datetime import datetime, timezone
import json
import shutil
import time
import httpx
from types import SimpleNamespace
from uuid import uuid4
from fastapi import FastAPI,UploadFile,File,Form,Depends,HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse,FileResponse
from pydantic import BaseModel,Field
from sqlalchemy import select,func,delete,inspect,text
from sqlalchemy.orm import Session,selectinload
from .config import settings
from .db import Base,engine,get_db,SessionLocal
from .models import Customer,Document,DocumentChunk,Questionnaire,Question,Answer,AnswerVersion,ProviderConfig,GlobalProviderConfig,AuditLog
from .services import ingest,build_questionnaire,export_xlsx,export_pdf,index_document,generate_questionnaire,generate_one,config_for,retrieve,parse_file,approved_suggestions,suggestion_pool,suggestions_from_pool,CATEGORY_AUTHORITY,authority_for,start_generation,generation_progress,request_generation_cancel,GENERATION_STAGES,delete_all_documents,backup_sqlite_database,apply_version_restore
from .providers import get_llm,get_embeddings

Base.metadata.create_all(engine)
CONFIG_FIELDS=("llm_provider","llm_model","embedding_provider","embedding_model","ai_base_url","ai_api_key","embedding_base_url","embedding_api_key","provider_display_name","custom_headers","chat_endpoint_path","embedding_endpoint_path","openai_compatible_mode","temperature","top_p","top_k","max_tokens","timeout","retry_count","chunk_size","chunk_overlap","prompt_instructions")
def config_values(source,include_secrets=True):return {name:getattr(source,name,None) for name in CONFIG_FIELDS if include_secrets or name not in {"ai_api_key","embedding_api_key","custom_headers"}}
def migrate_legacy_sqlite():
    if not settings.database_url.startswith("sqlite"):return
    custom={"provider_display_name":"VARCHAR(150) DEFAULT ''","custom_headers":"TEXT","chat_endpoint_path":"VARCHAR(255) DEFAULT '/chat/completions'","embedding_endpoint_path":"VARCHAR(255) DEFAULT '/embeddings'","openai_compatible_mode":"BOOLEAN DEFAULT 1"}
    additions={"documents":{"customer_id":"INTEGER","category":"VARCHAR(50) DEFAULT 'Company'","size_bytes":"INTEGER DEFAULT 0","mime_type":"VARCHAR(100) DEFAULT 'application/octet-stream'","updated_at":"DATETIME","extracted_text_length":"INTEGER DEFAULT 0","embedding_count":"INTEGER DEFAULT 0","vector_count":"INTEGER DEFAULT 0","embedding_provider":"VARCHAR(50) DEFAULT 'mock'","embedding_model":"VARCHAR(150) DEFAULT 'mock-hash-v1'","embedding_dimension":"INTEGER DEFAULT 0","last_indexed_at":"DATETIME","error_message":"TEXT"},"document_chunks":{"customer_id":"INTEGER"},"questionnaires":{"customer_id":"INTEGER","path":"VARCHAR(500) DEFAULT ''"},"questions":{"customer_id":"INTEGER"},"answers":{"customer_id":"INTEGER","classification_reason":"VARCHAR(255) DEFAULT ''","golden":"BOOLEAN DEFAULT 0","reviewer":"VARCHAR(150) DEFAULT ''","approved_at":"DATETIME","reused_from_answer_id":"INTEGER","review_started_at":"DATETIME","review_duration_seconds":"INTEGER DEFAULT 0","category":"VARCHAR(80) DEFAULT 'General'"},"providers_config":{"customer_id":"INTEGER","api_key":"TEXT","is_override":"BOOLEAN DEFAULT 0","ai_base_url":"VARCHAR(500)","ai_api_key":"TEXT","embedding_base_url":"VARCHAR(500)","embedding_api_key":"TEXT","top_p":"FLOAT DEFAULT 1","top_k":"INTEGER DEFAULT 4","timeout":"INTEGER DEFAULT 60","retry_count":"INTEGER DEFAULT 2","chunk_size":"INTEGER DEFAULT 900","chunk_overlap":"INTEGER DEFAULT 120","prompt_instructions":"TEXT DEFAULT ''",**custom},"global_provider_config":custom,"audit_logs":{"customer_id":"INTEGER"}}
    with engine.begin() as conn:
        tables=set(inspect(conn).get_table_names())
        for table,cols in additions.items():
            if table not in tables:continue
            existing={x["name"] for x in inspect(conn).get_columns(table)}
            for col,ddl in cols.items():
                if col not in existing:conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
        still_needed={"documents":{"enabled":"BOOLEAN DEFAULT 1"},"answers":{"global_approved":"BOOLEAN DEFAULT 0","evidence_document_ids":"JSON DEFAULT '[]'"}}
        for table,cols in still_needed.items():
            existing={x["name"] for x in inspect(conn).get_columns(table)}
            for col,ddl in cols.items():
                if col not in existing:conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
        # Knowledge Collections replace the former product scope; migrate legacy scope values into collections where present.
        def legacy_collections(product_name,product_version,product_line,document_collection):
            out=[];name=(product_name or "").strip();version=(product_version or "").strip();line=(product_line or "").strip();coll=(document_collection or "").strip()
            if name:out.append(f"{name} {version}".strip())
            if line and line not in out:out.append(line)
            if coll and coll.lower()!="default" and coll not in out:out.append(coll)
            return out or ["General"]
        for table in ("documents","questionnaires","answers"):
            columns={x["name"] for x in inspect(conn).get_columns(table)}
            if "collections" in columns:continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN collections JSON DEFAULT '[]'"))
            if "product_name" in columns:
                for row_id,name,version,line,coll in conn.execute(text(f"SELECT id,product_name,product_version,product_line,document_collection FROM {table}")).all():
                    conn.execute(text(f"UPDATE {table} SET collections=:collections WHERE id=:id"),{"collections":json.dumps(legacy_collections(name,version,line,coll)),"id":row_id})
            else:conn.execute(text(f"UPDATE {table} SET collections='[\"General\"]'"))
        # Drop the retired product-scope columns after backfill; legacy schemas declared them NOT NULL, which would reject new inserts.
        legacy_drop={"documents":["product_name","product_version","product_line","document_collection"],"questionnaires":["product_name","product_version","product_line","document_collection","selected_categories"],"answers":["product_name","product_version","product_line","document_collection"]}
        for table,legacy in legacy_drop.items():
            existing={x["name"] for x in inspect(conn).get_columns(table)}
            for col in legacy:
                if col in existing:conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {col}"))
        document_columns={x["name"] for x in inspect(conn).get_columns("documents")}
        if "authority" not in document_columns:
            conn.execute(text("ALTER TABLE documents ADD COLUMN authority INTEGER DEFAULT 6"))
            for category,tier in CATEGORY_AUTHORITY.items():conn.execute(text("UPDATE documents SET authority=:tier WHERE category=:category"),{"tier":tier,"category":category})
        if "settings_source" not in document_columns:conn.execute(text("ALTER TABLE documents ADD COLUMN settings_source VARCHAR(30) DEFAULT 'global_default'"))
        if "indexed_chunk_size" not in document_columns:conn.execute(text("ALTER TABLE documents ADD COLUMN indexed_chunk_size INTEGER DEFAULT 0"))
        if "indexed_chunk_overlap" not in document_columns:conn.execute(text("ALTER TABLE documents ADD COLUMN indexed_chunk_overlap INTEGER DEFAULT 0"))
        chunk_columns={x["name"] for x in inspect(conn).get_columns("document_chunks")}
        if "page_number" not in chunk_columns:conn.execute(text("ALTER TABLE document_chunks ADD COLUMN page_number INTEGER"))
        question_columns={x["name"] for x in inspect(conn).get_columns("questions")}
        if "retrieval_cache" not in question_columns:conn.execute(text("ALTER TABLE questions ADD COLUMN retrieval_cache JSON"))
        if "retrieval_cache_key" not in question_columns:conn.execute(text("ALTER TABLE questions ADD COLUMN retrieval_cache_key VARCHAR(255)"))
        answer_columns={x["name"] for x in inspect(conn).get_columns("answers")}
        if "debug_data" not in answer_columns:conn.execute(text("ALTER TABLE answers ADD COLUMN debug_data JSON DEFAULT '{}'"))
    with SessionLocal() as db:
        customer=db.scalar(select(Customer).order_by(Customer.id))
        if not customer:customer=Customer(name="Default Organization",description="Migrated MVP workspace");db.add(customer);db.flush()
        for model in (Document,DocumentChunk,Questionnaire,Question,Answer,AuditLog):db.execute(model.__table__.update().where(model.customer_id.is_(None)).values(customer_id=customer.id))
        configs=list(db.scalars(select(ProviderConfig)))
        if configs:
            for cfg in configs:
                if cfg.customer_id is None:cfg.customer_id=customer.id
                if not cfg.ai_base_url:cfg.ai_base_url=cfg.base_url
                if not cfg.embedding_base_url:cfg.embedding_base_url=cfg.base_url
                if not cfg.ai_api_key:cfg.ai_api_key=cfg.api_key
                if not cfg.embedding_api_key:cfg.embedding_api_key=cfg.api_key
        else:db.add(ProviderConfig(customer_id=customer.id))
        db.commit()
        global_cfg=db.get(GlobalProviderConfig,1)
        if not global_cfg:
            seed=db.scalar(select(ProviderConfig).order_by(ProviderConfig.customer_id))
            values=config_values(seed) if seed else {}
            if seed:
                values["ai_base_url"]=seed.ai_base_url or seed.base_url;values["ai_api_key"]=seed.ai_api_key or seed.api_key;values["embedding_base_url"]=seed.embedding_base_url or seed.base_url;values["embedding_api_key"]=seed.embedding_api_key or seed.api_key
            global_cfg=GlobalProviderConfig(id=1,**values);db.add(global_cfg);db.flush()
            for index,cfg in enumerate(db.scalars(select(ProviderConfig).order_by(ProviderConfig.customer_id))):cfg.is_override=index>0
            db.commit()
        for doc in db.scalars(select(Document)):
            cfg=config_for(db,doc.customer_id)
            customer_cfg=db.scalar(select(ProviderConfig).where(ProviderConfig.customer_id==doc.customer_id));doc.settings_source="customer_override" if customer_cfg and customer_cfg.is_override else "global_default"
            if cfg and (doc.embedding_provider!=cfg.embedding_provider or doc.embedding_model!=cfg.embedding_model or not doc.embedding_dimension):doc.status="uploaded";doc.error_message="Embedding settings differ from stored vectors; re-index required"
        db.commit()
backup_sqlite_database();migrate_legacy_sqlite();settings.upload_dir.mkdir(parents=True,exist_ok=True)
app=FastAPI(title="Customer Questionnaire Assistant",version="0.2.0")
app.add_middleware(CORSMiddleware,allow_origins=settings.cors_origins.split(","),allow_methods=["*"],allow_headers=["*"])

def customer_or_404(db,cid):
    item=db.get(Customer,cid)
    if not item:raise HTTPException(404,"Customer not found")
    return item
def scoped(db,model,item_id,cid):
    item=db.scalar(select(model).where(model.id==item_id,model.customer_id==cid))
    if not item:raise HTTPException(404,"Not found")
    return item
# Diagnostic fields the review cards read; the heavyweight debug payload (prompt, chunk copies) ships only with ?debug=1.
DEBUG_SUMMARY_FIELDS=("conflicting_documents","superseded_documents","retrieval_quality","evidence_consistency","evidence_analysis","execution_time_ms","cache_hit","llm_verified")
def answer_dict(q,pool=None,include_debug=False):
    if not q.answer:return {"id":q.id,"text":q.text,"ordinal":q.ordinal,"answer":None}
    # Suggestions only matter while an answer is still reviewable; approved/rejected cards never show the reuse panel.
    suggestions=suggestions_from_pool(pool,q.text,q.customer_id,q.answer.collections,q.answer.category,q.answer.id) if pool is not None and q.answer.status not in {"approved","rejected"} else []
    debug=q.answer.debug_data or {}
    if not include_debug:debug={key:debug.get(key) for key in DEBUG_SUMMARY_FIELDS}
    answer={"id":q.answer.id,"text":q.answer.text,"confidence":q.answer.confidence,"status":q.answer.status,"classification_reason":q.answer.classification_reason,"golden":q.answer.golden,"global_approved":q.answer.global_approved,"collections":q.answer.collections or [],"category":q.answer.category,"reviewer":q.answer.reviewer,"approved_at":q.answer.approved_at,"reused_from_answer_id":q.answer.reused_from_answer_id,"sources":q.answer.sources,"debug_data":debug,"suggestions":suggestions}
    return {"id":q.id,"text":q.text,"ordinal":q.ordinal,"answer":answer}
@app.get("/health")
def health():return {"status":"ok","version":"0.2.0"}

class CustomerBody(BaseModel):name:str=Field(min_length=1,max_length=255);description:str=""
@app.get("/api/customers")
def customers(include_archived:bool=True,db:Session=Depends(get_db)):
    query=select(Customer).order_by(Customer.archived,Customer.name)
    if not include_archived:query=query.where(Customer.archived==False)
    items=[]
    for x in db.scalars(query):
        cfg=db.scalar(select(ProviderConfig).where(ProviderConfig.customer_id==x.id));items.append({"id":x.id,"name":x.name,"description":x.description,"archived":x.archived,"created_at":x.created_at,"updated_at":x.updated_at,"document_count":db.scalar(select(func.count(Document.id)).where(Document.customer_id==x.id)),"questionnaire_count":db.scalar(select(func.count(Questionnaire.id)).where(Questionnaire.customer_id==x.id)),"llm_provider":cfg.llm_provider if cfg else "mock"})
    return items
@app.post("/api/customers")
def create_customer(body:CustomerBody,db:Session=Depends(get_db)):
    if db.scalar(select(Customer).where(Customer.name==body.name)):raise HTTPException(409,"Customer name already exists")
    item=Customer(**body.model_dump());db.add(item);db.flush();global_cfg=db.get(GlobalProviderConfig,1);db.add(ProviderConfig(customer_id=item.id,is_override=False,**(config_values(global_cfg,False) if global_cfg else {})));db.add(AuditLog(customer_id=item.id,action="customer_create",entity_type="customer",entity_id=item.id,details={"settings":"global_default"}));db.commit();return {"id":item.id,"name":item.name}
@app.patch("/api/customers/{cid}")
def edit_customer(cid:int,body:CustomerBody,db:Session=Depends(get_db)):
    item=customer_or_404(db,cid);item.name=body.name;item.description=body.description;db.commit();return {"ok":True}
@app.post("/api/customers/{cid}/archive")
def archive_customer(cid:int,db:Session=Depends(get_db)):
    item=customer_or_404(db,cid);item.archived=not item.archived;db.commit();return {"archived":item.archived}
@app.delete("/api/customers/{cid}")
def delete_customer(cid:int,db:Session=Depends(get_db)):
    item=customer_or_404(db,cid)
    # Explicit deletion keeps SQLite and external vector-store semantics identical even when FK cascades are disabled.
    for model in (AnswerVersion,Answer,Question,Questionnaire,DocumentChunk,Document,AuditLog,ProviderConfig):db.execute(delete(model).where(model.customer_id==cid))
    db.delete(item);db.commit();shutil.rmtree(settings.upload_dir/str(cid),ignore_errors=True);return {"ok":True}

@app.get("/api/customers/{cid}/dashboard")
def dashboard(cid:int,db:Session=Depends(get_db)):
    customer_or_404(db,cid);cfg=db.scalar(select(ProviderConfig).where(ProviderConfig.customer_id==cid));activity=list(db.scalars(select(AuditLog).where(AuditLog.customer_id==cid).order_by(AuditLog.id.desc()).limit(8)))
    def activity_href(entry):
        # Frontend route for the entity so activity rows are clickable, not dead text.
        if entry.entity_type=="questionnaire" and entry.entity_id:return f"/questionnaires/{entry.entity_id}"
        if entry.entity_type=="document":return "/knowledge"
        if entry.entity_type=="settings":return "/settings"
        if entry.entity_type=="customer":return "/customers"
        if entry.entity_type=="answer" and entry.entity_id:
            qid=db.scalar(select(Question.questionnaire_id).join(Answer,Answer.question_id==Question.id).where(Answer.id==entry.entity_id))
            return f"/questionnaires/{qid}" if qid else None
        return None
    total=db.scalar(select(func.count(Answer.id)).where(Answer.customer_id==cid)) or 0;approved=db.scalar(select(func.count(Answer.id)).where(Answer.customer_id==cid,Answer.status=="approved")) or 0;golden=db.scalar(select(func.count(Answer.id)).where(Answer.customer_id==cid,Answer.golden==True)) or 0;reused=db.scalar(select(func.count(Answer.id)).where(Answer.customer_id==cid,Answer.reused_from_answer_id.is_not(None))) or 0;manual=db.scalar(select(func.count(Answer.id)).where(Answer.customer_id==cid,Answer.status=="manual_review")) or 0;avg=db.scalar(select(func.avg(Answer.confidence)).where(Answer.customer_id==cid)) or 0;review_seconds=db.scalar(select(func.avg(Answer.review_duration_seconds)).where(Answer.customer_id==cid,Answer.review_duration_seconds>0)) or 0
    return {"customers":db.scalar(select(func.count(Customer.id)).where(Customer.archived==False)),"documents":db.scalar(select(func.count(Document.id)).where(Document.customer_id==cid)),"questionnaires":db.scalar(select(func.count(Questionnaire.id)).where(Questionnaire.customer_id==cid)),"llm_provider":cfg.llm_provider,"embedding_provider":cfg.embedding_provider,"questions_generated":total,"questions_approved":approved,"golden_answers":golden,"answers_reused":reused,"manual_reviews":manual,"average_confidence":round(float(avg),2),"average_review_seconds":round(float(review_seconds)),"estimated_minutes_saved":reused*3+approved,"recent_activity":[{"id":x.id,"action":x.action,"details":x.details,"created_at":x.created_at,"href":activity_href(x)} for x in activity]}

CATEGORIES={"Company","Products","Security","Compliance","Legal","Support","Operations","Previous Questionnaires"}
ALLOWED_EXTENSIONS={".pdf",".docx",".xlsx",".csv",".txt"}
MAX_UPLOAD_BYTES=25*1024*1024
def parse_collections(raw):return [x.strip() for x in (raw or "").split(",") if x.strip()]
@app.post("/api/customers/{cid}/documents")
async def upload_document(cid:int,file:UploadFile=File(...),category:str=Form("Company"),collections:str=Form(""),db:Session=Depends(get_db)):
    customer_or_404(db,cid)
    if category not in CATEGORIES:raise HTTPException(400,"Invalid category")
    safe_name=Path(file.filename or "upload").name
    if Path(safe_name).suffix.lower() not in ALLOWED_EXTENSIONS:raise HTTPException(400,"Unsupported file type. Use PDF, DOCX, XLSX, CSV, or TXT.")
    content=await file.read(MAX_UPLOAD_BYTES+1)
    if len(content)>MAX_UPLOAD_BYTES:raise HTTPException(413,"File exceeds the 25 MB maximum size")
    folder=settings.upload_dir/str(cid)/"knowledge";folder.mkdir(parents=True,exist_ok=True);path=folder/f"{uuid4().hex}_{safe_name}";path.write_bytes(content)
    try:doc=ingest(db,path,safe_name,cid,category,parse_collections(collections) or ["General"])
    except Exception as exc:raise HTTPException(422,f"Indexing failed: {exc}")
    return {"id":doc.id,"name":doc.name,"status":doc.status,"collections":doc.collections}
@app.get("/api/customers/{cid}/documents")
def documents(cid:int,db:Session=Depends(get_db)):
    customer_or_404(db,cid);count=select(DocumentChunk.document_id,func.count(DocumentChunk.id).label("n")).where(DocumentChunk.customer_id==cid).group_by(DocumentChunk.document_id).subquery()
    rows=db.execute(select(Document,count.c.n).outerjoin(count,count.c.document_id==Document.id).where(Document.customer_id==cid).order_by(Document.id.desc())).all()
    return [{"id":d.id,"name":d.name,"category":d.category,"authority":d.authority,"collections":d.collections or [],"enabled":d.enabled,"status":d.status,"size_bytes":d.size_bytes,"chunk_count":n or 0,"created_at":d.created_at,"updated_at":d.updated_at,"extracted_text_length":d.extracted_text_length,"embedding_count":d.embedding_count,"vector_count":d.vector_count,"embedding_provider":d.embedding_provider,"embedding_model":d.embedding_model,"embedding_dimension":d.embedding_dimension,"settings_source":d.settings_source,"indexed_chunk_size":d.indexed_chunk_size,"indexed_chunk_overlap":d.indexed_chunk_overlap,"last_indexed_at":d.last_indexed_at,"error_message":d.error_message} for d,n in rows]
@app.get("/api/customers/{cid}/collections")
def customer_collections(cid:int,db:Session=Depends(get_db)):
    customer_or_404(db,cid);documents=list(db.scalars(select(Document).where(Document.customer_id==cid,Document.enabled==True)))
    collections={}
    for doc in documents:
        for name in doc.collections or []:
            item=collections.setdefault(name,{"name":name,"document_count":0,"categories":set()});item["document_count"]+=1;item["categories"].add(doc.category)
    return sorted(({**item,"categories":sorted(item["categories"])} for item in collections.values()),key=lambda x:x["name"].lower())
@app.get("/api/customers/{cid}/documents/index-config")
def document_index_config(cid:int,db:Session=Depends(get_db)):
    customer=customer_or_404(db,cid);cfg=config_for(db,cid);mismatched=db.scalar(select(func.count(Document.id)).where(Document.customer_id==cid,((Document.embedding_provider!=cfg.embedding_provider)|(Document.embedding_model!=cfg.embedding_model)|(Document.embedding_dimension<=0)|(Document.indexed_chunk_size!=cfg.chunk_size)|(Document.indexed_chunk_overlap!=cfg.chunk_overlap))))
    return {"customer_id":customer.id,"customer_name":customer.name,"embedding_provider":cfg.embedding_provider,"embedding_model":cfg.embedding_model,"base_url":getattr(cfg,"embedding_base_url",None) or getattr(cfg,"base_url",None) or "provider default","settings_source":cfg.settings_source,"documents_requiring_reindex":mismatched}
class DocumentUpdate(BaseModel):name:str;category:str;collections:list[str]|None=None
@app.patch("/api/customers/{cid}/documents/{did}")
def update_document(cid:int,did:int,body:DocumentUpdate,db:Session=Depends(get_db)):
    doc=scoped(db,Document,did,cid);doc.name=body.name
    if doc.category!=body.category:doc.category=body.category;doc.authority=authority_for(body.category)
    if body.collections is not None:doc.collections=[x.strip() for x in body.collections if x.strip()] or ["General"]
    db.commit();return {"ok":True}
@app.delete("/api/customers/{cid}/documents/{did}")
def delete_document(cid:int,did:int,db:Session=Depends(get_db)):
    doc=scoped(db,Document,did,cid);path=Path(doc.path);db.execute(delete(DocumentChunk).where(DocumentChunk.customer_id==cid,DocumentChunk.document_id==did));db.delete(doc);db.add(AuditLog(customer_id=cid,action="document_delete",entity_type="document",entity_id=did,details={"name":doc.name}));db.commit();path.unlink(missing_ok=True);return {"ok":True}
@app.post("/api/customers/{cid}/documents/{did}/reindex")
def reindex_document(cid:int,did:int,db:Session=Depends(get_db)):
    doc=scoped(db,Document,did,cid);count=index_document(db,doc);db.add(AuditLog(customer_id=cid,action="document_reindex",entity_type="document",entity_id=did,details={"chunks":count,"embedding_provider":doc.embedding_provider,"embedding_model":doc.embedding_model}));db.commit();return {"chunks":count,"vectors":doc.vector_count,"embedding_provider":doc.embedding_provider,"embedding_model":doc.embedding_model}
@app.delete("/api/customers/{cid}/documents")
def delete_documents(cid:int,db:Session=Depends(get_db)):
    customer_or_404(db,cid);return {"deleted":delete_all_documents(db,cid)}
@app.post("/api/customers/{cid}/documents/reindex-all")
def reindex_all_documents(cid:int,db:Session=Depends(get_db)):
    customer_or_404(db,cid);docs=list(db.scalars(select(Document).where(Document.customer_id==cid).order_by(Document.id)));results=[];total=0
    for doc in docs:
        try:count=index_document(db,doc);total+=count;results.append({"id":doc.id,"name":doc.name,"ok":True,"vectors":count})
        except Exception as exc:results.append({"id":doc.id,"name":doc.name,"ok":False,"error":str(exc)})
    cfg=config_for(db,cid);db.add(AuditLog(customer_id=cid,action="document_reindex_all",entity_type="customer",entity_id=cid,details={"documents":len(docs),"vectors":total,"failures":sum(not x["ok"] for x in results),"embedding_provider":cfg.embedding_provider,"embedding_model":cfg.embedding_model}));db.commit();return {"documents":len(docs),"vector_records":total,"embedding_provider":cfg.embedding_provider,"embedding_model":cfg.embedding_model,"results":results}
class RetrievalTest(BaseModel):customer_id:int;question:str=Field(min_length=1);collections:list[str]=Field(min_length=1)
@app.post("/api/customers/{cid}/retrieval/test")
def test_retrieval(cid:int,body:RetrievalTest,db:Session=Depends(get_db)):
    customer_or_404(db,cid)
    if body.customer_id!=cid:raise HTTPException(400,"Customer scope does not match the active customer")
    started=time.perf_counter();results=retrieve(db,body.question,cid,collections=body.collections);return {"question":body.question,"collections":body.collections,"count":len(results),"latency_ms":round((time.perf_counter()-started)*1000,1),"results":[{"document":x["document"],"document_id":x["document_id"],"chunk_id":x["chunk_id"],"similarity_score":round(x["score"],4),"text":x["content"],"metadata":{"category":x["category"],"collections":x.get("collections",[]),"embedding_provider":x["embedding_provider"],"embedding_model":x["embedding_model"]}} for x in results]}
@app.post("/api/customers/{cid}/documents/{did}/replace")
async def replace_document(cid:int,did:int,file:UploadFile=File(...),db:Session=Depends(get_db)):
    doc=scoped(db,Document,did,cid);old=Path(doc.path);safe_name=Path(file.filename or "replacement").name
    if Path(safe_name).suffix.lower() not in ALLOWED_EXTENSIONS:raise HTTPException(400,"Unsupported file type")
    content=await file.read(MAX_UPLOAD_BYTES+1)
    if len(content)>MAX_UPLOAD_BYTES:raise HTTPException(413,"File exceeds the 25 MB maximum size")
    path=old.parent/f"{uuid4().hex}_{safe_name}";path.write_bytes(content)
    try:
        doc.path=str(path);doc.name=safe_name;doc.size_bytes=path.stat().st_size;count=index_document(db,doc);db.add(AuditLog(customer_id=cid,action="document_reindex",entity_type="document",entity_id=did,details={"reason":"replacement","chunks":count}));db.commit()
    except Exception:
        db.rollback();path.unlink(missing_ok=True);raise
    old.unlink(missing_ok=True);return {"id":did,"chunks":count}
@app.get("/api/customers/{cid}/documents/{did}/download")
def download_document(cid:int,did:int,db:Session=Depends(get_db)):
    doc=scoped(db,Document,did,cid);return FileResponse(doc.path,filename=doc.name)
@app.get("/api/customers/{cid}/documents/{did}/preview")
def preview_document(cid:int,did:int,chunk_id:int|None=None,db:Session=Depends(get_db)):
    doc=scoped(db,Document,did,cid);chunk=None
    if chunk_id:chunk=db.scalar(select(DocumentChunk).where(DocumentChunk.id==chunk_id,DocumentChunk.customer_id==cid,DocumentChunk.document_id==did))
    return {"id":doc.id,"name":doc.name,"category":doc.category,"type":Path(doc.path).suffix.lower().lstrip("."),"text":parse_file(Path(doc.path)),"chunk":None if not chunk else {"id":chunk.id,"content":chunk.content,"page_number":chunk.page_number},"download_url":f"/api/customers/{cid}/documents/{did}/download"}

@app.post("/api/customers/{cid}/questionnaires")
async def upload_questionnaire(cid:int,file:UploadFile=File(...),collections:str=Form(""),db:Session=Depends(get_db)):
    customer_or_404(db,cid);selected=parse_collections(collections)
    if not selected:raise HTTPException(400,"Select at least one Knowledge Collection to search")
    safe_name=Path(file.filename or "questionnaire").name;folder=settings.upload_dir/str(cid)/"questionnaires";folder.mkdir(parents=True,exist_ok=True);path=folder/f"{uuid4().hex}_{safe_name}";path.write_bytes(await file.read());item=build_questionnaire(db,path,safe_name,cid,selected);return {"id":item.id,"name":item.name,"question_count":len(item.questions),"detected_questions":getattr(item,"detected_question_count",0),"collections":item.collections}
@app.get("/api/customers/{cid}/questionnaires")
def questionnaires(cid:int,db:Session=Depends(get_db)):
    customer_or_404(db,cid);items=[]
    for x in db.scalars(select(Questionnaire).where(Questionnaire.customer_id==cid).order_by(Questionnaire.id.desc())):
        total=db.scalar(select(func.count(Question.id)).where(Question.customer_id==cid,Question.questionnaire_id==x.id));answered=db.scalar(select(func.count(Answer.id)).join(Question,Question.id==Answer.question_id).where(Answer.customer_id==cid,Question.questionnaire_id==x.id));manual=db.scalar(select(func.count(Answer.id)).join(Question,Question.id==Answer.question_id).where(Answer.customer_id==cid,Question.questionnaire_id==x.id,Answer.status=="manual_review"));progress=generation_progress(x.id);items.append({"id":x.id,"name":x.name,"collections":x.collections or [],"status":x.status,"created_at":x.created_at,"question_count":total,"answered_count":answered,"manual_review_count":manual,"generation":None if not progress or progress["customer_id"]!=cid else {"state":progress["state"],"completed":progress["completed"],"total":progress["total"],"percent":round(100*progress["completed"]/progress["total"]) if progress["total"] else 0,"failed_count":progress["failed_count"]}})
    return items
@app.get("/api/customers/{cid}/questionnaires/{qid}")
def questionnaire(cid:int,qid:int,debug:bool=False,db:Session=Depends(get_db)):
    item=db.scalar(select(Questionnaire).where(Questionnaire.id==qid,Questionnaire.customer_id==cid).options(selectinload(Questionnaire.questions).selectinload(Question.answer)))
    if not item:raise HTTPException(404,"Not found")
    pool=suggestion_pool(db,cid)
    return {"id":item.id,"name":item.name,"collections":item.collections or [],"status":item.status,"questions":[answer_dict(q,pool=pool,include_debug=debug) for q in sorted(item.questions,key=lambda q:q.ordinal)]}
def progress_dict(progress):
    total=progress["total"];completed=progress["completed"];remaining=max(0,total-completed)
    elapsed=round((progress.get("finished_ts") or time.time())-progress["started_ts"],1)
    eta=round(elapsed/completed*remaining) if completed and remaining and progress["state"]=="running" else None
    return {"state":progress["state"],"stage":progress["stage"],"stage_label":GENERATION_STAGES.get(progress["stage"],progress["stage"]),"total":total,"completed":completed,"remaining":remaining,"percent":round(100*completed/total) if total else 0,"failed_count":progress["failed_count"],"current_ordinal":progress["current_ordinal"],"current_question":progress["current_question"],"current_question_id":progress["current_question_id"],"question_status":progress["question_status"],"question_errors":progress["question_errors"],"summary":progress["summary"],"error":progress["error"],"elapsed_seconds":elapsed,"eta_seconds":eta,"started_at":progress["started_at"],"finished_at":progress["finished_at"]}
class GenerateBody(BaseModel):only_missing:bool=False;include_approved:bool=False;question_ids:list[int]|None=None
@app.post("/api/customers/{cid}/questionnaires/{qid}/generate")
def generate_answers(cid:int,qid:int,body:GenerateBody|None=None,db:Session=Depends(get_db)):
    item=scoped(db,Questionnaire,qid,cid);total=db.scalar(select(func.count(Question.id)).where(Question.questionnaire_id==qid))
    question_ids=body.question_ids if body else None
    if question_ids is not None and not question_ids:raise HTTPException(400,"No questions selected for generation")
    progress=start_generation(item.id,cid,only_missing=bool(body and body.only_missing),include_approved=bool(body and body.include_approved),question_ids=question_ids)
    if progress is None:raise HTTPException(409,"Generation is already running for this questionnaire")
    return {"started":True,"total":total,"only_missing":bool(body and body.only_missing)}
@app.get("/api/customers/{cid}/questionnaires/{qid}/generation")
def generation_status(cid:int,qid:int,db:Session=Depends(get_db)):
    scoped(db,Questionnaire,qid,cid);progress=generation_progress(qid)
    if not progress or progress["customer_id"]!=cid:return {"state":"idle"}
    return progress_dict(progress)
@app.post("/api/customers/{cid}/questionnaires/{qid}/generation/cancel")
def cancel_generation(cid:int,qid:int,db:Session=Depends(get_db)):
    scoped(db,Questionnaire,qid,cid);progress=generation_progress(qid)
    if not progress or progress["customer_id"]!=cid or progress["state"]!="running":raise HTTPException(409,"No generation is running for this questionnaire")
    request_generation_cancel(qid);db.add(AuditLog(customer_id=cid,action="generation_cancelled",entity_type="questionnaire",entity_id=qid,details={"completed":progress["completed"],"total":progress["total"]}));db.commit();return {"cancelling":True}
@app.delete("/api/customers/{cid}/questionnaires/{qid}")
def delete_questionnaire(cid:int,qid:int,db:Session=Depends(get_db)):
    item=scoped(db,Questionnaire,qid,cid);question_ids=list(db.scalars(select(Question.id).where(Question.customer_id==cid,Question.questionnaire_id==qid)))
    answer_ids=list(db.scalars(select(Answer.id).where(Answer.customer_id==cid,Answer.question_id.in_(question_ids)))) if question_ids else []
    if answer_ids:db.execute(delete(AnswerVersion).where(AnswerVersion.customer_id==cid,AnswerVersion.answer_id.in_(answer_ids)))
    if question_ids:db.execute(delete(Answer).where(Answer.customer_id==cid,Answer.question_id.in_(question_ids)))
    db.execute(delete(Question).where(Question.customer_id==cid,Question.questionnaire_id==qid));db.delete(item);db.add(AuditLog(customer_id=cid,action="questionnaire_delete",entity_type="questionnaire",entity_id=qid,details={"name":item.name}));db.commit();Path(item.path).unlink(missing_ok=True);return {"ok":True}
class AnswerUpdate(BaseModel):text:str;status:str
@app.patch("/api/customers/{cid}/answers/{aid}")
def update_answer(cid:int,aid:int,body:AnswerUpdate,db:Session=Depends(get_db)):
    a=scoped(db,Answer,aid,cid);changed=a.text!=body.text;a.text=body.text;a.status=body.status
    if changed:db.add(AuditLog(customer_id=cid,action="answer_edited",entity_type="answer",entity_id=a.id,details={}));a.golden and db.add(AuditLog(customer_id=cid,action="golden_answer_updated",entity_type="answer",entity_id=a.id,details={}))
    if body.status=="approved":a.approved_at=datetime.now(timezone.utc).replace(tzinfo=None);a.reviewer="Reviewer";a.review_duration_seconds=max(0,int((a.approved_at-(a.review_started_at or a.approved_at)).total_seconds()))
    db.add(AuditLog(customer_id=cid,action="answer_approved" if body.status=="approved" else f"answer_{body.status}",entity_type="answer",entity_id=a.id,details={}));db.commit();return {"ok":True}
@app.post("/api/customers/{cid}/answers/{aid}/regenerate")
def regenerate_answer(cid:int,aid:int,db:Session=Depends(get_db)):
    current=scoped(db,Answer,aid,cid);q=scoped(db,Question,current.question_id,cid);cfg=config_for(db,cid);answer=generate_one(db,q,cfg,get_llm(cfg));db.add(AuditLog(customer_id=cid,action="answer_regenerate",entity_type="answer",entity_id=aid,details={}));db.commit();return {"id":answer.id,"text":answer.text,"confidence":answer.confidence,"status":answer.status,"sources":answer.sources}
class GoldenUpdate(BaseModel):golden:bool
@app.patch("/api/customers/{cid}/answers/{aid}/golden")
def set_golden(cid:int,aid:int,body:GoldenUpdate,db:Session=Depends(get_db)):
    answer=scoped(db,Answer,aid,cid);answer.golden=body.golden
    if body.golden and answer.status!="approved":answer.status="approved";answer.approved_at=datetime.now(timezone.utc).replace(tzinfo=None);answer.reviewer="Reviewer"
    db.add(AuditLog(customer_id=cid,action="golden_answer_created" if body.golden else "golden_answer_removed",entity_type="answer",entity_id=aid,details={}));db.commit();return {"ok":True,"golden":answer.golden}
class GlobalAnswerUpdate(BaseModel):global_approved:bool;admin_confirm:bool=False
@app.patch("/api/customers/{cid}/answers/{aid}/global")
def set_global_answer(cid:int,aid:int,body:GlobalAnswerUpdate,db:Session=Depends(get_db)):
    answer=scoped(db,Answer,aid,cid)
    if not body.admin_confirm:raise HTTPException(403,"Explicit administrator confirmation is required")
    if answer.status!="approved":raise HTTPException(400,"Only approved answers can be marked global")
    answer.global_approved=body.global_approved;db.add(AuditLog(customer_id=cid,action="global_answer_approved" if body.global_approved else "global_answer_removed",entity_type="answer",entity_id=aid,details={}));db.commit();return {"ok":True,"global_approved":answer.global_approved}
class ReuseBody(BaseModel):source_answer_id:int
@app.post("/api/customers/{cid}/answers/{aid}/reuse")
def reuse_answer(cid:int,aid:int,body:ReuseBody,db:Session=Depends(get_db)):
    answer=scoped(db,Answer,aid,cid);source=db.scalar(select(Answer).where(Answer.id==body.source_answer_id,Answer.status=="approved"))
    if not source:raise HTTPException(404,"Approved answer not found")
    q=scoped(db,Question,answer.question_id,cid);questionnaire=scoped(db,Questionnaire,q.questionnaire_id,cid);allowed={x["answer_id"]:x for x in approved_suggestions(db,q.text,cid,questionnaire.collections,answer.category,answer.id)};suggestion=allowed.get(source.id)
    if not suggestion:raise HTTPException(409,"Answer does not share a Knowledge Collection with this questionnaire")
    if not suggestion["evidence_current"]:raise HTTPException(409,"Supporting evidence changed or is unavailable; reuse requires review")
    evidence=source.sources
    if source.global_approved:
        current=retrieve(db,q.text,cid,collections=questionnaire.collections)
        if not current or current[0]["score"]<.35:raise HTTPException(409,"Global answer is not supported by current in-scope documentation")
        evidence=[{"document":x["document"],"document_id":x["document_id"],"category":x["category"],"collections":x.get("collections",[]),"page_number":x.get("page_number"),"chunk_id":x["chunk_id"],"score":round(x["score"],4),"text_preview":x["content"][:700]} for x in current]
    answer.text=source.text;answer.sources=evidence;answer.evidence_document_ids=sorted(set(x.get("document_id") for x in evidence if x.get("document_id")));answer.reused_from_answer_id=source.id;answer.status="approved_candidate";answer.classification_reason="Previously approved answer reused; verify before final approval.";db.add(AuditLog(customer_id=cid,action="previous_answer_reused",entity_type="answer",entity_id=aid,details={"source_answer_id":source.id,"golden":source.golden,"global":source.global_approved}));db.commit();return {"ok":True}
class BulkBody(BaseModel):answer_ids:list[int]=[];action:str
@app.post("/api/customers/{cid}/answers/bulk")
def bulk_answers(cid:int,body:BulkBody,db:Session=Depends(get_db)):
    answers=list(db.scalars(select(Answer).where(Answer.customer_id==cid,Answer.id.in_(body.answer_ids)))) if body.answer_ids else []
    if body.action=="approve_high":answers=list(db.scalars(select(Answer).where(Answer.customer_id==cid,Answer.status=="approved_candidate")))
    if body.action=="approve_check":answers=list(db.scalars(select(Answer).where(Answer.customer_id==cid,Answer.status=="needs_review")))
    for answer in answers:
        if body.action in {"approve","approve_high","approve_check"}:answer.status="approved";answer.approved_at=datetime.now(timezone.utc).replace(tzinfo=None);answer.reviewer="Reviewer"
        elif body.action=="manual":answer.status="manual_review";answer.classification_reason="Marked for manual review by reviewer."
        elif body.action=="regenerate":
            q=scoped(db,Question,answer.question_id,cid);cfg=config_for(db,cid);generate_one(db,q,cfg,get_llm(cfg))
        else:raise HTTPException(400,"Unknown bulk action")
        db.add(AuditLog(customer_id=cid,action=f"bulk_{body.action}",entity_type="answer",entity_id=answer.id,details={}))
    db.commit();return {"updated":len(answers)}
@app.get("/api/customers/{cid}/approved-answers/search")
def search_approved_answers(cid:int,q:str="",collections:str="",db:Session=Depends(get_db)):
    customer_or_404(db,cid);selected=set(parse_collections(collections));rows=db.execute(select(Answer,Question,Customer).join(Question,Question.id==Answer.question_id).join(Customer,Customer.id==Answer.customer_id).where(Answer.status=="approved",((Answer.customer_id==cid)|(Answer.global_approved==True)))).all();needle=q.lower()
    return [{"answer_id":a.id,"question":question.text,"answer":a.text,"customer":customer.name,"collections":a.collections or [],"category":a.category,"status":a.status,"golden":a.golden,"global_approved":a.global_approved,"match_badge":"Global Approved Answer" if a.global_approved else "Shared Collection Match","reviewer":a.reviewer,"approved_at":a.approved_at} for a,question,customer in rows if needle in (question.text+" "+a.text+" "+customer.name).lower() and (a.global_approved or not selected or selected.intersection(a.collections or []))][:100]
@app.get("/api/customers/{cid}/answers/{aid}/versions")
def answer_versions(cid:int,aid:int,db:Session=Depends(get_db)):
    scoped(db,Answer,aid,cid);return [{"id":v.id,"version":v.version,"text":v.text,"confidence":v.confidence,"status":v.status,"sources":v.sources,"created_at":v.created_at} for v in db.scalars(select(AnswerVersion).where(AnswerVersion.customer_id==cid,AnswerVersion.answer_id==aid).order_by(AnswerVersion.version.desc()))]
@app.post("/api/customers/{cid}/answers/{aid}/versions/{version}/restore")
def restore_answer_version(cid:int,aid:int,version:int,db:Session=Depends(get_db)):
    answer=scoped(db,Answer,aid,cid);next_version=apply_version_restore(db,answer,version)
    if next_version is None:raise HTTPException(404,"Version not found")
    db.add(AuditLog(customer_id=cid,action="answer_version_restore",entity_type="answer",entity_id=aid,details={"restored_version":version,"new_version":next_version}));db.commit();return {"ok":True,"version":next_version}
def export_questionnaire_or_404(db,cid,qid):
    item=db.scalar(select(Questionnaire).where(Questionnaire.id==qid,Questionnaire.customer_id==cid).options(selectinload(Questionnaire.questions).selectinload(Question.answer)))
    if not item:raise HTTPException(404,"Not found")
    return item,db.get(Customer,cid).name
@app.get("/api/customers/{cid}/questionnaires/{qid}/export")
def export(cid:int,qid:int,db:Session=Depends(get_db)):
    item,customer_name=export_questionnaire_or_404(db,cid,qid)
    return StreamingResponse(export_xlsx(item,False,customer_name),media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":f'attachment; filename="questionnaire-{qid}.xlsx"'})
@app.get("/api/customers/{cid}/questionnaires/{qid}/export-pdf")
def export_pdf_copy(cid:int,qid:int,db:Session=Depends(get_db)):
    item,customer_name=export_questionnaire_or_404(db,cid,qid)
    return StreamingResponse(export_pdf(item,customer_name),media_type="application/pdf",headers={"Content-Disposition":f'attachment; filename="questionnaire-{qid}.pdf"'})
@app.get("/api/customers/{cid}/questionnaires/{qid}/export-internal")
def export_internal(cid:int,qid:int,db:Session=Depends(get_db)):
    item,customer_name=export_questionnaire_or_404(db,cid,qid)
    return StreamingResponse(export_xlsx(item,True,customer_name),media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":f'attachment; filename="questionnaire-{qid}-internal-review.xlsx"'})

PROVIDERS=["mock","openai","azure_openai","anthropic","gemini","openrouter","bedrock","ollama","lm_studio","openai_compatible","enterprise"]
EMBEDDINGS=["mock","openai","azure_openai","openrouter","ollama","sentence_transformers","bge","e5","enterprise","custom"]
def config_dict(c,source="global_default",is_override=False):return {"llm_provider":c.llm_provider,"llm_model":c.llm_model,"embedding_provider":c.embedding_provider,"embedding_model":c.embedding_model,"ai_base_url":c.ai_base_url or "","ai_api_key_configured":bool(c.ai_api_key),"embedding_base_url":c.embedding_base_url or "","embedding_api_key_configured":bool(c.embedding_api_key),"provider_display_name":c.provider_display_name or "","custom_headers_configured":bool(c.custom_headers),"chat_endpoint_path":c.chat_endpoint_path or "/chat/completions","embedding_endpoint_path":c.embedding_endpoint_path or "/embeddings","openai_compatible_mode":c.openai_compatible_mode,"temperature":c.temperature,"top_p":c.top_p,"top_k":c.top_k,"max_tokens":c.max_tokens,"timeout":c.timeout,"retry_count":c.retry_count,"chunk_size":c.chunk_size,"chunk_overlap":c.chunk_overlap,"prompt_instructions":c.prompt_instructions,"settings_source":source,"is_override":is_override,"available_llms":PROVIDERS,"available_embeddings":EMBEDDINGS,"recommended_chat_model":"openai/gpt-oss-20b:free","recommended_embedding_model":"openai/text-embedding-3-small"}
@app.get("/api/customers/{cid}/settings")
def get_settings(cid:int,db:Session=Depends(get_db)):
    customer_or_404(db,cid);row=db.scalar(select(ProviderConfig).where(ProviderConfig.customer_id==cid));effective=config_for(db,cid);return config_dict(effective,effective.settings_source,row.is_override)
@app.get("/api/customers/{cid}/settings/diagnostics")
def settings_diagnostics(cid:int,db:Session=Depends(get_db)):
    customer_or_404(db,cid);cfg=config_for(db,cid);documents=db.scalar(select(func.count(Document.id)).where(Document.customer_id==cid));indexed=db.scalar(select(func.count(Document.id)).where(Document.customer_id==cid,Document.status=="indexed"));failed=db.scalar(select(func.count(Document.id)).where(Document.customer_id==cid,Document.status=="failed"));last_indexed=db.scalar(select(func.max(Document.last_indexed_at)).where(Document.customer_id==cid));ai_test=db.scalar(select(AuditLog).where(AuditLog.customer_id==cid,AuditLog.action=="ai_connection_test").order_by(AuditLog.id.desc()).limit(1));embedding_test=db.scalar(select(AuditLog).where(AuditLog.customer_id==cid,AuditLog.action=="embedding_connection_test").order_by(AuditLog.id.desc()).limit(1))
    mismatch=db.scalar(select(func.count(Document.id)).where(Document.customer_id==cid,((Document.embedding_provider!=cfg.embedding_provider)|(Document.embedding_model!=cfg.embedding_model)|(Document.embedding_dimension<=0)|(Document.indexed_chunk_size!=cfg.chunk_size)|(Document.indexed_chunk_overlap!=cfg.chunk_overlap))))
    indexed_models=[{"provider":p,"model":m,"dimension":dim,"documents":count} for p,m,dim,count in db.execute(select(Document.embedding_provider,Document.embedding_model,Document.embedding_dimension,func.count(Document.id)).where(Document.customer_id==cid,Document.status=="indexed").group_by(Document.embedding_provider,Document.embedding_model,Document.embedding_dimension))]
    return {"documents":documents,"indexed_documents":indexed,"pending_index":documents-indexed-failed,"failed_index":failed,"documents_requiring_reindex":mismatch,"chat_model":cfg.llm_model,"embedding_provider":cfg.embedding_provider,"embedding_model":cfg.embedding_model,"indexed_models":indexed_models,"reindex_required":mismatch>0,"last_reindex":last_indexed,"last_ai_test":None if not ai_test else {"at":ai_test.created_at,"ok":ai_test.details.get("ok"),"latency_ms":ai_test.details.get("latency_ms")},"last_embedding_test":None if not embedding_test else {"at":embedding_test.created_at,"ok":embedding_test.details.get("ok"),"latency_ms":embedding_test.details.get("latency_ms")}}
class ConfigBody(BaseModel):
    llm_provider:str;llm_model:str;embedding_provider:str;embedding_model:str;ai_base_url:str="";ai_api_key:str="";embedding_base_url:str="";embedding_api_key:str="";provider_display_name:str="";custom_headers:str="";chat_endpoint_path:str="/chat/completions";embedding_endpoint_path:str="/embeddings";openai_compatible_mode:bool=True;temperature:float=.1;top_p:float=1;top_k:int=4;max_tokens:int=500;timeout:int=60;retry_count:int=2;chunk_size:int=900;chunk_overlap:int=120;prompt_instructions:str
def apply_config(target,body):
    data=body.model_dump();ai_key=data.pop("ai_api_key");embedding_key=data.pop("embedding_api_key");headers=data.pop("custom_headers")
    for key,value in data.items():setattr(target,key,value or None if key.endswith("base_url") else value)
    if ai_key:target.ai_api_key=ai_key
    if embedding_key:target.embedding_api_key=embedding_key
    if headers:target.custom_headers=headers
def unsaved_config(body,persisted):
    data=body.model_dump();data["ai_api_key"]=data["ai_api_key"] or getattr(persisted,"ai_api_key",None);data["embedding_api_key"]=data["embedding_api_key"] or getattr(persisted,"embedding_api_key",None);data["custom_headers"]=data["custom_headers"] or getattr(persisted,"custom_headers",None);return SimpleNamespace(**data,settings_source=getattr(persisted,"settings_source","global_default"))
def fetch_openrouter_models(cfg,kind):
    if (cfg.llm_provider if kind=="chat" else cfg.embedding_provider)!="openrouter":raise HTTPException(400,f"Select OpenRouter as the {kind} provider first")
    base=(cfg.ai_base_url if kind=="chat" else cfg.embedding_base_url) or "https://openrouter.ai/api/v1";key=cfg.ai_api_key if kind=="chat" else cfg.embedding_api_key
    try:
        response=httpx.get(base.rstrip("/")+"/models",params={"output_modalities":"text" if kind=="chat" else "embeddings"},headers={"Authorization":f"Bearer {key}"} if key else {},timeout=cfg.timeout);response.raise_for_status();items=response.json().get("data",[])
    except Exception as exc:raise HTTPException(502,{"message":f"OpenRouter model fetch failed: {exc}"})
    models=[]
    for item in items:
        architecture=item.get("architecture") or {};outputs=architecture.get("output_modalities") or [];pricing=item.get("pricing") or {};free=item.get("id","").endswith(":free") or all(float(pricing.get(x) or 0)==0 for x in ("prompt","completion","request"))
        models.append({"id":item.get("id"),"name":item.get("name") or item.get("id"),"free":free,"context_length":item.get("context_length"),"provider":(item.get("id") or "").split("/")[0],"supports_chat":"text" in outputs,"supports_embeddings":"embeddings" in outputs,"embedding_dimension":item.get("embedding_dimension") or item.get("dimensions") or (item.get("top_provider") or {}).get("embedding_dimension")})
    return {"kind":kind,"models":models}
@app.put("/api/customers/{cid}/settings")
def save_settings(cid:int,body:ConfigBody,db:Session=Depends(get_db)):
    customer_or_404(db,cid);cfg=db.scalar(select(ProviderConfig).where(ProviderConfig.customer_id==cid));old_effective=config_for(db,cid);old_llm,old_embed,old_embed_model,old_chunk_size,old_chunk_overlap=old_effective.llm_provider,old_effective.embedding_provider,old_effective.embedding_model,old_effective.chunk_size,old_effective.chunk_overlap;cfg.is_override=True;apply_config(cfg,body)
    if old_llm!=cfg.llm_provider:db.add(AuditLog(customer_id=cid,action="ai_provider_change",entity_type="settings",entity_id=cfg.id,details={"from":old_llm,"to":cfg.llm_provider}))
    if old_embed!=cfg.embedding_provider:db.add(AuditLog(customer_id=cid,action="embedding_provider_change",entity_type="settings",entity_id=cfg.id,details={"from":old_embed,"to":cfg.embedding_provider}))
    if old_embed!=cfg.embedding_provider or old_embed_model!=cfg.embedding_model or old_chunk_size!=cfg.chunk_size or old_chunk_overlap!=cfg.chunk_overlap:
        db.execute(Document.__table__.update().where(Document.customer_id==cid).values(status="uploaded",error_message="Embedding settings changed; re-index required"))
    db.commit();return config_dict(cfg,"customer_override",True)
@app.post("/api/customers/{cid}/settings/override")
def enable_customer_override(cid:int,db:Session=Depends(get_db)):
    customer_or_404(db,cid);cfg=db.scalar(select(ProviderConfig).where(ProviderConfig.customer_id==cid));global_cfg=db.get(GlobalProviderConfig,1)
    for key,value in config_values(global_cfg,False).items():setattr(cfg,key,value)
    cfg.ai_api_key=None;cfg.embedding_api_key=None;cfg.custom_headers=None
    cfg.is_override=True;db.add(AuditLog(customer_id=cid,action="settings_override_enabled",entity_type="settings",entity_id=cfg.id,details={}));db.commit();return config_dict(cfg,"customer_override",True)
@app.post("/api/customers/{cid}/settings/reset")
def reset_customer_settings(cid:int,db:Session=Depends(get_db)):
    customer_or_404(db,cid);cfg=db.scalar(select(ProviderConfig).where(ProviderConfig.customer_id==cid));old=config_for(db,cid);cfg.is_override=False;global_cfg=db.get(GlobalProviderConfig,1)
    if old.embedding_provider!=global_cfg.embedding_provider or old.embedding_model!=global_cfg.embedding_model or old.chunk_size!=global_cfg.chunk_size or old.chunk_overlap!=global_cfg.chunk_overlap:db.execute(Document.__table__.update().where(Document.customer_id==cid).values(status="uploaded",error_message="Embedding settings changed; re-index required"))
    db.add(AuditLog(customer_id=cid,action="settings_reset_to_global",entity_type="settings",entity_id=cfg.id,details={}));db.commit();global_cfg.settings_source="global_default";return config_dict(global_cfg,"global_default",False)
@app.get("/api/settings/global")
def get_global_settings(db:Session=Depends(get_db)):return config_dict(db.get(GlobalProviderConfig,1),"global_default",False)
@app.put("/api/settings/global")
def save_global_settings(body:ConfigBody,db:Session=Depends(get_db)):
    cfg=db.get(GlobalProviderConfig,1);old_provider,old_model,old_chunk_size,old_chunk_overlap=cfg.embedding_provider,cfg.embedding_model,cfg.chunk_size,cfg.chunk_overlap;apply_config(cfg,body)
    if old_provider!=cfg.embedding_provider or old_model!=cfg.embedding_model or old_chunk_size!=cfg.chunk_size or old_chunk_overlap!=cfg.chunk_overlap:
        inherited=list(db.scalars(select(ProviderConfig.customer_id).where(ProviderConfig.is_override==False)))
        if inherited:db.execute(Document.__table__.update().where(Document.customer_id.in_(inherited)).values(status="uploaded",error_message="Global embedding settings changed; re-index required"))
    db.add(AuditLog(customer_id=None,action="global_settings_change",entity_type="settings",entity_id=cfg.id,details={}));db.commit();return config_dict(cfg,"global_default",False)
def run_ai_test(cfg,cid,db):
    started=time.perf_counter();base_url=cfg.ai_base_url or "provider default"
    try:
        result=get_llm(cfg).chat([{"role":"user","content":"Reply with OK"}]);latency=round((time.perf_counter()-started)*1000,1);db.add(AuditLog(customer_id=cid,action="ai_connection_test",entity_type="settings",entity_id=None,details={"ok":True,"latency_ms":latency}));db.commit();return {"ok":True,"provider":cfg.llm_provider,"base_url":base_url,"model":cfg.llm_model,"latency_ms":latency,"response":str(result)[:200] or "Connected"}
    except Exception as exc:
        latency=round((time.perf_counter()-started)*1000,1);db.add(AuditLog(customer_id=cid,action="ai_connection_test",entity_type="settings",entity_id=None,details={"ok":False,"latency_ms":latency,"error":str(exc)[:500]}));db.commit();raise HTTPException(502,{"message":str(exc),"provider":cfg.llm_provider,"base_url":base_url,"model":cfg.llm_model,"latency_ms":latency})
def run_embedding_test(cfg,cid,db):
    started=time.perf_counter()
    try:
        vector=get_embeddings(cfg).embed_text("This is a test sentence.");latency=round((time.perf_counter()-started)*1000,1)
        if not vector:raise RuntimeError("Provider returned an empty vector")
        db.add(AuditLog(customer_id=cid,action="embedding_connection_test",entity_type="settings",entity_id=None,details={"ok":True,"latency_ms":latency,"dimension":len(vector)}));db.commit();return {"ok":True,"provider":cfg.embedding_provider,"model":cfg.embedding_model,"vector_dimension":len(vector),"latency_ms":latency}
    except Exception as exc:
        latency=round((time.perf_counter()-started)*1000,1);db.add(AuditLog(customer_id=cid,action="embedding_connection_test",entity_type="settings",entity_id=None,details={"ok":False,"latency_ms":latency,"error":str(exc)[:500]}));db.commit();raise HTTPException(502,{"message":str(exc),"provider":cfg.embedding_provider,"model":cfg.embedding_model,"latency_ms":latency})
@app.post("/api/customers/{cid}/settings/test-ai")
def test_customer_ai(cid:int,body:ConfigBody,db:Session=Depends(get_db)):return run_ai_test(unsaved_config(body,config_for(db,cid)),cid,db)
@app.post("/api/customers/{cid}/settings/test-embedding")
def test_customer_embedding(cid:int,body:ConfigBody,db:Session=Depends(get_db)):return run_embedding_test(unsaved_config(body,config_for(db,cid)),cid,db)
@app.post("/api/settings/global/test-ai")
def test_global_ai(body:ConfigBody,db:Session=Depends(get_db)):return run_ai_test(unsaved_config(body,db.get(GlobalProviderConfig,1)),None,db)
@app.post("/api/settings/global/test-embedding")
def test_global_embedding(body:ConfigBody,db:Session=Depends(get_db)):return run_embedding_test(unsaved_config(body,db.get(GlobalProviderConfig,1)),None,db)
@app.post("/api/settings/global/models/{kind}")
def global_models(kind:str,body:ConfigBody,db:Session=Depends(get_db)):
    if kind not in {"chat","embedding"}:raise HTTPException(404,"Unknown model type")
    return fetch_openrouter_models(unsaved_config(body,db.get(GlobalProviderConfig,1)),kind)
@app.post("/api/customers/{cid}/settings/models/{kind}")
def customer_models(cid:int,kind:str,body:ConfigBody,db:Session=Depends(get_db)):
    if kind not in {"chat","embedding"}:raise HTTPException(404,"Unknown model type")
    return fetch_openrouter_models(unsaved_config(body,config_for(db,cid)),kind)
