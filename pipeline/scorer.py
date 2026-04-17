from __future__ import annotations
"""Deterministic scoring: z-scores, confidence, tiers, RICE/RIC."""
import math
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Tunable constants
LOOKBACK_DAYS = 60
CONFIDENCE_THRESHOLD = 0.75
SOURCE_WEIGHTS = {
    "G2": 1.4,
    "Capterra": 1.3,
    "App Store": 1.1,
    "Play Store": 1.1,
    "HN": 0.9,
    "Reddit": 0.8,
}
SOURCE_DOMINANCE_CAP = 0.40
STAR_SEVERITY = {1: 2.0, 2: 1.5, 3: 1.0, 4: 0.5, 5: 0.2}
EFFORT_WEIGHT = 0.60
RICE_RIC_DIVERGENCE_FLAG = 0.30

EFFORT_MULTIPLIER = {"LOW": 1.0, "MEDIUM": 0.75, "HIGH": 0.5, "VERY HIGH": 0.25}

# Confidence tier thresholds
TIER1_THRESHOLD = 15.0
TIER2_THRESHOLD = 8.0


def _compute_engagement_z_scores(engagement_list: list[dict]) -> list[float]:
    """Compute per-source engagement z-scores."""
    scores = []
    for eng in engagement_list:
        upvotes = eng.get("upvotes") or 0
        star = eng.get("star_rating")
        helpful = eng.get("helpful_votes") or 0
        raw_score = upvotes + helpful
        if star:
            raw_score += (5 - star) * 2
        scores.append(float(raw_score))

    if len(scores) < 2:
        return [1.0] * len(scores)

    mean = sum(scores) / len(scores)
    std = math.sqrt(sum((s - mean) ** 2 for s in scores) / len(scores))

    if std == 0:
        return [1.0] * len(scores)

    weights = []
    for s in scores:
        z = (s - mean) / std
        if z > 2.0:
            w = 2.0
        elif z > 1.5:
            w = 1.5
        elif z > 0.5:
            w = 1.1
        elif z < -1.0:
            w = 0.4
        else:
            w = 1.0
        weights.append(w)
    return weights


