from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID

from db import SessionLocal
from models import OutreachThread, Influencer, Campaign
from schemas import ThreadCreate, ThreadOut

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
    return q.order_by(OutreachThread.created_at.desc()).limit(200).all()
