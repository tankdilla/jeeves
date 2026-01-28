from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from datetime import datetime, timedelta
import uuid as uuidlib

from typing import List, Optional

from db import SessionLocal
from models import OutreachThread, Message, Influencer, Campaign
from schemas import DraftRequest, MessageOut, ApproveRequest, SendResult

from llm import generate_outreach_draft  # expects you already have this

FOLLOWUP_DAYS_DEFAULT = 3

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

    now = datetime.utcnow()
    msg.status = "sent"
    msg.provider_msg_id = provider_msg_id
    msg.sent_at = now

    thread = db.query(OutreachThread).get(msg.thread_id)
    if thread:
        # ✅ Job #3 scheduling fields
        thread.stage = "waiting"
        thread.last_contact_at = now
        thread.next_followup_at = now + timedelta(days=FOLLOWUP_DAYS_DEFAULT)

    db.commit()
    return SendResult(status="sent", provider_msg_id=provider_msg_id)


# --------------------------------------------------------------------
#  READ-ONLY ENDPOINTS
# --------------------------------------------------------------------

#  get one message by id
@router.get("/{message_id}", response_model=MessageOut)
def get_message(message_id: UUID, db: Session = Depends(get_db)):
    msg = db.query(Message).get(message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    return msg

# list messages (optionally filter by status or thread)
@router.get("", response_model=List[MessageOut])
def list_messages(
    status: Optional[str] = None,
    thread_id: Optional[UUID] = None,
    db: Session = Depends(get_db)
):
    q = db.query(Message)
    if status:
        q = q.filter(Message.status == status)
    if thread_id:
        q = q.filter(Message.thread_id == thread_id)
    return q.order_by(Message.created_at.desc()).limit(200).all()

# list messages for a thread (canonical endpoint)
@router.get("/thread/{thread_id}", response_model=List[MessageOut])
def list_messages_for_thread(thread_id: UUID, db: Session = Depends(get_db)):
    # ensure thread exists (helps with clearer errors)
    thread = db.query(OutreachThread).get(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    msgs = (
        db.query(Message)
        .filter(Message.thread_id == thread_id)
        .order_by(Message.created_at.asc())
        .all()
    )
    return msgs