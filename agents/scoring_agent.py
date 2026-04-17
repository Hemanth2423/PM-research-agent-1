from __future__ import annotations
"""Scoring agent: estimate engineering effort for Tier 1 themes."""
import json
import re
import logging
import anthropic

logger = logging.getLogger(__name__)

SCORING_SYSTEM_PROMPT = """You are a senior engineering manager estimating implementation effort for product features.

For each theme, estimate the engineering effort to address the pain point:
- LOW: Simple config change, UI tweak, or existing infrastructure. <1 sprint.
- MEDIUM: New feature within existing systems, moderate complexity. 1-2 sprints.
- HIGH: Significant new feature, architectural changes, or cross-team coordination. 3-5 sprints.
- VERY HIGH: Major platform change, new infrastructure, or fundamental rearchitecture. 5+ sprints.

Consider:
- Technical complexity of the fix
- Whether it requires new infrastructure or can build on existing systems
- Cross-team dependencies
- Testing and rollout complexity

Respond with a JSON array. Each element:
{
  "theme_name": "the theme name",
  "effort": "LOW|MEDIUM|HIGH|VERY HIGH",
  "reasoning": "one sentence explaining the estimate"
}

Be realistic. Do NOT default everything to MEDIUM. Consider the actual engineering
work required."""


def run_scoring_agent(
    tier1_themes: list[dict],
    client: anthropic.Anthropic,
) -> tuple[list[dict], dict]:
    """
    Estimate effort for Tier 1 themes.
    Returns (effort_estimates, agent_log).
    """
    if not tier1_themes:
        return [], {"agent": "scoring", "skipped": True}

    # Build concise theme descriptions for the prompt
    theme_descriptions = []
    for theme in tier1_themes:
        theme_descriptions.append({
            "theme_name": theme.get("theme_name", ""),
            "product_area": theme.get("product_area", ""),
            "description": "; ".join(theme.get("pain_point_texts", [])[:2]),
            "severity": theme.get("dominant_severity", "medium"),
        })

    user_message = json.dumps(theme_descriptions, indent=2)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=SCORING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:
        logger.error(f"Scoring agent failed: {e}")
        return [], {"agent": "scoring", "error": str(e)}

    raw_content = response.content[0].text if response.content else ""

    try:
        text = raw_content.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        effort_data = json.loads(text)
    except Exception as e:
        logger.error(f"Scoring agent parse failed: {e}")
        match = re.search(r'\[.*\]', raw_content, re.DOTALL)
        if match:
            try:
                effort_data = json.loads(match.group())
            except Exception:
                effort_data = []
        else:
            effort_data = []

    agent_log = {
        "agent": "scoring",
        "model": "claude-sonnet-4-6",
        "themes_scored": len(tier1_themes),
        "tokens_used": response.usage.input_tokens + response.usage.output_tokens,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }

    logger.info(f"Scoring agent: estimated effort for {len(effort_data)} themes")
    return effort_data, agent_log
