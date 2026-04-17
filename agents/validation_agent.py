from __future__ import annotations
"""Validation agent: check if Notion changelog addresses pain point themes."""
import json
import re
import logging
import anthropic

logger = logging.getLogger(__name__)

VALIDATION_SYSTEM_PROMPT = """You are a conservative product changelog analyst.

You are given a theme (a user pain point) and relevant changelog excerpts.
Determine whether the changelog evidence ACTUALLY addresses the pain point.

Be CONSERVATIVE:
- Mark ADDRESSED only if the changelog explicitly describes a fix or feature that
  resolves the pain point.
- Mark PARTIALLY_ADDRESSED if the changelog shows related work but the core pain
  point remains.
- Mark UNADDRESSED if there is no evidence or only tangentially related changes.

Respond with JSON:
{
  "status": "ADDRESSED|PARTIALLY_ADDRESSED|UNADDRESSED",
  "evidence": "brief quote or description from changelog, or null",
  "release_name": "release name/date if ADDRESSED, or null",
  "reasoning": "one sentence explaining your decision"
}

Do NOT guess. Do NOT hallucinate changelog entries. Only cite what is in the input."""


def _keyword_search(theme_name: str, changelog_text: str, window: int = 500) -> str | None:
    """Find a relevant excerpt from changelog text using keyword matching."""
    if not changelog_text:
        return None

    # Extract key words from theme name
    keywords = [w.lower() for w in theme_name.split() if len(w) > 3]
    if not keywords:
        return None

    text_lower = changelog_text.lower()
    for keyword in keywords:
        idx = text_lower.find(keyword)
        if idx != -1:
            start = max(0, idx - 100)
            end = min(len(changelog_text), idx + window)
            return changelog_text[start:end]

    return None


def run_validation_agent(
    themes: list[dict],
    notion_changelog: str,
    overrides: list[dict],
    client: anthropic.Anthropic,
) -> tuple[list[dict], dict]:
    """
    Validate themes against Notion changelog.
    Returns (validated_themes, agent_log).
    """
    # Build override lookup
    override_map = {}
    for ov in overrides:
        kw = ov.get("pain_point_keyword", "").lower()
        if kw:
            override_map[kw] = ov

    total_input_tokens = 0
    total_output_tokens = 0
    claude_calls = 0
    validated_themes = []

    for theme in themes:
        theme_validated = dict(theme)
        theme_name = theme.get("theme_name", "")

        # Check override
        override_match = None
        for kw, ov in override_map.items():
            if kw in theme_name.lower():
                override_match = ov
                break

        if override_match:
            status = override_match.get("status", "UNADDRESSED")
            provider = override_match.get("provided_by", "PM")
            date_ov = override_match.get("date", "")
            theme_validated["validation_status"] = status
            theme_validated["validation_evidence"] = f"[OVERRIDE by {provider} on {date_ov}]: {override_match.get('note', '')}"
            theme_validated["override_flag"] = True
            validated_themes.append(theme_validated)
            continue

        theme_validated["override_flag"] = False

        # Python keyword search first
        excerpt = _keyword_search(theme_name, notion_changelog)

        if excerpt:
            # Send to Claude for confirmation
            user_msg = json.dumps({
                "theme": theme_name,
                "product_area": theme.get("product_area", ""),
                "changelog_excerpt": excerpt,
            }, indent=2)

            try:
                response = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=512,
                    system=VALIDATION_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_msg}],
                )
                claude_calls += 1
                total_input_tokens += response.usage.input_tokens
                total_output_tokens += response.usage.output_tokens

                raw = response.content[0].text if response.content else ""
                text = raw.strip()
                if text.startswith("```"):
                    text = text.split("```")[1]
                    if text.startswith("json"):
                        text = text[4:]
                val_result = json.loads(text)

                theme_validated["validation_status"] = val_result.get("status", "UNADDRESSED")
                theme_validated["validation_evidence"] = val_result.get("evidence")
                theme_validated["validation_reasoning"] = val_result.get("reasoning")
            except Exception as e:
                logger.error(f"Validation agent call failed for '{theme_name}': {e}")
                theme_validated["validation_status"] = "UNADDRESSED"
        else:
            theme_validated["validation_status"] = "UNADDRESSED"
            theme_validated["validation_evidence"] = None

        validated_themes.append(theme_validated)

    agent_log = {
        "agent": "validation",
        "model": "claude-sonnet-4-6",
        "themes_checked": len(themes),
        "claude_calls_made": claude_calls,
        "tokens_used": total_input_tokens + total_output_tokens,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
    }

    logger.info(f"Validation: {claude_calls} Claude calls for {len(themes)} themes")
    return validated_themes, agent_log


def check_competitor_coverage(themes: list[dict], competitor_changelogs: dict[str, str]) -> dict[str, bool]:
    """
    For each theme, check if any competitor changelog mentions keywords from the theme.
    Returns dict of theme_name -> bool (True if competitor addressed it).
    """
    result = {}
    for theme in themes:
        theme_name = theme.get("theme_name", "")
        keywords = [w.lower() for w in theme_name.split() if len(w) > 3]
        addressed = False
        for comp_name, comp_text in competitor_changelogs.items():
            if not comp_text:
                continue
            text_lower = comp_text.lower()
            if any(kw in text_lower for kw in keywords):
                addressed = True
                break
        result[theme_name] = addressed
    return result
