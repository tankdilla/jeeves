# tasks.py
import os
from celery import Celery, current_task
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime, timedelta
from llm import generate_outreach_draft, generate_followup_draft
from decimal import Decimal

from db import SessionLocal
from models import Influencer, Campaign, OutreachThread, Message
from logging_config import get_logger
from scoring import compute_scores

from email_providers.factory import get_email_provider
from email_providers.base import SendEmailRequest

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

@celery_app.task(name="tasks.score_influencers")
def score_influencers(limit: int = 200, rescore_older_than_hours: int = 24) -> dict:
    """
    Computes brand_fit_score, risk_score, overall_score + score_breakdown for influencers.
    Default behavior:
      - score influencers never scored, OR
      - score influencers scored more than N hours ago
    """
    db = SessionLocal()
    task_id = getattr(current_task.request, "id", None)

    scored = 0
    skipped = 0

    try:
        cutoff = datetime.utcnow() - timedelta(hours=rescore_older_than_hours)

        q = (
            db.query(Influencer)
            .filter(
                (Influencer.score_updated_at.is_(None)) |
                (Influencer.score_updated_at < cutoff)
            )
            .limit(limit)
        )

        influencers = q.all()

        logger.info(
            "score_influencers_started",
            extra={
                "task_id": task_id,
                "limit": limit,
                "rescore_older_than_hours": rescore_older_than_hours,
                "selected": len(influencers),
            },
        )

        for inf in influencers:
            # If you later add outreach/reply counters, plug them in here
            scores = compute_scores(
                platform=inf.platform,
                followers=inf.followers,
                engagement_rate=inf.engagement_rate,
                bio=inf.bio,
                outreach_count=0,
                reply_count=0,
            )

            inf.brand_fit_score = scores["brand_fit_score"]
            inf.risk_score = scores["risk_score"]
            inf.overall_score = scores["overall_score"]
            inf.score_breakdown = scores["breakdown"]
            inf.score_updated_at = datetime.utcnow()

            scored += 1

        db.commit()

        logger.info(
            "score_influencers_completed",
            extra={
                "task_id": task_id,
                "scored_count": scored,
                "skipped_count": skipped,
            },
        )

        return {"scored": scored, "skipped": skipped}

    except Exception:
        logger.exception("score_influencers_failed", extra={"task_id": task_id})
        raise
    finally:
        db.close()

