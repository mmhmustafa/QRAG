from app.services import analyze_evidence, claims_conflict, verify_answer
from app.providers import MockLLMProvider

def item(document_id,name,content,authority=6,score=.6,chunk_id=None):
    return {"document_id":document_id,"document":name,"content":content,"authority":authority,"score":score,"chunk_id":chunk_id or document_id}

def test_complementary_evidence_is_merged_not_conflicted():
    context=[item(1,"Company Profile","Support operations are located in India and the USA.",authority=6),item(2,"Support Handbook","Customer support is available 24x7.",authority=7)]
    analysis=analyze_evidence(context)
    assert analysis["counts"]["complementary"]==1
    assert analysis["conflicting_documents"]==[]
    assert analysis["primary"]["document"]=="Company Profile"
    answer=MockLLMProvider().generate_answer("Where is support located?",context)
    assert "India" in answer and "24x7" in answer

def test_supporting_evidence_increases_consistency_without_conflict():
    context=[item(1,"Policy A","Multi-factor authentication is supported for administrator access."),item(2,"Policy B","Multi-factor authentication is supported for administrator access.")]
    analysis=analyze_evidence(context)
    assert analysis["counts"]["supporting"]==1 and analysis["consistency"]>=.94
    assert not analysis["conflicting_documents"]

def test_only_mutually_incompatible_claims_conflict():
    mfa=analyze_evidence([item(1,"Current Policy","The platform supports MFA authentication.",authority=4),item(2,"Legacy Policy","The platform does not support MFA authentication.",authority=4)])
    deployment=analyze_evidence([item(1,"Cloud Guide","The product is cloud-only.",authority=3),item(2,"Deployment Guide","The product is on-prem only.",authority=3)])
    assert mfa["counts"]["conflicting"]==1 and mfa["consistency"]<=.35
    assert deployment["counts"]["conflicting"]==1

def test_benign_negation_does_not_create_conflict():
    # Enterprise documents are full of negations that are not contradictions of the answer's subject.
    context=[item(1,"Company Profile","Support operations are located in India and the USA.",authority=6),item(2,"Compliance Guide","Support staff do not have access to production customer data.",authority=8)]
    analysis=analyze_evidence(context)
    assert analysis["conflicting_documents"]==[]
    pricing=[item(1,"Support Handbook","Premium support is included in the enterprise plan.",authority=7),item(2,"Pricing FAQ","There is no additional charge for standard support.",authority=7)]
    assert analyze_evidence(pricing)["conflicting_documents"]==[]

def test_higher_authority_supersedes_instead_of_conflicting():
    context=[item(1,"Product Guide","The platform supports MFA authentication for all users.",authority=3),item(2,"Old Marketing Sheet","The platform does not support MFA authentication.",authority=9)]
    analysis=analyze_evidence(context)
    assert analysis["conflicting_documents"]==[]
    assert analysis["superseded_documents"]==["Old Marketing Sheet"]
    assert analysis["primary"]["document"]=="Product Guide"
    assert analysis["consistency"]>=.9

def test_single_authoritative_document_is_enough():
    analysis=analyze_evidence([item(1,"Product Guide","Data is encrypted at rest using AES-256.",authority=3,score=.8)])
    assert analysis["primary"]["document"]=="Product Guide"
    assert analysis["consistency"]>=.9
    assert analysis["conflicting_documents"]==[]

def test_irrelevant_chunks_cannot_veto_or_dilute():
    context=[item(1,"Security Guide","Data is encrypted at rest using AES-256.",authority=4,score=.8),item(2,"Legal Notice","This agreement does not constitute a warranty of encryption performance.",authority=8,score=.1)]
    analysis=analyze_evidence(context)
    assert analysis["relevant_count"]==1
    assert analysis["conflicting_documents"]==[]
    assert analysis["consistency"]>=.9

def test_answer_verification_flags_peer_contradiction_but_not_low_tiers():
    question="Do you support MFA for administrators?"
    primary=item(1,"Security Guide","MFA is supported for administrator access.",authority=4,score=.8)
    peer=item(2,"Legacy Security Note","MFA authentication is not supported by the platform.",authority=4,score=.7)
    marketing=item(3,"Marketing Sheet","MFA authentication is not supported by the platform.",authority=9,score=.7)
    assert verify_answer("MFA is supported for administrator access.",question,[primary,peer],primary)==["Legacy Security Note"]
    assert verify_answer("MFA is supported for administrator access.",question,[primary,marketing],primary)==[]

def test_answer_verification_ignores_contradictions_about_side_topics():
    # A disagreement about MFA must never block an answer about SSO.
    question="Do you support single sign-on SSO for enterprise users?"
    primary=item(1,"SSO Guide","Single sign-on SSO is supported via SAML for enterprise users.",authority=3,score=.9)
    side=item(2,"Legacy Note","The platform does not support MFA authentication for administrator users.",authority=4,score=.6)
    answer="Single sign-on SSO is supported via SAML. The platform does not support MFA authentication."
    assert verify_answer(answer,question,[primary,side],primary)==[]

def test_claims_conflict_requires_shared_negated_subject():
    assert claims_conflict("The platform supports MFA authentication.","The platform does not support MFA authentication.")
    assert not claims_conflict("Support operations are located in India.","Support staff do not have access to production data.")
    assert claims_conflict("The product is cloud-only.","The product is on-prem only.")

class ConflictJudgeLLM(MockLLMProvider):
    def __init__(self,verdict):self.verdict=verdict
    def chat(self,messages,stream=False):
        if "Reply with exactly YES or NO" in messages[0].get("content",""):return self.verdict
        return super().chat(messages,stream)

def test_llm_vetoes_false_lexical_conflict():
    # Lexical screen suspects a conflict; the model precision filter clears it, so consistency is not punished.
    context=[item(1,"Current Policy","The platform supports MFA authentication.",authority=4),item(2,"Legacy Policy","The platform does not support MFA authentication.",authority=4)]
    cleared=analyze_evidence(context,llm=ConflictJudgeLLM("NO"),use_llm=True)
    assert cleared["counts"]["conflicting"]==0
    assert cleared["conflicting_documents"]==[]
    assert cleared["consistency"]>=.9
    confirmed=analyze_evidence(context,llm=ConflictJudgeLLM("YES"),use_llm=True)
    assert confirmed["counts"]["conflicting"]==1 and confirmed["consistency"]<=.35

def test_lexical_behavior_unchanged_without_llm():
    context=[item(1,"Current Policy","The platform supports MFA authentication.",authority=4),item(2,"Legacy Policy","The platform does not support MFA authentication.",authority=4)]
    assert analyze_evidence(context)["counts"]["conflicting"]==1
