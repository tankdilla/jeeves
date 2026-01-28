from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from db import SessionLocal
from models import Campaign
from schemas import CampaignCreate, CampaignOut

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
