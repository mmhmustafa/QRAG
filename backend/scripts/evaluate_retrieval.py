"""Retrieval quality evaluation.

Measures hit@1 / hit@3 / hit@5 and MRR for a labeled set of questionnaire-style
questions against the indexed knowledge base, plus a guard set of unsupported
questions whose top score must stay below the RELIABLE threshold.

Run:  python backend/scripts/evaluate_retrieval.py --customer mednova
      --limit 8          retrieval depth to evaluate
      --variants         additionally re-rank with alternative scoring weights
                         (uses one query embedding per question, then ranks offline)
DATABASE_URL selects the database to evaluate against.
"""
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Customer, Document, DocumentChunk
from app.services import retrieve, config_for, relevance_terms, cosine, RELIABLE_SCORE, authority_for
from app.providers import get_embeddings

# question -> acceptable primary source documents (substring match on document name)
EVAL_CASES = [
    ("Describe your corporate governance model.", ["Company_Profile"]),
    ("Where are your support operations located?", ["Company_Profile", "Support_and_SLA"]),
    ("Which business functions are involved in product delivery?", ["Company_Profile"]),
    ("Describe your customer escalation governance.", ["Company_Profile", "Support_and_SLA"]),
    ("Which deployment models are supported?", ["Product_Suite"]),
    ("Describe your product portfolio.", ["Product_Suite"]),
    ("What are the known limitations of the product?", ["Product_Suite"]),
    ("Describe the main features of the platform.", ["Product_Suite"]),
    ("Describe your reference architecture.", ["Architecture"]),
    ("How does data flow through the platform?", ["Architecture"]),
    ("How does the platform scale and ensure availability?", ["Architecture"]),
    ("Which integration interfaces are available?", ["Architecture", "API_and_Integration"]),
    ("Is customer data encrypted at rest?", ["Information_Security"]),
    ("How is data encrypted in transit?", ["Information_Security"]),
    ("Do you support multi-factor authentication?", ["Information_Security", "Approved_Questionnaire"]),
    ("How is identity and access management handled?", ["Information_Security"]),
    ("Describe your logging and monitoring controls.", ["Information_Security"]),
    ("How are code reviews performed?", ["SDLC"]),
    ("Describe your release management process.", ["SDLC"]),
    ("Do developers receive security training?", ["SDLC"]),
    ("How are security incidents classified?", ["Incident_Response"]),
    ("Describe your incident response workflow.", ["Incident_Response"]),
    ("Do you conduct post-incident reviews?", ["Incident_Response"]),
    ("How are customers notified of a data breach?", ["Incident_Response", "Privacy"]),
    ("What are your RPO and RTO targets?", ["Disaster_Recovery"]),
    ("Describe your backup strategy.", ["Disaster_Recovery"]),
    ("How is business continuity maintained?", ["Disaster_Recovery"]),
    ("How often is disaster recovery tested?", ["Disaster_Recovery"]),
    ("How is healthcare data privacy protected?", ["Privacy"]),
    ("How do you handle data subject requests?", ["Privacy"]),
    ("Describe your data retention and deletion policy.", ["Privacy"]),
    ("Are you aligned with ISO 27001?", ["Compliance"]),
    ("Describe your SOC 2 position.", ["Compliance"]),
    ("How do you address HIPAA and GDPR requirements?", ["Compliance", "Privacy"]),
    ("Which support channels are available?", ["Support_and_SLA"]),
    ("What are your severity definitions and response targets?", ["Support_and_SLA"]),
    ("Describe your maintenance windows.", ["Support_and_SLA"]),
    ("Do you support REST APIs?", ["API_and_Integration"]),
    ("How are API requests authenticated?", ["API_and_Integration"]),
    ("Can audit logs be exported to a SIEM?", ["API_and_Integration", "Information_Security"]),
]
UNSUPPORTED = [
    "Provide production IP addresses",
    "List employee phone numbers",
    "Provide unreleased roadmap dates",
    "Provide salary policy",
]

def expected_rank(results, expected):
    for index, x in enumerate(results, start=1):
        if any(token.lower() in x["document"].lower() for token in expected):
            return index
    return None

def metrics(ranks, limit):
    n = len(ranks)
    line = {f"hit@{k}": round(sum(1 for r in ranks if r and r <= k) / n, 3) for k in (1, 3, 5) if k <= limit}
    line["mrr"] = round(sum(1 / r for r in ranks if r) / n, 3)
    line["missed"] = sum(1 for r in ranks if r is None)
    return line

