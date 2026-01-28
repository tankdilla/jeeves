from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID

from db import SessionLocal
from models import Influencer
from schemas import InfluencerCreate, InfluencerUpdate, InfluencerOut

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("", response_model=InfluencerOut)
def create_influencer(payload: InfluencerCreate, db: Session = Depends(get_db)):
    inf = Influencer(**payload.model_dump())
    db.add(inf)
    db.commit()
    db.refresh(inf)
    return inf

@router.get("", response_model=List[InfluencerOut])
def list_influencers(status: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(Influencer)
    if status:
        q = q.filter(Influencer.status == status)
    return q.order_by(Influencer.created_at.desc()).limit(200).all()

@router.patch("/{influencer_id}", response_model=InfluencerOut)
def update_influencer(influencer_id: UUID, payload: InfluencerUpdate, db: Session = Depends(get_db)):
    inf = db.query(Influencer).get(influencer_id)
    if not inf:
        raise HTTPException(status_code=404, detail="Influencer not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(inf, k, v)
    db.commit()
    db.refresh(inf)
    return inf
