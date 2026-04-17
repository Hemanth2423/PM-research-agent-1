from __future__ import annotations
"""Synthesis agent: extract pain points and classify them."""
import json
import re
import logging
import anthropic

logger = logging.getLogger(__name__)

SYNTHESIS_SYSTEM_PROMPT = """You are a product analyst extracting user pain points from feedback about Notion.

For each item, extract ONE OR MORE distinct pain points. Each pain point must be
classified into exactly one primary product area.

Product areas (use EXACTLY these strings):
["Docs & Editor", "Databases", "Wikis & Knowledge Base", "Projects & Tasks",
 "Notion AI", "Collaboration", "Integrations", "Mobile", "Admin & Security", "Platform"]

"Platform" is ONLY for issues that span 3+ product areas. Do not default to it.

For each pain point you extract, return:
{
  "source_platform_id": "the platform_id of the source item",
  "pain_point_text": "a concise 1-2 sentence description of the specific pain point",
  "cluster_label": "short 5-8 word canonical label for grouping similar complaints",
  "product_area": "one of the product areas above",
  "classification_confidence": 0.0-1.0,
  "alternate_area": "second most likely product area or null",
  "alternate_confidence": 0.0-1.0 or null,
  "severity": "low|medium|high|critical"
}

Rules:
- One source item CAN produce multiple pain points if it mentions distinct issues.
- Be specific: "database sorting limited to single column" not "databases have issues".
- cluster_label: A short, reusable label that groups similar complaints together.
  Use the SAME cluster_label for pain points describing the same underlying issue.
  Examples: "mobile app slow performance", "offline mode unreliable",
  "AI hallucination in summaries", "database multi-column sorting missing".
  Do NOT use unique or overly specific labels. Two complaints about the same problem
  MUST share the same label.
- classification_confidence: 0.9+ = very clear fit, 0.75-0.9 = good fit, <0.75 = uncertain.
- severity: critical = data loss/security, high = blocks workflow, medium = annoying,
  low = nice-to-have.
- Do NOT hallucinate. Only extract pain points explicitly stated in the text.
- Do NOT count, rank, or sort. Just extract and classify.

Return a JSON array of pain points. No commentary."""


def run_synthesis_agent(
    batches: list[list[dict]],
    client: anthropic.Anthropic,
    confidence_threshold: float = 0.75,
) -> tuple[list[dict], list[dict], dict]:
    """
    Run synthesis agent on all batches.
    Returns (pain_points, flagged_items, agent_log).
    """
    all_pain_points = []
    flagged_items = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_extracted = 0

    for i, batch in enumerate(batches):
        logger.info(f"Synthesis agent: processing batch {i+1}/{len(batches)} ({len(batch)} items)")

        user_message = json.dumps(batch, indent=2)

        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=8192,
                system=SYNTHESIS_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
        except Exception as e:
            logger.error(f"Synthesis agent batch {i+1} failed: {e}")
            continue

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        raw_content = response.content[0].text if response.content else ""

        try:
            text = raw_content.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            pain_points = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r'\[.*\]', raw_content, re.DOTALL)
            if match:
                try:
                    pain_points = json.loads(match.group())
                except Exception:
                    continue
            else:
                continue

        if not isinstance(pain_points, list):
            continue

        for pp in pain_points:
            total_extracted += 1
            conf = pp.get("classification_confidence", 0)
            if conf < confidence_threshold:
                flagged_items.append({
                    "pain_point_text": pp.get("pain_point_text", ""),
                    "classification_confidence": conf,
                    "source_platform_id": pp.get("source_platform_id", ""),
                })
            else:
                all_pain_points.append(pp)

    agent_log = {
        "agent": "synthesis",
        "model": "claude-sonnet-4-6",
        "input_item_count": sum(len(b) for b in batches),
        "output_item_count": len(all_pain_points),
        "discarded_low_confidence": len(flagged_items),
        "total_pain_points_extracted": total_extracted,
        "batch_count": len(batches),
        "tokens_used": total_input_tokens + total_output_tokens,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "notes": f"{len(flagged_items)} items below {confidence_threshold} confidence threshold — moved to flagged_items",
    }

    logger.info(f"Synthesis agent done: {len(all_pain_points)} pain points, {len(flagged_items)} flagged")
    return all_pain_points, flagged_items, agent_log