def _days_since(date_str: str) -> int:
    """Days between date_str (YYYY-MM-DD) and today. Returns 9999 if unparseable."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - d).days
    except Exception:
        return 9999


def compute_confidence_score(theme: dict, competitor_addressed: bool = False) -> float:
    """Compute multi-signal confidence score for a theme."""
    score = float(theme.get("unique_mention_count", 1))

    # Engagement z-scores
    eng_weights = _compute_engagement_z_scores(theme.get("engagement_weights", []))
    score += sum(eng_weights)

    # Source diversity bonus/penalty
    src_count = theme.get("source_type_count", 1)
    if src_count >= 3:
        score *= 1.5
    elif src_count == 1:
        score *= 0.5

    # Recency bonus
    latest = theme.get("latest_date", "")
    days_latest = _days_since(latest)
    if days_latest <= 30:
        score *= 1.3

    # Competitor urgency bonus
    if competitor_addressed:
        score *= 1.2

    # Staleness penalty
    oldest = theme.get("oldest_date", "")
    days_oldest = _days_since(oldest)
    if days_oldest >= 45:
        score *= 0.3

    # Source credibility (capped at 40%)
    breakdown = theme.get("source_breakdown", {})
    total_mentions = sum(breakdown.values()) or 1
    weighted_src_score = sum(
        SOURCE_WEIGHTS.get(src, 0.8) * count / total_mentions
        for src, count in breakdown.items()
    )

    # Source dominance cap
    max_share = max((c / total_mentions for c in breakdown.values()), default=0)
    source_dominance_capped = max_share > SOURCE_DOMINANCE_CAP

    score += weighted_src_score * 0.5

    return round(score, 2), source_dominance_capped


def classify_tier(confidence_score: float) -> int:
    if confidence_score >= TIER1_THRESHOLD:
        return 1
    elif confidence_score >= TIER2_THRESHOLD:
        return 2
    return 3


def compute_confidence_label(score: float) -> str:
    if score >= TIER1_THRESHOLD:
        return "VERY HIGH"
    elif score >= TIER2_THRESHOLD:
        return "HIGH"
    elif score >= 4.0:
        return "MEDIUM"
    return "LOW"


def compute_rice_score(theme: dict, effort_label: str | None = None) -> dict:
    """
    RICE = (Reach * Impact * Confidence) / Effort
    RIC  = Reach * Impact * Confidence  (no effort denominator)

    Simplified:
      Reach = unique_mention_count * source_weight_avg
      Impact = severity_multiplier
      Confidence = source_type_count factor
    """
    reach = float(theme.get("unique_mention_count", 1))
    breakdown = theme.get("source_breakdown", {})
    total = sum(breakdown.values()) or 1
    avg_src_weight = sum(
        SOURCE_WEIGHTS.get(src, 0.8) * cnt / total for src, cnt in breakdown.items()
    )
    reach *= avg_src_weight

    sev = theme.get("dominant_severity", "medium")
    severity_map = {"critical": 3.0, "high": 2.0, "medium": 1.0, "low": 0.5}
    impact = severity_map.get(sev, 1.0)

    src_count = theme.get("source_type_count", 1)
    confidence_factor = min(src_count / 3.0, 1.0)

    ric = round(reach * impact * confidence_factor, 1)

    if effort_label:
        effort_mult = EFFORT_MULTIPLIER.get(effort_label.upper(), 0.5)
        rice = round(ric * effort_mult * EFFORT_WEIGHT + ric * (1 - EFFORT_WEIGHT), 1)
    else:
        rice = ric

    divergence_pct = abs(rice - ric) / max(ric, 0.001)
    divergence_flag = divergence_pct > RICE_RIC_DIVERGENCE_FLAG

    return {
        "rice_score": rice,
        "ric_score": ric,
        "divergence_flag": divergence_flag,
        "divergence_pct": round(divergence_pct, 2),
    }


def score_themes(themes: list[dict], competitor_data: dict[str, bool]) -> list[dict]:
    """Score all themes and assign tiers."""
    scored = []
    for theme in themes:
        competitor_addressed = competitor_data.get(theme.get("theme_name", ""), False)
        confidence_score, source_dominance_capped = compute_confidence_score(theme, competitor_addressed)
        tier = classify_tier(confidence_score)
        confidence_label = compute_confidence_label(confidence_score)

        theme_scored = dict(theme)
        theme_scored.update({
            "confidence_score": confidence_score,
            "confidence_label": confidence_label,
            "tier": tier,
            "competitor_addressed": competitor_addressed,
            "source_dominance_capped": source_dominance_capped,
            "effort_label": None,
            "rice_score": None,
            "ric_score": None,
            "divergence_flag": False,
            "divergence_pct": 0.0,
            "validation_status": "UNADDRESSED",
            "validation_evidence": None,
        })
        scored.append(theme_scored)

    scored.sort(key=lambda t: t["confidence_score"], reverse=True)
    logger.info(f"Scorer: {len(scored)} themes scored. Tier1={sum(1 for t in scored if t['tier']==1)}, Tier2={sum(1 for t in scored if t['tier']==2)}, Tier3={sum(1 for t in scored if t['tier']==3)}")
    return scored


def apply_effort_scores(themes: list[dict], effort_data: list[dict]) -> list[dict]:
    """Apply effort estimates from scoring agent to Tier 1 themes."""
    effort_map = {e["theme_name"].lower().strip(): e["effort"] for e in effort_data}

    for theme in themes:
        if theme.get("tier") == 1:
            effort_label = effort_map.get(theme.get("theme_name", "").lower().strip())
            if effort_label:
                theme["effort_label"] = effort_label
                rice_data = compute_rice_score(theme, effort_label)
                theme.update(rice_data)

    return themes
