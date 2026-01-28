# schemas.py
from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, Any, List
from uuid import UUID
from decimal import Decimal
from datetime import datetime

# ---------- Influencers ----------
class InfluencerCreate(BaseModel):
    platform: str
    handle: str
    display_name: Optional[str] = None
    profile_url: Optional[str] = None
    email: Optional[EmailStr] = None
    bio: Optional[str] = None
    followers: Optional[int] = None
    engagement_rate: Optional[Decimal] = None
    niche_tags: Optional[Dict[str, Any]] = None

class InfluencerUpdate(BaseModel):
    display_name: Optional[str] = None
    profile_url: Optional[str] = None
    email: Optional[EmailStr] = None
    bio: Optional[str] = None
    followers: Optional[int] = None
    engagement_rate: Optional[Decimal] = None
    niche_tags: Optional[Dict[str, Any]] = None
    status: Optional[str] = None
    notes: Optional[str] = None

class InfluencerOut(BaseModel):
    id: UUID
    platform: str
    handle: str
    status: str
    overall_score: Optional[Decimal] = None

    class Config:
        from_attributes = True

# ---------- Campaigns ----------
class CampaignCreate(BaseModel):
    name: str
    offer_type: str  # gifted / paid / affiliate
    rules: Optional[Dict[str, Any]] = None

class CampaignOut(BaseModel):
    id: UUID
    name: str
    offer_type: str
    rules: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True

# ---------- Threads ----------
class ThreadCreate(BaseModel):
    campaign_id: UUID
    influencer_id: UUID

class ThreadOut(BaseModel):
    id: UUID
    campaign_id: UUID
    influencer_id: UUID
    stage: str

    last_contact_at: Optional[datetime] = None
    next_followup_at: Optional[datetime] = None  

    class Config:
        from_attributes = True

# ---------- Messages ----------
class DraftRequest(BaseModel):
    channel: str = "email"  # email or dm
    # optionally override offer/brand_context per draft:
    brand_context: Optional[Dict[str, Any]] = None
    offer: Optional[Dict[str, Any]] = None

class MessageOut(BaseModel):
    id: UUID
    thread_id: UUID
    channel: str
    direction: str
    status: str
    subject: Optional[str] = None
    body: str
    created_at: datetime
    sent_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class ApproveRequest(BaseModel):
    approved: bool = True

class SendResult(BaseModel):
    status: str
    provider_msg_id: Optional[str] = None
