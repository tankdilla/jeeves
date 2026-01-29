import os
import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional, Dict, Any
from uuid import UUID

from db import SessionLocal
from models import Campaign
from schemas import CampaignCreate, CampaignOut

from models import OutreachThread, Message, Influencer  # Campaign already imported
from email_providers.factory import get_email_provider
from email_providers.base import SendEmailRequest

from celery.result import AsyncResult
from celery_app import celery_app
from celery import chain

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("", response_model=CampaignOut)
def create_campaign(payload: CampaignCreate, db: Session = Depends(get_db)):
    c = Campaign(**payload.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@router.get("", response_model=List[CampaignOut])
def list_campaigns(db: Session = Depends(get_db)):
    return db.query(Campaign).order_by(Campaign.name.asc()).all()


# ----------------------------
# Job #4 trigger endpoint
# ----------------------------
@router.post("/{campaign_id}/fill_and_draft")
def trigger_fill_and_draft(
    campaign_id: UUID,
    min_score: float = 70.0,
    max_new_threads: int = 25,
    platform: Optional[str] = None,
    require_email: bool = True,
    db: Session = Depends(get_db),
):
    # Ensure campaign exists (so you get a clean 404 instead of a Celery failure later)
    c = db.query(Campaign).get(campaign_id)
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Fire-and-return
    task = celery_app.send_task(
        "tasks.campaign_fill_and_draft",
        args=[str(campaign_id)],
        kwargs={
            "min_score": float(min_score),
            "max_new_threads": int(max_new_threads),
            "influencer_platform": platform,
            "require_email": bool(require_email),
        },
    )

    return {
        "status": "queued",
        "task_id": task.id,
        "campaign_id": str(campaign_id),
        "params": {
            "min_score": min_score,
            "max_new_threads": max_new_threads,
            "platform": platform,
            "require_email": require_email,
        },
    }


# ----------------------------
# Basic Celery task status endpoint
# ----------------------------
@router.get("/tasks/{task_id}")
def get_task_status(task_id: str):
    res = AsyncResult(task_id, app=celery_app)

    payload = {
        "task_id": task_id,
        "state": res.state,
    }

    # If done, include result/exception
    if res.successful():
        payload["result"] = res.result
    elif res.failed():
        # Exception text is often enough for MVP diagnostics
        payload["error"] = str(res.result)

    return payload

@router.post("/{campaign_id}/approve_and_send")
def approve_and_send(
    campaign_id: UUID,
    limit: int = 20,
    followup_days: int = 3,
    require_email: bool = True,
    db: Session = Depends(get_db),
):
    """
    Approves + sends outbound draft emails for a campaign (up to `limit`).
    Safe defaults:
      - only sends messages with status='draft' and direction='outbound' and channel='email'
      - only threads not already replied
      - updates thread.last_contact_at + next_followup_at
    """
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")

    campaign = db.query(Campaign).get(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    from_email = os.getenv("SENDGRID_FROM_EMAIL")
    from_name = os.getenv("SENDGRID_FROM_NAME", "Hello To Natural")
    inbound_domain = os.getenv("INBOUND_REPLY_DOMAIN")  # used for thread-specific Reply-To

    if not from_email:
        raise HTTPException(status_code=500, detail="SENDGRID_FROM_EMAIL is not set")
    if not inbound_domain:
        raise HTTPException(status_code=500, detail="INBOUND_REPLY_DOMAIN is not set")

    provider = get_email_provider()
    now = datetime.utcnow()

    # Find candidate messages:
    # - Message: outbound, email, draft
    # - Thread: belongs to campaign, not replied
    # Order oldest first to behave like an inbox backlog processor
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

    approved = 0
    sent = 0
    failed = 0
    skipped = 0

    results = []

    for msg, thread in rows:
        influencer = db.query(Influencer).get(thread.influencer_id)
        if not influencer:
            skipped += 1
            results.append({"message_id": str(msg.id), "status": "skipped", "reason": "Influencer not found"})
            continue

        if require_email and (not influencer.email or influencer.email.strip() == ""):
            skipped += 1
            results.append({"message_id": str(msg.id), "status": "skipped", "reason": "Influencer missing email"})
            continue

        # Approve it
        msg.status = "approved"
        approved += 1

        # Build thread-specific reply-to so inbound parse can map replies back to thread
        reply_to = f"replies+{thread.id}@{inbound_domain}"

        subject = msg.subject or f"Collab idea ({campaign.offer_type})"
        body = msg.body or ""

        try:
            send_result = provider.send_email(
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
            msg.provider_msg_id = send_result.provider_msg_id
            msg.sent_at = now

            thread.stage = "waiting"
            thread.last_contact_at = now
            thread.next_followup_at = now + timedelta(days=followup_days)

            sent += 1
            results.append(
                {
                    "message_id": str(msg.id),
                    "thread_id": str(thread.id),
                    "status": "sent",
                    "provider_msg_id": send_result.provider_msg_id,
                    "dry_run": bool(send_result.dry_run),
                }
            )

        except Exception as e:
            msg.status = "failed"
            failed += 1
            results.append({"message_id": str(msg.id), "thread_id": str(thread.id), "status": "failed", "error": str(e)})

        # Commit per message so one failure doesn’t roll back others
        db.commit()

    return {
        "campaign_id": str(campaign_id),
        "limit": limit,
        "approved": approved,
        "sent": sent,
        "failed": failed,
        "skipped": skipped,
        "results": results,
    }

@router.post("/{campaign_id}/pipeline")
def run_campaign_pipeline(
    campaign_id: UUID,
    # Step 1 (fill + draft)
    min_score: float = 70.0,
    max_new_threads: int = 25,
    platform: Optional[str] = None,
    # Step 2 (approve + send)
    send_limit: int = 20,
    followup_days: int = 3,
    require_email: bool = True,
    db: Session = Depends(get_db),
):
    """
    Pipeline:
      1) Fill campaign with top influencers + generate drafts (Job #4)
      2) Approve + send drafts (Job #5)
    Returns pipeline_id and Celery task IDs.
    """
    c = db.query(Campaign).get(campaign_id)
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")

    pipeline_id = str(uuid.uuid4())

    # # 1) Fill & draft
    # t1 = celery_app.send_task(
    #     "tasks.campaign_fill_and_draft",
    #     args=[str(campaign_id)],
    #     kwargs={
    #         "min_score": float(min_score),
    #         "max_new_threads": int(max_new_threads),
    #         "influencer_platform": platform,
    #         "require_email": bool(require_email),
    #     },
    # )

    # # 2) Approve & send — chained to run after fill/draft completes
    # # Link ensures Celery triggers this task when t1 finishes.
    # t2 = celery_app.send_task(
    #     "tasks.campaign_approve_and_send",
    #     args=[str(campaign_id)],
    #     kwargs={
    #         "limit": int(send_limit),
    #         "followup_days": int(followup_days),
    #         "require_email": bool(require_email),
    #     },
    #     link=t1  # NOTE: see below
    # )

    pipeline = chain(
        celery_app.signature(
            "tasks.campaign_fill_and_draft",
            args=[str(campaign_id)],
            kwargs={
                "min_score": float(min_score),
                "max_new_threads": int(max_new_threads),
                "influencer_platform": platform,
                "require_email": bool(require_email),
            },
        ),
        celery_app.signature(
            "tasks.campaign_approve_and_send",
            args=[str(campaign_id)],
            kwargs={
                "limit": int(send_limit),
                "followup_days": int(followup_days),
                "require_email": bool(require_email),
            },
        ),
    )

    res = pipeline.apply_async()

    # return {
    #     "status": "queued",
    #     "pipeline_id": pipeline_id,
    #     "campaign_id": str(campaign_id),
    #     "root_task_id": res.id,
    #     "params": {...},
    # }


    return {
        "status": "queued",
        "pipeline_id": pipeline_id,
        "campaign_id": str(campaign_id),
        "root_task_id": res.id,
        "params": {
            "min_score": min_score,
            "max_new_threads": max_new_threads,
            "platform": platform,
            "send_limit": send_limit,
            "followup_days": followup_days,
            "require_email": require_email,
        },
    }

@router.get("/{campaign_id}/pipeline_status")
def campaign_pipeline_status(
    campaign_id: UUID,
    task_id: Optional[str] = None,
    include_recent_failures: bool = True,
    failure_limit: int = 25,
    db: Session = Depends(get_db),
):
    """
    Returns pipeline-like operational status based on DB state.

    Optionally include Celery task state/result if `task_id` is provided.
    """
    if failure_limit < 1 or failure_limit > 200:
        raise HTTPException(status_code=400, detail="failure_limit must be between 1 and 200")

    campaign = db.query(Campaign).get(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # ---- Threads summary ----
    threads_total = (
        db.query(func.count(OutreachThread.id))
        .filter(OutreachThread.campaign_id == campaign_id)
        .scalar()
    ) or 0

    threads_by_stage_rows = (
        db.query(OutreachThread.stage, func.count(OutreachThread.id))
        .filter(OutreachThread.campaign_id == campaign_id)
        .group_by(OutreachThread.stage)
        .all()
    )
    threads_by_stage: Dict[str, int] = {stage: int(cnt) for stage, cnt in threads_by_stage_rows}

    # ---- Messages summary (only messages tied to this campaign via threads join) ----
    messages_total = (
        db.query(func.count(Message.id))
        .join(OutreachThread, Message.thread_id == OutreachThread.id)
        .filter(OutreachThread.campaign_id == campaign_id)
        .scalar()
    ) or 0

    messages_by_status_rows = (
        db.query(Message.status, func.count(Message.id))
        .join(OutreachThread, Message.thread_id == OutreachThread.id)
        .filter(OutreachThread.campaign_id == campaign_id)
        .group_by(Message.status)
        .all()
    )
    messages_by_status: Dict[str, int] = {status: int(cnt) for status, cnt in messages_by_status_rows}

    outbound_by_status_rows = (
        db.query(Message.status, func.count(Message.id))
        .join(OutreachThread, Message.thread_id == OutreachThread.id)
        .filter(OutreachThread.campaign_id == campaign_id)
        .filter(Message.direction == "outbound")
        .group_by(Message.status)
        .all()
    )
    outbound_by_status: Dict[str, int] = {status: int(cnt) for status, cnt in outbound_by_status_rows}

    inbound_count = (
        db.query(func.count(Message.id))
        .join(OutreachThread, Message.thread_id == OutreachThread.id)
        .filter(OutreachThread.campaign_id == campaign_id)
        .filter(Message.direction == "inbound")
        .scalar()
    ) or 0

    # ---- Timing signals ----
    last_outbound_sent_at = (
        db.query(func.max(Message.sent_at))
        .join(OutreachThread, Message.thread_id == OutreachThread.id)
        .filter(OutreachThread.campaign_id == campaign_id)
        .filter(Message.direction == "outbound")
        .scalar()
    )

    now = datetime.utcnow()

    waiting_due_count = (
        db.query(func.count(OutreachThread.id))
        .filter(OutreachThread.campaign_id == campaign_id)
        .filter(OutreachThread.stage == "waiting")
        .filter(OutreachThread.next_followup_at.isnot(None))
        .filter(OutreachThread.next_followup_at <= now)
        .scalar()
    ) or 0

    needs_approval_count = (
        db.query(func.count(OutreachThread.id))
        .filter(OutreachThread.campaign_id == campaign_id)
        .filter(OutreachThread.stage == "needs_approval")
        .scalar()
    ) or 0

    # ---- Recent failures (optional) ----
    recent_failures = []
    if include_recent_failures:
        failed_rows = (
            db.query(Message, OutreachThread)
            .join(OutreachThread, Message.thread_id == OutreachThread.id)
            .filter(OutreachThread.campaign_id == campaign_id)
            .filter(Message.status == "failed")
            .order_by(Message.created_at.desc())
            .limit(failure_limit)
            .all()
        )

        recent_failures = [
            {
                "message_id": str(m.id),
                "thread_id": str(t.id),
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "sent_at": m.sent_at.isoformat() if m.sent_at else None,
                "subject": m.subject,
                "channel": m.channel,
                "direction": m.direction,
                "provider_msg_id": m.provider_msg_id,
            }
            for (m, t) in failed_rows
        ]

    # ---- Optional Celery task info ----
    celery_info: Dict[str, Any] | None = None
    if task_id:
        res = AsyncResult(task_id, app=celery_app)
        celery_info = {"task_id": task_id, "state": res.state}
        if res.successful():
            celery_info["result"] = res.result
        elif res.failed():
            celery_info["error"] = str(res.result)

    # ---- A simple derived "pipeline step" hint ----
    # (DB-driven, not Celery-driven)
    # new -> needs_approval -> waiting -> replied
    inferred_step = "idle"
    if needs_approval_count > 0:
        inferred_step = "approval_queue"
    elif threads_by_stage.get("new", 0) > 0 or threads_by_stage.get("drafting", 0) > 0:
        inferred_step = "drafting"
    elif threads_by_stage.get("waiting", 0) > 0:
        inferred_step = "waiting_for_replies"
    elif threads_by_stage.get("replied", 0) > 0:
        inferred_step = "replies_received"

    return {
        "campaign_id": str(campaign_id),
        "campaign_name": campaign.name,
        "inferred_step": inferred_step,
        "now": now.isoformat(),
        "threads": {
            "total": threads_total,
            "by_stage": threads_by_stage,
            "needs_approval": needs_approval_count,
            "waiting_due": waiting_due_count,
        },
        "messages": {
            "total": messages_total,
            "by_status": messages_by_status,
            "outbound_by_status": outbound_by_status,
            "inbound_count": int(inbound_count),
            "last_outbound_sent_at": last_outbound_sent_at.isoformat() if last_outbound_sent_at else None,
        },
        "recent_failures": recent_failures,
        "celery": celery_info,
    }
