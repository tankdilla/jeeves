# models.py
import uuid
from sqlalchemy import (
    Column, String, Integer, DateTime, Text, Enum, ForeignKey, Numeric, JSON
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime
from db import Base

# Base = declarative_base()

class Influencer(Base):
    __tablename__ = "influencers"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform = Column(String, nullable=False)
    handle = Column(String, nullable=False, index=True)
    display_name = Column(String, nullable=True)
    profile_url = Column(String, nullable=True)
    email = Column(String, nullable=True)
    bio = Column(Text, nullable=True)
    followers = Column(Integer, nullable=True)
    engagement_rate = Column(Numeric, nullable=True)
    niche_tags = Column(JSON, nullable=True)

    brand_fit_score = Column(Numeric, nullable=True)
    risk_score = Column(Numeric, nullable=True)
    overall_score = Column(Numeric, nullable=True)

    score_breakdown = Column(JSON, nullable=True)
    score_updated_at = Column(DateTime, nullable=True)

    discovered_source = Column(String, nullable=True)  # optional but handy

    status = Column(String, nullable=False, default="new")
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Campaign(Base):
    __tablename__ = "campaigns"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    offer_type = Column(String, nullable=False)  # gifted/paid/affiliate
    rules = Column(JSON, nullable=True)

class OutreachThread(Base):
    __tablename__ = "outreach_threads"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=False)
    influencer_id = Column(UUID(as_uuid=True), ForeignKey("influencers.id"), nullable=False)

    stage = Column(String, nullable=False, default="new")
    deal_terms = Column(JSON, nullable=True)

    last_contact_at = Column(DateTime, nullable=True)
    next_followup_at = Column(DateTime, nullable=True)

    influencer = relationship("Influencer")
    campaign = relationship("Campaign")
    messages = relationship("Message", back_populates="thread")

class Message(Base):
    __tablename__ = "messages"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id = Column(UUID(as_uuid=True), ForeignKey("outreach_threads.id"), nullable=False)
    channel = Column(String, nullable=False)     # email/dm
    direction = Column(String, nullable=False)   # outbound/inbound
    status = Column(String, nullable=False)      # draft/approved/sent/failed
    subject = Column(String, nullable=True)
    body = Column(Text, nullable=False)
    provider_msg_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)

    thread = relationship("OutreachThread", back_populates="messages")
