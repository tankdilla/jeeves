import os
import hashlib
from typing import Dict, Any

def _stable_tag(*parts: str) -> str:
    raw = "|".join([p or "" for p in parts])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]

def _mock_outreach(brand_context: Dict[str, Any], influencer: Dict[str, Any], offer: Dict[str, Any]) -> Dict[str, str]:
    brand_name = (brand_context or {}).get("brand_name", "Hello To Natural")
    site = (brand_context or {}).get("site", "")
    handle = influencer.get("handle") or "there"
    display = influencer.get("display_name") or handle
    platform = influencer.get("platform") or "social"
    bio = (influencer.get("bio") or "").strip()

    offer_type = (offer or {}).get("type", "gifted")
    offer_details = (offer or {}).get("details", "a product set")
    cta = (offer or {}).get("cta", "If you're open, reply with your email + shipping info.")

    tag = _stable_tag(brand_name, handle, platform, offer_type, offer_details)

    subject = f"Collab idea for {display} ({offer_type}) [{tag}]"
    first_line = (
        f"I came across your {platform} content—really enjoyed your vibe."
        if not bio else
        f"I came across your {platform} and noticed you share about {bio[:80]}."
    )

    body_lines = [
        f"Hi {display},",
        "",
        first_line,
        f"I'm reaching out from {brand_name}.",
        "",
        f"We’d love to offer you {offer_details} as a {offer_type} collab.",
        cta,
        "",
        f"Website: {site}" if site else "",
        "",
        "If you're not open to collaborations right now, just reply “no thanks” and I won’t follow up.",
        "",
        f"— {brand_name} Team",
    ]

    # Remove empty lines that came from missing site
    body = "\n".join([line for line in body_lines if line != ""]).strip()

    return {"subject": subject, "body": body}

def generate_outreach_draft(*, brand_context: Dict[str, Any], influencer: Dict[str, Any], offer: Dict[str, Any]) -> Dict[str, Any]:
    """
    Returns:
      dict with at least: { "subject": str, "body": str }

    Modes:
      - LLM_MODE=mock (default) -> returns mock content
      - LLM_MODE=openai + OPENAI_API_KEY set -> uses OpenAI (later)
    """
    mode = os.getenv("LLM_MODE", "mock").lower().strip()

    # Default to mock unless explicitly told otherwise AND key exists.
    if mode != "openai" or not os.getenv("OPENAI_API_KEY"):
        return _mock_outreach(brand_context, influencer, offer)

    # Lazy import so app can start without the openai package/key during development.
    from openai import OpenAI

    client = OpenAI()

    # Keep it simple for now; later you can enforce JSON schema.
    prompt = f"""
Brand: {brand_context}
Influencer: {influencer}
Offer: {offer}

Write a concise outreach email.
- Be truthful: only reference details present in Influencer data.
- Do not mention trademarks.
- Include a clear next step and an opt-out line.
Return:
Subject: ...
Body: ...
""".strip()

    resp = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-5.2-mini"),
        input=prompt,
    )

    text = (resp.output_text or "").strip()

    # Very basic parsing fallback (you can improve later)
    subject = f"Collab idea for {influencer.get('display_name') or influencer.get('handle')}"
    body = text

    return {"subject": subject, "body": body}


def generate_followup_draft(*, brand_context: Dict[str, Any], influencer: Dict[str, Any], offer: Dict[str, Any]) -> Dict[str, Any]:
    """
    Follow-up draft (same mode logic as initial drafts).
    Returns dict with {subject, body}.
    """
    # Reuse your existing mode behavior by calling generate_outreach_draft if you want,
    # but better to make followups distinct.
    mode = os.getenv("LLM_MODE", "mock").lower().strip()

    # MOCK follow-up (no key required)
    if mode != "openai" or not os.getenv("OPENAI_API_KEY"):
        brand_name = (brand_context or {}).get("brand_name", "Hello To Natural")
        handle = influencer.get("handle") or "there"
        display = influencer.get("display_name") or handle
        offer_details = (offer or {}).get("details", "a product set")
        offer_type = (offer or {}).get("type", "gifted")
        cta = (offer or {}).get("cta", "If you're open, reply with your email + shipping info.")

        subject = f"Quick follow-up, {display} ✨"
        body = "\n".join([
            f"Hi {display},",
            "",
            "Just following up in case my earlier note got buried.",
            f"We’d still love to offer you {offer_details} as a {offer_type} collab.",
            cta,
            "",
            "If you’re not open right now, just reply “no thanks” and I’ll close this out.",
            "",
            f"— {brand_name} Team",
        ]).strip()

        return {"subject": subject, "body": body}

    # OPENAI mode (later)
    from openai import OpenAI
    client = OpenAI()

    prompt = f"""
Brand: {brand_context}
Influencer: {influencer}
Offer: {offer}

Write a short, polite follow-up email.
- Assume a prior outreach email was sent a few days ago.
- Be truthful; only reference what we know.
- Include opt-out.
Return:
Subject: ...
Body: ...
""".strip()

    resp = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-5.2-mini"),
        input=prompt,
    )

    text = (resp.output_text or "").strip()
    subject = f"Quick follow-up, {influencer.get('display_name') or influencer.get('handle')}"
    return {"subject": subject, "body": text}
