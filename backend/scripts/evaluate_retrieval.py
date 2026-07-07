"""Run: python backend/scripts/evaluate_retrieval.py --customer mednova"""
import argparse
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Customer
from app.services import retrieve

CASES=[
 ("Where are your support operations located?",["Company_Profile","Support_and_SLA"]),
 ("Do you support MFA?",["Information_Security","Approved_Questionnaire"]),
 ("What is your RPO and RTO?",["Disaster_Recovery"]),
 ("Which deployment models are supported?",["Product_Suite"]),
 ("Do you support REST APIs?",["API_and_Integration"]),
]
UNSUPPORTED=["Provide production IP addresses","List employee phone numbers","Provide unreleased roadmap dates","Provide salary policy"]
def main():
 parser=argparse.ArgumentParser();parser.add_argument("--customer",default="mednova");args=parser.parse_args()
 with SessionLocal() as db:
  customer=db.scalar(select(Customer).where(Customer.name.ilike(args.customer)))
  if not customer:raise SystemExit(f"Customer not found: {args.customer}")
  passed=0
  for question,expected in CASES:
   results=retrieve(db,question,customer.id);names=[x["document"] for x in results];ok=all(any(token.lower() in name.lower() for name in names) for token in expected);passed+=ok
   print(f"\nQuestion: {question}\nExpected: {expected}\nRetrieved: {names}\nScores: {[round(x['score'],4) for x in results]}\n{'PASS' if ok else 'FAIL'}")
  unsupported_passed=0;print("\nUnsupported-question retrieval (top score must remain below 0.35):")
  for question in UNSUPPORTED:
   results=retrieve(db,question,customer.id);ok=not results or results[0]["score"]<.35;unsupported_passed+=ok;print(f"- {question}: {[(x['document'],round(x['score'],4)) for x in results]} — {'PASS' if ok else 'FAIL'}")
  print(f"\nKnown retrieval: {passed}/{len(CASES)} passed\nUnsupported manual-review checks: {unsupported_passed}/{len(UNSUPPORTED)} passed")
  if passed!=len(CASES) or unsupported_passed!=len(UNSUPPORTED):raise SystemExit(1)
if __name__=="__main__":main()
