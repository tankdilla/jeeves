from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import List, Optional
from uuid import UUID
from datetime import datetime
import os

from db import SessionLocal
from models import OutreachThread, Influencer, Campaign, Message
from schemas import ThreadCreate, ThreadOut, MessageOut, InboundMessageCreate

from pydantic import BaseModel, Field


router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ----------------------------
# Single thread create
# ----------------------------
@router.post("", response_model=ThreadOut)
def create_thread(payload: ThreadCreate, db: Session = Depends(get_db)):
    # validate foreign keys exist
    if not db.query(Campaign).get(payload.campaign_id):
        raise HTTPException(status_code=404, detail="Campaign not found")
    if not db.query(Influencer).get(payload.influencer_id):
        raise HTTPException(status_code=404, detail="Influencer not found")

    # prevent duplicates
    existing = (
        db.query(OutreachThread)
        .filter(
            OutreachThread.campaign_id == payload.campaign_id,
            OutreachThread.influencer_id == payload.influencer_id,
        )
        .first()
    )
    if existing:
        return existing

    thread = OutreachThread(
        campaign_id=payload.campaign_id,
        influencer_id=payload.influencer_id,
        stage="new",
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


# ----------------------------
# Bulk thread create
# ----------------------------
class BulkThreadsCreate(BaseModel):
    campaign_id: UUID
    influencer_ids: List[UUID] = Field(min_length=1, max_length=500)
    stage: str = "new"


class BulkThreadsResult(BaseModel):
    created_count: int
    skipped_existing_count: int
    missing_influencers_count: int
    threads: List[ThreadOut]


@router.post("/bulk", response_model=BulkThreadsResult)
def create_threads_bulk(payload: BulkThreadsCreate, db: Session = Depends(get_db)):
    # Validate campaign exists
    campaign = db.query(Campaign).get(payload.campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Load influencers that exist
    influencers = (
        db.query(Influencer)
        .filter(Influencer.id.in_(payload.influencer_ids))
        .all()
    )
    found_ids = {inf.id for inf in influencers}
    missing_ids = [iid for iid in payload.influencer_ids if iid not in found_ids]

    created: List[OutreachThread] = []
    skipped_existing = 0

    # Build a quick lookup of existing threads for this campaign
    existing_threads = (
        db.query(OutreachThread.influencer_id)
        .filter(OutreachThread.campaign_id == payload.campaign_id)
        .filter(OutreachThread.influencer_id.in_(list(found_ids)))
        .all()
    )
    existing_influencer_ids = {row[0] for row in existing_threads}

    # Create threads for influencers that don't already have one
    for inf in influencers:
        if inf.id in existing_influencer_ids:
            skipped_existing += 1
            continue

        t = OutreachThread(
            campaign_id=payload.campaign_id,
            influencer_id=inf.id,
            stage=payload.stage or "new",
        )
        db.add(t)
        created.append(t)

    db.commit()

    # Refresh created for response
    for t in created:
        db.refresh(t)

    return BulkThreadsResult(
        created_count=len(created),
        skipped_existing_count=skipped_existing,
        missing_influencers_count=len(missing_ids),
        threads=created,
    )


# ----------------------------
# List + read threads
# ----------------------------
@router.get("", response_model=List[ThreadOut])
def list_threads(stage: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(OutreachThread)
    if stage:
        q = q.filter(OutreachThread.stage == stage)

    # Prefer next_followup_at soonest, then last_contact_at most recent, then stable fallback
    return (
        q.order_by(
            OutreachThread.next_followup_at.asc().nulls_last(),
            OutreachThread.last_contact_at.desc().nulls_last(),
            OutreachThread.id.desc(),
        )
        .limit(200)
        .all()
    )


@router.get("/{thread_id}", response_model=ThreadOut)
def get_thread(thread_id: UUID, db: Session = Depends(get_db)):
    thread = db.query(OutreachThread).get(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


@router.get("/{thread_id}/messages", response_model=List[MessageOut])
def get_thread_messages(thread_id: UUID, db: Session = Depends(get_db)):
    thread = db.query(OutreachThread).get(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    return (
        db.query(Message)
        .filter(Message.thread_id == thread_id)
        .order_by(Message.created_at.asc())
        .limit(500)
        .all()
    )


# ----------------------------
# TEST ONLY: simulate inbound
# ----------------------------
@router.post("/{thread_id}/simulate_inbound", response_model=MessageOut)
def simulate_inbound(thread_id: UUID, payload: InboundMessageCreate, db: Session = Depends(get_db)):
    if os.getenv("ALLOW_TEST_ENDPOINTS", "false").lower() != "true":
        raise HTTPException(status_code=403, detail="Test endpoints disabled")

    thread = db.query(OutreachThread).get(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    received_at = payload.received_at or datetime.utcnow()

    msg = Message(
        thread_id=thread.id,
        channel=payload.channel,
        direction="inbound",
        status="received",
        subject=payload.subject,
        body=payload.body,
        created_at=received_at,
    )
    db.add(msg)

    if payload.set_thread_stage:
        thread.stage = payload.set_thread_stage

    thread.last_contact_at = received_at
    thread.next_followup_at = None  # stop follow-ups when replied

    db.commit()
    db.refresh(msg)
    return msg
