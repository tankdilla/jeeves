# tasks.py
from celery import Celery, current_task
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from llm import generate_outreach_draft, generate_followup_draft
from db import SessionLocal
from models import Influencer, Campaign, OutreachThread, Message
from logging_config import get_logger

from celery_app import celery_app

celery = Celery(__name__, broker="redis://localhost:6379/0")

logger = get_logger("jeeves", component="worker")

now = datetime.utcnow()

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

@celery_app.task(name="tasks.generate_initial_drafts")
def generate_initial_drafts(limit: int = 25) -> dict:
    """
    Finds threads that need a first outreach draft, generates the draft,
    stores it as a Message(status='draft'), and updates thread.stage to 'needs_approval'.
    """
    db: Session = SessionLocal()
    created_count = 0
    skipped_count = 0
    task_id = getattr(current_task.request, "id", None)

    # print("Celery DB:", db.bind.url)

    try:
        logger.info(
            "draft_job_started",
            extra={"task_id": task_id, "limit": limit, "db_url": str(db.bind.url)},
        )
        
        # Support both 'new' and 'drafting' in case you have mixed data.
        threads = (
            db.query(OutreachThread)
            .filter(OutreachThread.stage.in_(["new", "drafting"]))
            .limit(limit)
            .all()
        )

        for thread in threads:
            influencer = db.query(Influencer).get(thread.influencer_id)
            campaign = db.query(Campaign).get(thread.campaign_id)
            if not influencer or not campaign:
                skipped += 1
                continue

            # guard: skip if already has outbound message
            existing_outbound = (
                db.query(Message)
                .filter(Message.thread_id == thread.id, Message.direction == "outbound")
                .count()
            )
            if existing_outbound > 0:
                skipped_count += 1
                continue

            rules = campaign.rules or {}
            brand_context = rules.get("brand_context", {})
            offer = rules.get("offer", {"type": campaign.offer_type})

            draft = generate_outreach_draft(
                brand_context=brand_context,
                influencer={
                    "handle": influencer.handle,
                    "display_name": influencer.display_name,
                    "platform": influencer.platform,
                    "bio": influencer.bio,
                    "followers": influencer.followers,
                    "profile_url": influencer.profile_url,
                },
                offer=offer,
            )

            msg = Message(
                thread_id=thread.id,
                channel="email",
                direction="outbound",
                status="draft",
                subject=draft.get("subject"),
                body=draft.get("body") or "",
                created_at=datetime.utcnow(),
            )
            db.add(msg)

            thread.stage = "needs_approval"
            thread.last_contact_at = None
            db.commit()
            created += 1

            logger.info(
                "Draft created",
                extra={
                    "thread_id": str(thread.id),
                    "campaign_id": str(thread.campaign_id),
                    "influencer_id": str(thread.influencer_id),
                },
            )

        logger.info(
            "draft_job_completed",
            extra={
                "task_id": task_id,
                "created_count": created_count,
                "skipped_count": skipped_count,
                "checked_count": len(threads),
            },
        )
        
        return {"created_count": created_count, "skipped_count": skipped_count, "checked": len(threads)}

    finally:
        db.close()

@celery_app.task(name="tasks.generate_followup_drafts")
def generate_followup_drafts(days_since_last_send: int = 3, limit: int = 25) -> dict:
    """
    For threads in stage='waiting':
      - if no inbound replies exist
      - and last outbound sent message is older than N days
    then create a follow-up Message(status='draft') and move thread to 'needs_approval'.
    """
    db = SessionLocal()
    task_id = getattr(current_task.request, "id", None)
    created_count = 0
    skipped_count = 0
    checked_count = 0

    try:
        # cutoff = datetime.utcnow() - timedelta(days=days_since_last_send)

        # logger.info(
        #     "followup_job_started",
        #     extra={
        #         "task_id": task_id,
        #         "days_since_last_send": days_since_last_send,
        #         "limit": limit,
        #         "cutoff": cutoff.isoformat(),
        #     },
        # )

        threads = (
            db.query(OutreachThread)
            .filter(
                OutreachThread.stage == "waiting",
                OutreachThread.next_followup_at.isnot(None),
                OutreachThread.next_followup_at <= now,
            )
            .limit(limit)
            .all()
        )

        for thread in threads:
            checked_count += 1

            # Skip if follow-up not due yet (preferred scheduling driver)
            if thread.next_followup_at and thread.next_followup_at > datetime.utcnow():
                skipped_count += 1
                continue

            # Guard 1: if any inbound message exists, skip (they replied)
            inbound_exists = (
                db.query(Message)
                .filter(
                    Message.thread_id == thread.id,
                    Message.direction == "inbound",
                )
                .count()
            ) > 0
            if inbound_exists:
                skipped_count += 1
                continue

            # Find last sent outbound message
            last_sent = (
                db.query(Message)
                .filter(
                    Message.thread_id == thread.id,
                    Message.direction == "outbound",
                    Message.status == "sent",
                    Message.sent_at.isnot(None),
                )
                .order_by(Message.sent_at.desc())
                .first()
            )

            # If we never actually sent, skip (thread state mismatch)
            if not last_sent:
                skipped_count += 1
                continue

            # # Not old enough yet → skip
            # if last_sent.sent_at and last_sent.sent_at > cutoff:
            #     skipped_count += 1
            #     continue

            # Guard 2: don’t create multiple follow-up drafts if one already exists
            existing_followup_draft = (
                db.query(Message)
                .filter(
                    Message.thread_id == thread.id,
                    Message.direction == "outbound",
                    Message.status == "draft",
                )
                .count()
            ) > 0
            if existing_followup_draft:
                skipped_count += 1
                continue

            influencer = db.query(Influencer).get(thread.influencer_id)
            campaign = db.query(Campaign).get(thread.campaign_id)
            if not influencer or not campaign:
                skipped_count += 1
                continue

            rules = campaign.rules or {}
            brand_context = rules.get("brand_context", {})
            offer = rules.get("offer", {"type": campaign.offer_type})

            draft = generate_followup_draft(
                brand_context=brand_context,
                influencer={
                    "handle": influencer.handle,
                    "display_name": influencer.display_name,
                    "platform": influencer.platform,
                    "bio": influencer.bio,
                    "followers": influencer.followers,
                    "profile_url": influencer.profile_url,
                },
                offer=offer,
            )

            msg = Message(
                thread_id=thread.id,
                channel="email",
                direction="outbound",
                status="draft",
                subject=draft.get("subject"),
                body=draft.get("body") or "",
                created_at=datetime.utcnow(),
            )
            db.add(msg)

            thread.stage = "needs_approval"
            thread.next_followup_at = None
            db.commit()

            created_count += 1
            logger.info(
                "followup_draft_created",
                extra={
                    "task_id": task_id,
                    "thread_id": str(thread.id),
                    "last_sent_at": last_sent.sent_at.isoformat() if last_sent.sent_at else None,
                },
            )

        logger.info(
            "followup_job_completed",
            extra={
                "task_id": task_id,
                "created_count": created_count,
                "skipped_count": skipped_count,
                "checked_count": checked_count,
            },
        )

        return {
            "created": created_count,
            "skipped": skipped_count,
            "checked": checked_count,
        }

    except Exception:
        logger.exception("followup_job_failed", extra={"task_id": task_id})
        raise

    finally:
        db.close()