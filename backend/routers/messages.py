from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from datetime import datetime
import uuid as uuidlib

from db import SessionLocal
from models import OutreachThread, Message, Influencer, Campaign
from schemas import DraftRequest, MessageOut, ApproveRequest, SendResult

from llm import generate_outreach_draft  # expects you already have this

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/draft/{thread_id}", response_model=MessageOut)
def generate_draft(thread_id: UUID, payload: DraftRequest, db: Session = Depends(get_db)):
    thread = db.query(OutreachThread).get(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    influencer = db.query(Influencer).get(thread.influencer_id)
    campaign = db.query(Campaign).get(thread.campaign_id)
    if not influencer or not campaign:
        raise HTTPException(status_code=400, detail="Thread is missing influencer or campaign")

    rules = campaign.rules or {}
    brand_context = payload.brand_context or rules.get("brand_context", {})
    offer = payload.offer or rules.get("offer", {"type": campaign.offer_type})

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
        channel=payload.channel,
        direction="outbound",
        status="draft",
        subject=draft.get("subject"),
        body=draft.get("body"),
    )
    db.add(msg)

    thread.stage = "needs_approval"
    db.commit()
    db.refresh(msg)
    return msg

@router.post("/{message_id}/approve", response_model=MessageOut)
def approve_message(message_id: UUID, payload: ApproveRequest, db: Session = Depends(get_db)):
    msg = db.query(Message).get(message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.status != "draft":
        raise HTTPException(status_code=400, detail=f"Message is not draft (status={msg.status})")

    msg.status = "approved" if payload.approved else "draft"
    db.commit()
    db.refresh(msg)
    return msg

@router.post("/{message_id}/send", response_model=SendResult)
def send_message(message_id: UUID, db: Session = Depends(get_db)):
    """
    MVP: stub sender (marks as sent).
    Next step: replace with SendGrid/Gmail API send and store provider_msg_id.
    """
    msg = db.query(Message).get(message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.status != "approved":
        raise HTTPException(status_code=400, detail=f"Message not approved (status={msg.status})")

    # TODO: integrate real email provider here
    provider_msg_id = f"stub-{uuidlib.uuid4()}"
    msg.status = "sent"
    msg.provider_msg_id = provider_msg_id
    msg.sent_at = datetime.utcnow()

    thread = db.query(OutreachThread).get(msg.thread_id)
    if thread:
        thread.stage = "waiting"

    db.commit()
    return SendResult(status="sent", provider_msg_id=provider_msg_id)
