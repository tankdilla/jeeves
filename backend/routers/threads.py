from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID

from db import SessionLocal
from models import OutreachThread, Influencer, Campaign, Message
from schemas import ThreadCreate, ThreadOut, MessageOut, InboundMessageCreate

from datetime import datetime
import os

if os.getenv("ALLOW_TEST_ENDPOINTS", "false").lower() != "true":
    raise HTTPException(status_code=403, detail="Test endpoints disabled")

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("", response_model=ThreadOut)
def create_thread(payload: ThreadCreate, db: Session = Depends(get_db)):
    # validate foreign keys exist
    if not db.query(Campaign).get(payload.campaign_id):
        raise HTTPException(status_code=404, detail="Campaign not found")
    if not db.query(Influencer).get(payload.influencer_id):
        raise HTTPException(status_code=404, detail="Influencer not found")

    thread = OutreachThread(
        campaign_id=payload.campaign_id,
        influencer_id=payload.influencer_id,
        stage="drafting",
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread

@router.get("", response_model=List[ThreadOut])
def list_threads(stage: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(OutreachThread)
    if stage:
        q = q.filter(OutreachThread.stage == stage)
    
    # Prefer next_followup_at soonest, then last_contact_at most recent, then stable fallback
    # This is a practical ordering for an outreach inbox.
    return (
        q.order_by(
            OutreachThread.next_followup_at.asc().nulls_last(),
            OutreachThread.last_contact_at.desc().nulls_last(),
            OutreachThread.id.desc(),
        )
        .limit(200)
        .all()
    )
    # return q.limit(200).all()
    # return q.order_by(OutreachThread.created_at.desc()).limit(200).all()

# get one thread by id
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

@router.post("/{thread_id}/simulate_inbound", response_model=MessageOut)
def simulate_inbound(thread_id: UUID, payload: InboundMessageCreate, db: Session = Depends(get_db)):
    """
    TESTING endpoint: simulates an inbound reply from an influencer.
    Creates Message(direction='inbound', status='received') and optionally updates thread.stage.
    """
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

    # Update thread stage (optional)
    if payload.set_thread_stage:
        thread.stage = payload.set_thread_stage

    # Also update last_contact_at since a reply is contact
    thread.last_contact_at = received_at
    thread.next_followup_at = None  # stop follow-ups when replied

    db.commit()
    db.refresh(msg)
    return msg
