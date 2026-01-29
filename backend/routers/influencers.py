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
def list_influencers(
    status: Optional[str] = None,
    platform: Optional[str] = None,
    min_score: Optional[float] = None,
    has_email: Optional[bool] = None,
    sort: str = "created_desc",   # created_desc | score_desc | score_asc
    limit: int = 200,
    db: Session = Depends(get_db),
):
    """
    List influencers with optional filters.

    Examples:
      /influencers?status=discovered
      /influencers?min_score=70&sort=score_desc
      /influencers?platform=instagram&has_email=true&min_score=65
    """
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 500")

    q = db.query(Influencer)

    if status:
        q = q.filter(Influencer.status == status)

    if platform:
        q = q.filter(Influencer.platform == platform)

    if min_score is not None:
        q = q.filter(Influencer.overall_score.isnot(None))
        q = q.filter(Influencer.overall_score >= min_score)

    if has_email is True:
        q = q.filter(Influencer.email.isnot(None)).filter(Influencer.email != "")
    elif has_email is False:
        q = q.filter((Influencer.email.is_(None)) | (Influencer.email == ""))

    # Sorting
    if sort == "created_desc":
        q = q.order_by(Influencer.created_at.desc())
    elif sort == "score_desc":
        # Put scored records first, then sort by score desc, then newest
        q = q.order_by(Influencer.overall_score.desc().nullslast(), Influencer.created_at.desc())
    elif sort == "score_asc":
        q = q.order_by(Influencer.overall_score.asc().nullslast(), Influencer.created_at.desc())
    else:
        raise HTTPException(status_code=400, detail="sort must be one of: created_desc, score_desc, score_asc")

    return q.limit(limit).all()

@router.get("/top", response_model=List[InfluencerOut])
def top_influencers(
    limit: int = 50,
    min_score: float = 70.0,
    has_email: bool = True,
    platform: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Convenience endpoint for quickly getting a shortlist.
    Defaults:
      - min_score=70
      - requires email
      - score_desc ordering
    """
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")

    q = (
        db.query(Influencer)
        .filter(Influencer.overall_score.isnot(None))
        .filter(Influencer.overall_score >= min_score)
    )

    if platform:
        q = q.filter(Influencer.platform == platform)

    if has_email:
        q = q.filter(Influencer.email.isnot(None)).filter(Influencer.email != "")

    return q.order_by(Influencer.overall_score.desc().nullslast(), Influencer.created_at.desc()).limit(limit).all()

@router.get("/{influencer_id}", response_model=InfluencerOut)
def get_influencer(influencer_id: UUID, db: Session = Depends(get_db)):
    inf = db.query(Influencer).get(influencer_id)
    if not inf:
        raise HTTPException(status_code=404, detail="Influencer not found")
    return inf

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
