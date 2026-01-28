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


# llm.py
# import json
# from openai import OpenAI

# # client = OpenAI()

# DRAFT_SCHEMA = {
#   "type": "object",
#   "properties": {
#     "subject": {"type": "string"},
#     "body": {"type": "string"},
#     "personalization_notes": {"type": "array", "items": {"type": "string"}},
#     "followup_body": {"type": "string"}
#   },
#   "required": ["subject", "body", "personalization_notes", "followup_body"]
# }

# def generate_outreach_draft(brand_context, influencer, offer):
#     try:
#         from openai import OpenAI
#     except ModuleNotFoundError as e:
#         raise RuntimeError(
#             "openai package not installed. Run: pip install openai"
#         ) from e

#     client = OpenAI()  # ✅ only created when function is called

#     # TODO: replace with your real prompt + schema
#     response = client.responses.create(
#         model="gpt-5.2-mini",
#         input={
#             "brand_context": brand_context,
#             "influencer": influencer,
#             "offer": offer,
#             "instructions": "Write a concise outreach email."
#         }
#     )

#     return {
#         "subject": "Quick collab idea",
#         "body": response.output_text
#     }

# Orig
#
# def generate_outreach_draft(brand_context: dict, influencer: dict, offer: dict) -> dict:
#     prompt = {
#       "brand": brand_context,
#       "influencer": influencer,
#       "offer": offer,
#       "instructions": [
#         "Write a concise, warm outreach email.",
#         "Be truthful. Only reference specific details included in influencer data.",
#         "Do not mention trademarks. Use general scent descriptions.",
#         "Include a simple next step and an opt-out line."
#       ],
#       "output": "Return JSON with subject, body, personalization_notes, followup_body."
#     }

#     resp = client.responses.create(
#       model="gpt-5.2-mini",  # good for structured writing; adjust as needed
#       input=json.dumps(prompt),
#       text={"format": {"type": "json_schema", "json_schema": DRAFT_SCHEMA}}
#     )
#     return json.loads(resp.output_text)
