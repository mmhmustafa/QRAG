# Customer Questionnaire Assistant

A multi-customer, mock-first, provider-independent RAG application that drafts customer questionnaire answers only from approved internal documents. Every answer includes confidence and source references; missing evidence becomes **Manual Review Required**.

## Architecture

- `frontend/`: Next.js App Router dashboard, uploads, review/approval, settings, and export
- `backend/`: FastAPI API, SQLAlchemy persistence, parsers, retrieval, provider interfaces, audit logging
- `database/schema.sql`: PostgreSQL schema baseline (Docker image includes pgvector)
- `data/uploads/`: local MVP file storage
- `samples/`: ready-to-upload knowledge and questionnaire files

Every operational record carries a `customer_id`, all retrieval and mutations are customer-scoped, and local files are stored below a customer-specific directory. Existing SQLite MVP databases are automatically assigned to a `Default Organization` on first v0.2 startup.

The default mock embedding hashes tokens into a deterministic 128-dimensional vector, allowing local cosine search without an external model. The mock LLM returns only retrieved context and refuses questions with no reliable evidence. Common interfaces isolate OpenAI, Azure OpenAI, Claude, Gemini, OpenRouter, Bedrock, Ollama, LM Studio, OpenAI-compatible and enterprise endpoints, plus cloud/local embedding providers. OpenAI-compatible endpoints use `/chat/completions` and `/embeddings`; provider-specific gateways can be added with one adapter class.

## Quick start (no API key)

Requirements: Python 3.11+ and Node.js 20+.

```powershell
Copy-Item .env.example .env
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
uvicorn app.main:app --app-dir backend --reload
```

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`, create or select a customer, upload `samples/company-knowledge.txt`, then upload `samples/customer-questionnaire.csv`. The app extracts and displays the question count without generating answers. Choose **Generate Answers** when the knowledge base and customer AI settings are ready, then review and export the grounded drafts. API docs are at `http://localhost:8000/docs`.

SQLite is the zero-setup default. For PostgreSQL, run `docker compose up -d postgres`, then set:

```env
DATABASE_URL=postgresql+psycopg://questionnaire:questionnaire@localhost:5432/questionnaire
```

## Provider configuration

Provider settings are saved per customer and take effect immediately without an application restart. API keys are accepted by the backend but never returned to the browser. The common interfaces expose `generate_answer`, `summarize`, `extract_questions`, `classify_question`, `chat`, `embed_text`, and `embed_batch`. OpenRouter defaults to `https://openrouter.ai/api/v1`; Ollama, LM Studio, private OpenAI-compatible services, and custom enterprise base URLs can remain entirely on-premises.

After changing an embedding provider or model, documents are marked as requiring re-indexing. Use **Test Embedding Connection** first, then **Re-index all documents** on the Knowledge Base page. Document diagnostics prove extracted text, chunk, embedding, and stored-vector counts. **Test Retrieval** displays raw top-K chunks and scores before the LLM is called.

The Knowledge Base page also displays the active customer and its effective embedding provider/model/base URL. This prevents diagnostics from one customer workspace being mistaken for another. Indexing refuses missing or unknown provider configuration; mock embeddings are used only when the saved provider is explicitly `mock`.

## Global defaults and customer overrides

The Settings page has separate **Global Default Settings** and **Customer Settings** views. New customers inherit the global AI, embedding, retrieval, and prompt configuration automatically. Select **Override for this Customer** only when a customer needs different providers or models; customer API keys remain separate and write-only. **Reset to Global Default** removes the override and immediately restores dynamic inheritance. Changes to an effective embedding provider or model mark affected documents for re-indexing.

OpenRouter chat and embedding models are managed separately. Use **Fetch Chat Models** or **Fetch Embedding Models** to load the live OpenRouter catalog and review model ID, display name, free/paid status, provider, context length, capability, and published embedding dimension. The recommended defaults are `openai/gpt-oss-20b:free` for chat and `openai/text-embedding-3-small` for embeddings. Changing only the chat model does not invalidate an index; changing the embedding model does. Retrieval filters indexed vectors by the active embedding provider, exact model ID, and vector dimension.

Local and custom enterprise providers never require model discovery. Configure a display name, chat and embedding base URLs, optional API tokens, write-only JSON custom headers, manual model names, endpoint paths, and whether the service uses OpenAI-compatible response envelopes. With compatibility disabled, common `response`/`output`/`text` chat responses and `embeddings`/`vectors` embedding responses are accepted.

Connection tests operate on the values currently entered in the form, without requiring a save. Existing configured secrets are reused server-side when the API key input remains blank. The Effective Configuration card, inline validation, provider URL examples, unsaved/saved indicators, re-index warning, and Diagnostics Summary make provider and indexing health visible from one page.

## Enterprise questionnaire review

Generated answer text is customer-ready and never intentionally includes internal source names or chunk references. Evidence remains in a separate internal panel with document metadata, similarity, page number when available, and links into the integrated source viewer. PDF sources open at the retrieved page; DOCX, TXT, CSV, and XLSX sources use searchable extracted-text previews.

Each regeneration affects only the selected answer and creates a version that can be compared and restored. Low-confidence retrieval automatically enters manual review. The default export includes only questions and final approved answers; **Export with Internal Evidence** produces a separate reviewer copy. Administrator retrieval prompts, chunks, scores, responses, timings, and cache status are hidden from normal review and can be enabled by an authorized operator with `?debug=1` on the review URL.

### Reviewer productivity

