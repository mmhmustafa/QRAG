# Customer Questionnaire Assistant v0.2 — Handover

## New in this delivery: Knowledge Collections replace Product Scope

Product Scope (product name / version / line / document collection / category filters) is retired in favor of **Knowledge Collections** — simple, flexible, user-defined groupings that match how teams organize documentation.

- Documents are assigned one or more collections at upload (single comma-separated field with one-click chips for existing collections); untagged uploads default to `General`; collections are editable per document
- Questionnaires select one or more collections to search via toggle chips (all collections pre-selected — the common case is zero extra clicks); at least one collection is required
- Retrieval is hard-limited to documents sharing at least one selected collection, on top of unchanged customer isolation and embedding provider/model/dimension isolation
- Approved and Golden answers belong to collections; reuse requires the same customer plus a shared collection (or explicit admin global approval with current-evidence validation, unchanged)
- The Test Retrieval tool, approved-answer library search, questionnaire list, review header, and internal export all operate on collections; the internal export's four scope columns collapse into one Knowledge Collections column
- Automatic migration: existing documents, questionnaires, and answers receive collections derived from their product scope — product name + version become one collection, product line and non-default document collection become additional collections, empty scope becomes `General` — and the retired NOT NULL product-scope columns are dropped so new inserts succeed on migrated databases
- New regression suite: collection-scoped retrieval isolation (disjoint collections never cross, multi-collection selection unions, shared collections reach shared documents), General-default behavior, and collection-scoped answer reuse
- Upload and questionnaire forms drop from five scope fields to one collections control — fewer clicks, less configuration, same safety

## Previous delivery: reviewer-first answer policy (generate-then-verify)

The review workflow and contradiction detection were redesigned to optimize reviewer productivity without reducing trust. One authoritative document is now enough for a confident answer, and Manual Review is reserved for genuine problems.

- Generate-then-verify pipeline: the best answer is always drafted first from the most authoritative relevant evidence, then verified against peer evidence; a confirmed contradiction downgrades the status but never erases the draft — the reviewer edits instead of authoring from scratch
- Document authority tiers derived from category (Product 3, Security 4, Previous Questionnaires 5, Company 6, Support/Operations 7, Compliance/Legal 8, Marketing 9; Golden/Approved Answers reserved at 1–2), stored per document, backfilled by migration, and used in retrieval ranking and evidence arbitration
- Primary/Supporting/Complementary/Conflicting/Superseded evidence classification anchored to a primary source (most authoritative document within the top relevance band) instead of pairwise chunk comparison; chunks below the relevance threshold can neither veto nor dilute an answer
- Subject-scoped contradiction detection: a negation only counts against the clause it negates, requires a specific (non-generic) shared subject, and — at answer verification — must concern the question's own subject; mutually exclusive claims (cloud-only vs on-prem-only) are always detected
- Contradictions from sources more than one authority tier below the primary are recorded as superseded rather than routed to Manual Review
- Confidence recalibrated: 0.55·retrieval quality + 0.30·evidence consistency + 0.15·authority + supporting-evidence bonus; the former two-document minimum for approval candidates is removed, and supporting documents raise confidence instead of creating doubt
- Golden Answer reuse is validated against current documentation on every reuse; a matching Golden Answer with changed source documents surfaces as Check Suggested Answer with an explanation instead of silent reuse or silent skipping
- Manual Review is reserved for: no relevant documentation, a genuine peer-authority contradiction about the question's subject (draft retained, both documents named), or evidence that cannot support a grounded answer
- Provenance-oriented review language ("Answered from Product Guide, supported by 2 additional sources") replaces warning-oriented language; contradiction warnings appear only for verified conflicts
- Business-friendly statuses — Ready to Approve / Check Suggested Answer / Needs Manual Input — with confidence shown as High/Medium/Low buckets; raw percentages and quality metrics moved behind a collapsed Confidence Details expander
- Review workspace triage bar with per-status counts and one-click Approve All Ready; keyboard-driven Focus Review Mode (A approve-and-advance, E edit, arrow keys navigate) that steps through only the answers still needing attention
- Evidence panel labels every source with its role (Primary/Supporting/Complementary/Conflicting/Superseded); LLM-confirmed contradiction checking for real providers with a deterministic lexical screen for the mock provider
- New regression suites: evidence-consistency unit tests (benign negations, authority supersede, single-document sufficiency, side-topic contradiction immunity) and end-to-end generation-policy tests (draft retention on conflict, supporting-evidence confidence lift, superseded low-authority contradictions)

## Delivered

A customer-isolated, mock-first application for drafting customer questionnaire answers from approved internal documents.

