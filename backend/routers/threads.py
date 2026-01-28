from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID

from db import SessionLocal
from models import OutreachThread, Influencer, Campaign, Message
from schemas import ThreadCreate, ThreadOut, MessageOut

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