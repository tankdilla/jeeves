import json
import os
import re
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from db import SessionLocal
from models import OutreachThread, Message

router = APIRouter(prefix="/webhooks/sendgrid", tags=["webhooks"])

THREAD_RE = re.compile(r"replies\+([0-9a-fA-F-]{36})@", re.IGNORECASE)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _extract_thread_id(to_field: str, envelope_json: str | None) -> UUID | None:
    """
    Prefer envelope['to'] if present; otherwise use the 'to' field.
    We look for: replies+<uuid>@...
    """
    candidates = []

    if envelope_json:
        try:
            env = json.loads(envelope_json)
            # envelope: {"to":["addr1","addr2"], "from":"..."}
            if isinstance(env, dict) and isinstance(env.get("to"), list):
                candidates.extend([str(x) for x in env["to"]])
        except Exception:
            pass

    if to_field:
        candidates.append(to_field)

    for c in candidates:
        m = THREAD_RE.search(c)
        if m:
            return UUID(m.group(1))

    return None

@router.post("/inbound")
async def inbound_email(request: Request, db: Session = Depends(get_db)):
    """
    SendGrid Inbound Parse webhook.
    Receives multipart/form-data including fields like:
      - to, from, subject, text, html, headers, envelope, attachments, attachment-info, etc.
    """
    form = await request.form()

    to_field = str(form.get("to") or "")
    from_field = str(form.get("from") or "")
    subject = str(form.get("subject") or "")
    text = str(form.get("text") or "")
    html = str(form.get("html") or "")
    envelope = form.get("envelope")
    envelope_json = str(envelope) if envelope is not None else None

    # Determine thread id from replies+<thread_id>@inbound-domain
    thread_id = _extract_thread_id(to_field=to_field, envelope_json=envelope_json)
    if not thread_id:
        raise HTTPException(status_code=400, detail="Could not determine thread_id from inbound email")

    thread = db.query(OutreachThread).get(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    received_at = datetime.utcnow()

    # Prefer plain text; fallback to html if needed
    body = text.strip() if text.strip() else (html.strip() or "(no body)")

    msg = Message(
        thread_id=thread.id,
        channel="email",
        direction="inbound",
        status="received",
        subject=subject or None,
        body=body,
        created_at=received_at,
    )
    db.add(msg)

    # Stop follow-ups, mark thread replied
    thread.stage = "replied"
    thread.last_contact_at = received_at
    thread.next_followup_at = None

    db.commit()
    return {"status": "ok", "thread_id": str(thread.id), "message_id": str(msg.id)}