- Customer create, edit, archive, delete, and active-customer switching
- Hard customer scoping across knowledge, chunks, questionnaires, answers, settings, retrieval, files, and audit activity
- Legacy MVP migration into a `Default Organization`
- Document categories, metadata, rename, replace, download, re-index, and complete deletion
- Multi-file picker and drag-and-drop knowledge uploads with preview metadata, removal, per-file progress, independent failures, and aggregate results
- PDF, DOCX, XLSX, CSV, and TXT validation with a 25 MB per-file limit
- Collision-safe physical filenames so duplicate uploaded names cannot overwrite existing documents
- Polished onboarding, searchable management screens, workflow-aware empty/loading states, and responsive SaaS-style layouts
- Two-phase questionnaire workflow: extract questions first, then generate on explicit user action
- Questionnaire progress metrics, delete/generate/export actions, and per-answer regeneration
- Approval-focused review cards with editable answers, citations, confidence meters, statuses, and decisions
- Structured AI, embedding, retrieval, prompt, and export settings with provider connection testing
- Real OpenRouter `/embeddings` integration with upstream error details and vector dimension/latency testing
- Verified indexing state machine, per-document RAG diagnostics, customer-wide re-index, and raw retrieval inspection
- Semantic vector retrieval without the former lexical false-negative gate; dimension mismatches are safely excluded
- OpenRouter chat/embedding model catalog dropdowns with metadata and recommended defaults
- Strict retrieval isolation by active embedding provider, exact model ID, and stored vector dimension
- Discovery-free local/custom enterprise configuration with manual model and endpoint names, optional tokens, write-only custom headers, and OpenAI-compatible mode
- Reviewer productivity workflow: evidence-aware answer classification with reasons, conservative contradiction detection, duplicate/similar question suggestions, approved-answer reuse, editable Golden Answers, bulk review controls, and cross-customer approved-answer search
- Reviewer metrics and expanded internal exports with reviewer, approval date, version, confidence, evidence, and Golden/reuse provenance
- Audit coverage for generated, edited, approved, reused, Golden-created, Golden-updated, and Golden-removed answers
- Strict answer-scope safety: customer/product/version/module/collection/category metadata, scoped document retrieval, scoped Golden and approved-answer matching, explicit admin-only global designation, stale-evidence rejection, and current-document validation for global reuse
- Global frontend error normalization with readable FastAPI validation messages and defensive JSX formatting for unexpected API shapes
- Active-customer Test Retrieval scope discovery with automatic single-product selection, multi-product selector, empty-scope guard, persisted selection, and backend customer/scope validation
- Frontend/backend route consistency audit, documents-based Knowledge scope discovery, friendly contextual 404 errors, development API request logging, and caught Knowledge/Settings/Viewer loaders
- Calibrated evidence relationship classifier (duplicate/complementary/conflicting/unrelated), complementary answer synthesis, duplicate confidence boost, genuine-claim-only contradiction routing, and separate retrieval/consistency/answer quality metrics
- RAG logs for extraction, chunking, embeddings, vector persistence, retrieval results, and LLM call/skip decisions
- Strict active-customer embedding selection with no implicit mock fallback, effective indexing configuration banner, and provider/model-stamped re-index results
- Singleton Global Default Settings with dynamic customer inheritance, explicit override/reset lifecycle, separate AI and embedding endpoints/keys, and write-only secret indicators
- New customers work immediately from populated global defaults; only explicit overrides require customer-specific secrets
- Effective settings source is recorded with indexed documents and displayed as Global Default or Customer Override
- Enterprise Settings polish: unsaved-value AI/embedding tests, write-only key updates, effective configuration health, inline validation, provider help, dirty/saved states, factual re-index detection, and customer diagnostics summary
- Enterprise questionnaire review: clean customer answers, internal evidence panels, semantic confidence badges, clickable sources, integrated document preview, per-answer regeneration, version history/restore, manual-review routing, admin RAG diagnostics, retrieval caching, and clean versus internal exports
- MedNova-calibrated retrieval quality: document-diverse hybrid ranking, customer-answer sanitization, 0.35 reliability boundary, reproducible evaluation script, 5/5 known-source passes, 4/4 unsupported manual-review passes, and structural clean/internal export tests
- Per-customer live AI, embedding, retrieval, and prompt settings without restart
- OpenRouter, Ollama, LM Studio, OpenAI-compatible, enterprise, cloud, and mock adapter surfaces

- Next.js dashboard, knowledge upload, questionnaire upload, review, settings, and export screens
- FastAPI backend with document parsing, chunking, retrieval, grounded answer generation, and audit events
- PDF, DOCX, XLSX, CSV, and TXT support
- Provider-independent LLM and embedding interfaces
- Adapter seams for OpenAI, Azure OpenAI, Anthropic Claude, Gemini, AWS Bedrock, local LLMs, and mock providers
- PostgreSQL/pgvector-ready schema with a zero-setup SQLite development default
- Confidence scores and source document/chunk references
- Automatic `Manual review required` routing when no reliable evidence exists
- Answer editing, approval, rejection, draft saving, and Excel export
- Sample knowledge and questionnaire files
- Docker Compose, environment template, tests, and production-hardening checklist

## Verification completed

- Backend unit, workflow, evidence-consistency, generation-policy, collection-isolation, scope-safety, and tenant-isolation tests: 25 passed
- Frontend optimized production build: passed
- End-to-end API verification against a seeded corpus: documents uploaded into distinct collections; a questionnaire scoped to Product Alpha answered from the Alpha document while a contradictory Product Beta document remained invisible (collection isolation prevents false conflicts); legacy product-scope databases migrated in place (verified on two databases, including one first migrated by an older build) and regenerated correctly under their migrated collections
- Previous-delivery browser verification of the review workflow (triage bar, Approve All Ready, Focus Review Mode, draft retention on conflict) remains valid; this delivery's UI changes are compiled and served by the running dev stack

## Run locally

From the project root:

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

Open `http://localhost:3000`. Upload `samples/company-knowledge.txt`, then `samples/customer-questionnaire.csv`.

## Important implementation note

Mock providers are fully operational without API keys. Named real-provider adapter classes and configuration surfaces are present, but each organization must connect its approved provider SDK and credentials in `backend/app/providers.py`. Secrets remain server-side.

See `README.md` for full architecture, configuration, testing, PostgreSQL, and production-hardening guidance.
