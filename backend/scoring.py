from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional, Tuple
import re


# Tune these for Hello To Natural
KEYWORDS = {
    # High intent / brand-aligned
    "natural": 4,
    "holistic": 4,
    "herbal": 4,
    "plant based": 4,
    "plant-based": 4,
    "vegan": 3,
    "wellness": 3,
    "clean beauty": 4,
    "skincare": 3,
    "body oil": 4,
    "hair": 2,
    "self care": 2,
    "self-care": 2,
    "tea": 2,
    "coffee": 2,
    "sourdough": 2,
    "organic": 3,
}

PLATFORM_SCORES = {
    "instagram": 10,
    "tiktok": 9,
    "youtube": 8,
    "pinterest": 6,
}


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def _followers_score(followers: Optional[int]) -> int:
    if followers is None:
        return 8
    if followers < 1_000:
        return 5
    if 1_000 <= followers < 3_000:
        return 10
    if 3_000 <= followers <= 50_000:
        return 20
    if 50_000 < followers <= 250_000:
        return 15
    return 10


def _engagement_score(engagement_rate: Optional[Decimal]) -> int:
    if engagement_rate is None:
        return 12

    # engagement_rate might be stored as 0.045 (4.5) OR 4.5 (percent)
    r = float(engagement_rate)
    if r > 1.0:  # treat as percent if > 1
        r = r / 100.0

    if r < 0.01:
        return 5
    if r < 0.02:
        return 15
    if r < 0.04:
        return 25
    if r < 0.08:
        return 35
    return 30


def _keyword_fit_score(bio: Optional[str]) -> Tuple[int, Dict[str, int]]:
    text = _norm(bio)
    if not text:
        return 6, {}

    hits: Dict[str, int] = {}
    points = 0

    # simple phrase matching with word boundaries when possible
    for kw, weight in KEYWORDS.items():
        kw_norm = kw.lower()
        if " " in kw_norm or "-" in kw_norm:
            found = kw_norm in text
        else:
            found = re.search(rf"\b{re.escape(kw_norm)}\b", text) is not None

        if found:
            hits[kw] = 1
            points += weight

    # Normalize points to 0–25 with a soft cap
    # max useful points ~ 20-25; cap hard at 25
    score = min(25, int(points * 1.5))  # tune multiplier as desired
    # ensure some baseline if bio exists but no keywords
    score = max(score, 8) if text else score
    return score, hits


def _platform_score(platform: Optional[str]) -> int:
    p = _norm(platform)
    return PLATFORM_SCORES.get(p, 5)


def compute_scores(
    *,
    platform: Optional[str],
    followers: Optional[int],
    engagement_rate: Optional[Decimal],
    bio: Optional[str],
    outreach_count: int = 0,
    reply_count: int = 0,
) -> Dict[str, Any]:
    """
    Returns:
      {
        brand_fit_score: Decimal(5,2),
        risk_score: Decimal(5,2),
        overall_score: Decimal(5,2),
        breakdown: dict
      }
    """

    f_score = _followers_score(followers)            # 0–20
    e_score = _engagement_score(engagement_rate)     # 0–35
    k_score, hits = _keyword_fit_score(bio)          # 0–25
    p_score = _platform_score(platform)              # 0–10

    # Responsiveness adjustment (-10..+10) — you don't have counts yet, keep neutral
    resp_adj = 0
    if outreach_count >= 2:
        rate = reply_count / max(outreach_count, 1)
        if rate == 0:
            resp_adj = -10
        elif rate < 0.10:
            resp_adj = -3
        elif rate < 0.25:
            resp_adj = 3
        else:
            resp_adj = 10

    raw_overall = f_score + e_score + k_score + p_score + resp_adj
    raw_overall = max(0, min(100, raw_overall))

    # Brand fit: focus on keyword match + platform + engagement (0-100)
    brand_fit_raw = min(100, int((k_score * 2.4) + (p_score * 3.0) + (e_score * 1.2)))
    brand_fit_raw = max(0, brand_fit_raw)

    # Risk: higher if missing email, very low engagement, huge follower count, or no bio
    risk = 0
    if engagement_rate is None:
        risk += 10
    else:
        r = float(engagement_rate)
        if r > 1.0:
            r = r / 100.0
        if r < 0.01:
            risk += 20

    if followers is None:
        risk += 10
    elif followers > 250_000:
        risk += 10

    if not _norm(bio):
        risk += 10

    risk = max(0, min(100, risk))

    breakdown = {
        "followers_score": f_score,
        "engagement_score": e_score,
        "keyword_fit_score": k_score,
        "platform_score": p_score,
        "responsiveness_adjust": resp_adj,
        "keyword_hits": hits,
        "notes": [],
    }

    # Optional notes (helps later in UI)
    if 3_000 <= (followers or 0) <= 50_000:
        breakdown["notes"].append("Ideal follower range for gifted collab")
    if k_score >= 18:
        breakdown["notes"].append("Bio strongly matches brand niche")
    if e_score >= 30:
        breakdown["notes"].append("Strong engagement rate")

    return {
        "brand_fit_score": Decimal(str(brand_fit_raw)),
        "risk_score": Decimal(str(risk)),
        "overall_score": Decimal(str(raw_overall)),
        "breakdown": breakdown,
    }
