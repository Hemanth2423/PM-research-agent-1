from __future__ import annotations
"""Label harmonization agent: merge near-duplicate cluster labels across batches."""
import json
import re
import logging
import anthropic

logger = logging.getLogger(__name__)

HARMONIZATION_SYSTEM_PROMPT = """You are merging duplicate cluster labels for a product feedback analysis pipeline.

Below is a JSON object mapping product_area to a list of cluster labels. Many labels
describe the same issue but use different wording.

For each product_area, merge labels that refer to the SAME underlying problem into one
canonical label. Pick the clearest, most concise label as the canonical one.

Return a JSON object: {"label_map": {"original_label": "canonical_label", ...}}
- If a label is already canonical (no merge needed), you can omit it from the map.
- Only map labels that genuinely describe the same issue. Do NOT over-merge distinct problems.
- The canonical label should be 5-8 words, lowercase, descriptive."""


def run_harmonization_agent(
    pain_points: list[dict],
    client: anthropic.Anthropic,
) -> tuple[list[dict], dict]:
    """
    Run harmonization to merge near-duplicate cluster labels.
    Returns (harmonized_pain_points, agent_log).
    """
    # Build area->labels mapping
    area_labels: dict[str, list[str]] = {}
    for pp in pain_points:
        area = pp.get("product_area", "Platform")
        label = pp.get("cluster_label", "").lower().strip()
        if area not in area_labels:
            area_labels[area] = []
        if label and label not in area_labels[area]:
            area_labels[area].append(label)

    # Only call Claude if there's something to harmonize
    total_labels = sum(len(v) for v in area_labels.values())
    if total_labels == 0:
        return pain_points, {"agent": "harmonization", "skipped": True}

    user_message = json.dumps(area_labels, indent=2)

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=HARMONIZATION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:
        logger.error(f"Harmonization agent failed: {e}")
        return pain_points, {"agent": "harmonization", "error": str(e)}

    raw_content = response.content[0].text if response.content else ""

    try:
        text = raw_content.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text)
        label_map = result.get("label_map", {})
    except Exception as e:
        logger.error(f"Harmonization parse failed: {e}")
        label_map = {}

    # Apply label map to pain points
    harmonized = []
    merges_applied = 0
    for pp in pain_points:
        new_pp = dict(pp)
        original = pp.get("cluster_label", "").lower().strip()
        if original in label_map:
            new_pp["cluster_label"] = label_map[original]
            merges_applied += 1
        harmonized.append(new_pp)

    agent_log = {
        "agent": "harmonization",
        "model": "claude-haiku-4-5-20251001",
        "total_labels_seen": total_labels,
        "merges_applied": merges_applied,
        "tokens_used": response.usage.input_tokens + response.usage.output_tokens,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }

    logger.info(f"Harmonization: {merges_applied} label merges applied")
    return harmonized, agent_log
