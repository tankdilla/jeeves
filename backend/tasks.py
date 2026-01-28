# tasks.py
from celery import Celery
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from llm import generate_outreach_draft
from db import SessionLocal
from models import Influencer, Campaign, OutreachThread, Message

celery = Celery(__name__, broker="redis://localhost:6379/0")

def compute_score(inf: Influencer, rules: dict) -> tuple[float, float, float]:
    # Simple transparent scoring MVP
    niche = 0.0
    if inf.bio and rules.get("keywords"):
        bio = inf.bio.lower()
        niche = sum(1 for k in rules["keywords"] if k.lower() in bio) / max(1, len(rules["keywords"]))
        niche *= 40

    perf = 0.0
    if inf.engagement_rate:
        # normalize around typical micro-influencer ranges
        er = float(inf.engagement_rate)
        perf = min(35.0, max(0.0, (er / 0.08) * 35.0))  # 8% => full points

    risk = 5.0 if not inf.email else 0.0  # light penalty if no email

    overall = niche + perf - risk
    return niche, risk, overall

@celery.task
def score_and_draft_for_campaign(campaign_id: str):
    db: Session = SessionLocal()
    campaign = db.query(Campaign).get(campaign_id)
    rules = campaign.rules or {}

    brand_context = rules.get("brand_context", {})
    offer = rules.get("offer", {})

    influencers = db.query(Influencer).filter(Influencer.status == "new").limit(50).all()

    for inf in influencers:
        niche_score, risk_score, overall = compute_score(inf, rules)
        inf.brand_fit_score = niche_score
        inf.risk_score = risk_score
        inf.overall_score = overall
        inf.status = "queued"

        thread = OutreachThread(campaign_id=campaign.id, influencer_id=inf.id, stage="drafting")
        db.add(thread)
        db.flush()

        draft = generate_outreach_draft(
            brand_context=brand_context,
            influencer={
                "handle": inf.handle,
                "display_name": inf.display_name,
                "platform": inf.platform,
                "bio": inf.bio,
                "followers": inf.followers,
                "profile_url": inf.profile_url
            },
            offer=offer
        )

        msg = Message(
            thread_id=thread.id,
            channel="email",
            direction="outbound",
            status="draft",
            subject=draft["subject"],
            body=draft["body"]
        )
        db.add(msg)

        thread.stage = "needs_approval"
        thread.next_followup_at = datetime.utcnow() + timedelta(days=4)

    db.commit()
    db.close()