def run_live(db, cid, limit, verbose=False):
    ranks = []
    for question, expected in EVAL_CASES:
        results = retrieve(db, question, cid, limit=limit)
        rank = expected_rank(results, expected)
        ranks.append(rank)
        if verbose or rank is None or rank > 3:
            print(f"  rank={rank or 'MISS':>4}  {question}")
            print(f"        got: {[(x['document'][:38], round(x['score'], 3)) for x in results[:3]]}")
    return ranks

def run_guard(db, cid):
    passed = 0
    for question in UNSUPPORTED:
        results = retrieve(db, question, cid)
        ok = not results or results[0]["score"] < RELIABLE_SCORE
        passed += ok
        if not ok:
            print(f"  GUARD FAIL: {question} -> {[(x['document'][:38], round(x['score'], 3)) for x in results[:2]]}")
    return passed

def run_variants(db, cid, limit):
    """Re-rank with alternative scoring weights using cached query embeddings (no extra indexing)."""
    cfg = config_for(db, cid)
    embedder = get_embeddings(cfg)
    rows = db.execute(select(DocumentChunk, Document).join(Document, Document.id == DocumentChunk.document_id).where(DocumentChunk.customer_id == cid, Document.status == "indexed", Document.enabled == True)).all()
    chunk_data = [{"content": c.content, "vector": c.embedding, "document": d.name, "document_id": d.id, "authority": d.authority or authority_for(d.category), "terms": relevance_terms(c.content)} for c, d in rows]
    # Terms shared by most chunks are boilerplate (headers, company name) and prove nothing about topical relevance.
    from collections import Counter
    doc_freq = Counter(t for x in chunk_data for t in x["terms"])
    common = {t for t, n in doc_freq.items() if n >= 0.6 * len(chunk_data)}
    query_vectors = {q: embedder.embed_text(q) for q, _ in EVAL_CASES}

    def rank_with(weights, drop_common):
        w_lex, w_name = weights
        ranks = []
        for question, expected in EVAL_CASES:
            v = query_vectors[question]
            terms = relevance_terms(question) - (common if drop_common else set())
            ranked = []
            for x in chunk_data:
                chunk_terms = x["terms"] - (common if drop_common else set())
                overlap = len(terms & chunk_terms) / max(1, len(terms))
                name_overlap = len(terms & relevance_terms(x["document"])) / max(1, len(terms))
                score = min(1, cosine(v, x["vector"]) + w_lex * overlap + w_name * name_overlap)
                ranked.append({"document": x["document"], "document_id": x["document_id"], "score": score})
            seen, results = set(), []
            for cand in sorted(ranked, key=lambda r: -r["score"]):
                if cand["document_id"] in seen:
                    continue
                results.append(cand)
                seen.add(cand["document_id"])
                if len(results) >= limit:
                    break
            ranks.append(expected_rank(results, expected))
        return ranks

    variants = [
        ("current  (lex .20, name .15)", (0.20, 0.15), False),
        ("vector only", (0.0, 0.0), False),
        ("drop-common lexical", (0.20, 0.15), True),
        ("heavier name (lex .20, name .30)", (0.20, 0.30), False),
        ("drop-common + heavier name", (0.20, 0.30), True),
        ("heavier lexical (lex .35, name .15)", (0.35, 0.15), True),
    ]
    print("\n--- scoring variants (offline re-rank) ---")
    for label, weights, drop in variants:
        print(f"  {label:<38} {metrics(rank_with(weights, drop), limit)}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--customer", default="mednova")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--variants", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        customer = db.scalar(select(Customer).where(Customer.name.ilike(args.customer)))
        if not customer:
            raise SystemExit(f"Customer not found: {args.customer}")
        print(f"Evaluating retrieval for customer '{customer.name}' ({len(EVAL_CASES)} cases, limit={args.limit})")
        print("--- misses and weak ranks ---")
        ranks = run_live(db, customer.id, args.limit, verbose=args.verbose)
        print("\n--- metrics ---")
        print(f"  {metrics(ranks, args.limit)}")
        guard = run_guard(db, customer.id)
        print(f"  unsupported-question guard: {guard}/{len(UNSUPPORTED)} stayed below {RELIABLE_SCORE}")
        if args.variants:
            run_variants(db, customer.id, args.limit)

if __name__ == "__main__":
    main()