Generated answers are classified as **Ready to Approve**, **Check Suggested Answer**, or **Needs Manual Input**, with a plain-language provenance reason ("Answered from Product Guide, supported by 2 additional sources"). Answer generation is generate-then-verify: the best answer is always drafted from the most authoritative relevant evidence first, then checked against peer evidence for genuine contradictions about the question's subject. A verified contradiction routes the answer to manual review with the draft retained and both documents named, so the reviewer edits instead of authoring from scratch. One authoritative document is enough for a high-confidence answer; additional agreeing documents raise confidence rather than create doubt. Approved answers form an internal scope-isolated library; similar in-scope questions surface previous answers, with Golden Answers ranked first. Reviewers can reuse, edit, ignore, approve, or mark trusted answers as Golden, and can bulk approve candidates, route selected answers to manual review, or regenerate selections. The dashboard tracks approvals, reuse, golden answers, confidence, review time, and estimated time saved.

### Knowledge Collections

Documents are organized into **Knowledge Collections** — user-defined groupings that match how enterprise teams actually organize documentation ("Company", "Product Alpha", "Security", "Cloud Deployment", "Regional Documentation"). A document belongs to one or more collections, assigned at upload (comma-separated, with one-click chips for existing collections) and editable later; documents uploaded without collections default to `General`. A questionnaire selects one or more collections to search, and retrieval is hard-limited to documents sharing at least one selected collection — in addition to customer isolation and embedding provider/model/dimension isolation, which are unchanged.

Approved and Golden answers are deny-by-default reusable: they must belong to the active customer, share at least one Knowledge Collection with the questionnaire, and have a compatible category. Golden status does not broaden scope. Cross-customer reuse is possible only after the explicit **Admin: Approve Global Answer** confirmation, and even then current in-scope documentation must retrieve reliable supporting evidence. Deleted, disabled, replaced, re-indexed, stale, or missing evidence prevents automatic reuse.

Databases created under the former product-scope model migrate automatically on startup: each document, questionnaire, and answer receives collections built from its product name plus version (as one collection), product line, and any non-default document collection; records with no scope receive `General`. The retired product-scope columns are then dropped.

Customer exports contain only question and final approved answer. Internal exports add customer scope, Knowledge Collections, category, evidence, confidence, reviewer, approval date, version, and Golden/reuse provenance. Generated, edited, approved, reused, global-approval, and Golden lifecycle events are retained in the audit log.

Frontend API failures are normalized by `frontend/lib/api.ts` through the shared `formatError` utility. FastAPI validation arrays render as readable `Validation error` lines with field locations; strings, arrays, nested `detail`/`message`/`error` objects, unknown objects, and unexpected payloads are converted to safe text before entering React.

The **Test Retrieval** tool lists the active customer's Knowledge Collections as toggle chips (all selected by default, last selection retained per customer) and searches only the selected collections. With no collections, the tool shows guidance and never submits an invalid request. Requests carry a matching `customer_id`, the selected collections, and the question; the backend rejects customer/path mismatches and requires at least one collection.

Frontend calls and FastAPI routes are audited as a matching set. The centralized API client reports 404s as `API endpoint not found: <path>`, logs method, URL, status, and error body in development, and page loaders catch failures before they can become unhandled promise rejections.

Documents carry an authority tier derived from their category (Product 3, Security 4, Previous Questionnaires 5, Company 6, Support/Operations 7, Compliance/Legal 8; Golden and Approved Answers occupy tiers 1-2). Retrieved evidence is ranked around a primary source — the most authoritative document near the top retrieval score — and every other relevant chunk is classified as supporting, complementary, conflicting, or superseded relative to it. Chunks below the relevance threshold can neither veto nor dilute an answer. Opposite claims must deny the same specific factual subject (generic questionnaire words such as "support" or "user" never establish a contradiction alone), or state mutually exclusive conditions such as cloud-only versus on-prem-only. Contradictions from sources more than one tier below the primary are recorded as superseded instead of triggering review. Supporting evidence increases consistency and confidence, and the review screen displays Retrieval Quality, Evidence Consistency, and Answer Confidence separately behind an expandable details section. The review workspace opens with a triage bar (Ready to Approve / Check Suggested Answer / Needs Manual Input counts plus one-click **Approve All Ready**) and a keyboard-driven **Focus Review Mode** (`A` approve, `E` edit, arrow keys to navigate) for clearing the remaining queue one question at a time.

### Retrieval quality evaluation

Run `python backend/scripts/evaluate_retrieval.py --customer mednova` with `PYTHONPATH=backend`. The script prints expected and retrieved documents, similarity/relevance scores, and pass/fail results for known and unsupported questions. Ranking combines semantic similarity with bounded terminology/title relevance and returns document-diverse evidence. The current MedNova acceptance run passes 5/5 known-source cases and 4/4 unsupported manual-review cases.

The provider prompt/implementation must preserve these invariants: use retrieved context only, never invent facts, return `Manual review required` when evidence is insufficient, cite source documents, stay concise, and prefer approved responses.

## Tests and production build

```powershell
pip install pytest
pytest backend\tests -q
cd frontend
npm run build
```

## Security and traceability

Uploads and answer decisions create audit records. Answers retain source document/chunk IDs and relevance scores. The MVP stores uploads locally and uses environment variables for secrets. Authentication is intentionally deferred; do not expose this build directly to the internet.

## Production hardening TODO

- Enterprise SSO and role-based access control
- Encryption at rest and managed secret storage
- Multi-stage approval workflow and document versioning
- Tenant isolation and multi-tenant authorization tests
- Native pgvector/Qdrant indexing for large corpora
- SharePoint, Confluence, and Google Drive connectors
- Tamper-resistant audit export and retention policies
- Malware scanning, MIME validation, quotas, and async ingestion workers
- On-prem deployment packaging and observability
- Full real-provider adapters, rate limiting, retries, and evaluation suites
- Preserve formatting when exporting into original Word/Excel questionnaires