@celery_app.task(name="tasks.campaign_fill_and_draft")
def campaign_fill_and_draft(
    campaign_id: str,
    *,
    min_score: float = 70.0,
    max_new_threads: int = 25,
    influencer_platform: str | None = None,
    require_email: bool = True,
) -> dict:
    """
    Job #4:
      - Find top scored influencers
      - Create new threads for a given campaign (skipping existing)
      - Generate initial draft message for each new thread
      - Set thread.stage='needs_approval'

    Returns summary counts.
    """
    db = SessionLocal()
    task_id = getattr(current_task.request, "id", None)

    created_threads = 0
    drafted_messages = 0
    skipped_existing = 0
    skipped_missing_email = 0
    skipped_no_score = 0

    try:
        campaign = db.query(Campaign).get(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign not found: {campaign_id}")

        # Pull rules for draft generation defaults
        rules = campaign.rules or {}
        brand_context = rules.get("brand_context", {"brand_name": "Hello To Natural"})
        offer = rules.get("offer", {"type": campaign.offer_type})

        # Get influencer candidates
        q = db.query(Influencer)

        # Must be scored
        q = q.filter(Influencer.overall_score.isnot(None))
        q = q.filter(Influencer.overall_score >= Decimal(str(min_score)))

        if influencer_platform:
            q = q.filter(Influencer.platform == influencer_platform)

        if require_email:
            q = q.filter(Influencer.email.isnot(None)).filter(Influencer.email != "")

        # Highest score first
        candidates = (
            q.order_by(Influencer.overall_score.desc().nullslast(), Influencer.created_at.desc())
            .limit(max_new_threads * 5)  # over-fetch so we can skip existing threads
            .all()
        )

        logger.info(
            "campaign_fill_and_draft_started",
            extra={
                "task_id": task_id,
                "campaign_id": str(campaign_id),
                "min_score": min_score,
                "max_new_threads": max_new_threads,
                "platform": influencer_platform,
                "candidate_count": len(candidates),
            },
        )

        # Quick lookup: existing influencer_ids already in threads for this campaign
        existing = (
            db.query(OutreachThread.influencer_id)
            .filter(OutreachThread.campaign_id == campaign.id)
            .all()
        )
        existing_influencer_ids = {row[0] for row in existing}

        now = datetime.utcnow()

        for inf in candidates:
            if created_threads >= max_new_threads:
                break

            if require_email and (not inf.email):
                skipped_missing_email += 1
                continue

            if inf.overall_score is None:
                skipped_no_score += 1
                continue

            if inf.id in existing_influencer_ids:
                skipped_existing += 1
                continue

            # 1) Create thread
            thread = OutreachThread(
                campaign_id=campaign.id,
                influencer_id=inf.id,
                stage="new",
            )
            db.add(thread)
            db.flush()  # gets thread.id without committing yet

            # 2) Generate draft
            draft = generate_outreach_draft(
                brand_context=brand_context,
                influencer={
                    "handle": inf.handle,
                    "display_name": inf.display_name,
                    "platform": inf.platform,
                    "bio": inf.bio,
                    "followers": inf.followers,
                    "profile_url": inf.profile_url,
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
                created_at=now,
            )
            db.add(msg)

            # 3) Set stage for approval
            thread.stage = "needs_approval"

            created_threads += 1
            drafted_messages += 1
            existing_influencer_ids.add(inf.id)

        db.commit()

        logger.info(
            "campaign_fill_and_draft_completed",
            extra={
                "task_id": task_id,
                "campaign_id": str(campaign_id),
                "created_threads": created_threads,
                "drafted_messages": drafted_messages,
                "skipped_existing": skipped_existing,
                "skipped_missing_email": skipped_missing_email,
                "skipped_no_score": skipped_no_score,
            },
        )

        return {
            "campaign_id": str(campaign_id),
            "created_threads": created_threads,
            "drafted_messages": drafted_messages,
            "skipped_existing": skipped_existing,
            "skipped_missing_email": skipped_missing_email,
            "skipped_no_score": skipped_no_score,
        }

    except Exception:
        logger.exception(
            "campaign_fill_and_draft_failed",
            extra={"task_id": task_id, "campaign_id": str(campaign_id)},
        )
        raise
    finally:
        db.close()

@celery_app.task(name="tasks.campaign_approve_and_send")
def campaign_approve_and_send(
    campaign_id: str,
    *,
    limit: int = 20,
    followup_days: int = 3,
    require_email: bool = True,
) -> dict:
    db = SessionLocal()
    task_id = getattr(current_task.request, "id", None)

    approved = 0
    sent = 0
    failed = 0
    skipped = 0

    try:
        campaign = db.query(Campaign).get(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign not found: {campaign_id}")

        from_email = os.getenv("SENDGRID_FROM_EMAIL")
        from_name = os.getenv("SENDGRID_FROM_NAME", "Hello To Natural")
        inbound_domain = os.getenv("INBOUND_REPLY_DOMAIN")

        if not from_email:
            raise RuntimeError("SENDGRID_FROM_EMAIL is not set")
        if not inbound_domain:
            raise RuntimeError("INBOUND_REPLY_DOMAIN is not set")

        provider = get_email_provider()
        now = datetime.utcnow()

        logger.info(
            "campaign_approve_and_send_started",
            extra={
                "task_id": task_id,
                "campaign_id": str(campaign_id),
                "limit": limit,
                "followup_days": followup_days,
                "require_email": require_email,
            },
        )

        q = (
            db.query(Message, OutreachThread)
            .join(OutreachThread, Message.thread_id == OutreachThread.id)
            .filter(OutreachThread.campaign_id == campaign_id)
            .filter(OutreachThread.stage != "replied")
            .filter(Message.direction == "outbound")
            .filter(Message.channel == "email")
            .filter(Message.status == "draft")
            .order_by(Message.created_at.asc())
            .limit(limit)
        )

        rows = q.all()

        for msg, thread in rows:
            influencer = db.query(Influencer).get(thread.influencer_id)
            if not influencer:
                skipped += 1
                continue

            if require_email and (not influencer.email or influencer.email.strip() == ""):
                skipped += 1
                continue

            msg.status = "approved"
            approved += 1

            reply_to = f"replies+{thread.id}@{inbound_domain}"
            subject = msg.subject or f"Collab idea ({campaign.offer_type})"
            body = msg.body or ""

            try:
                r = provider.send_email(
                    SendEmailRequest(
                        to_email=influencer.email,
                        subject=subject,
                        body_text=body,
                        from_email=from_email,
                        from_name=from_name,
                        reply_to=reply_to,
                    )
                )

                msg.status = "sent"
                msg.provider_msg_id = r.provider_msg_id
                msg.sent_at = now

                thread.stage = "waiting"
                thread.last_contact_at = now
                thread.next_followup_at = now + timedelta(days=followup_days)

                sent += 1

            except Exception:
                msg.status = "failed"
                failed += 1

            # Commit per message so one failure doesn't roll back others
            db.commit()

        logger.info(
            "campaign_approve_and_send_completed",
            extra={
                "task_id": task_id,
                "campaign_id": str(campaign_id),
                "approved": approved,
                "sent": sent,
                "failed": failed,
                "skipped": skipped,
            },
        )

        return {
            "campaign_id": str(campaign_id),
            "approved": approved,
            "sent": sent,
            "failed": failed,
            "skipped": skipped,
        }

    except Exception:
        logger.exception("campaign_approve_and_send_failed", extra={"task_id": task_id, "campaign_id": str(campaign_id)})
        raise
    finally:
        db.close()