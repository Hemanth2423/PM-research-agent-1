from __future__ import annotations
"""Research agent: binary relevance filtering using claude-haiku."""
import json
import logging
import anthropic

logger = logging.getLogger(__name__)

RESEARCH_SYSTEM_PROMPT = """You are a research analyst filtering user feedback for Notion-related content.

For each item, determine:
1. Is this about Notion (the productivity tool)? If not, mark not_relevant.
2. Extract: user_segment (startup/mid_market/enterprise/power_user/individual/unknown),
   cleaned_text (the core complaint or feedback, max 300 chars).

Return JSON array. Each element:
{
  "platform_id": "the original platform_id",
  "is_relevant": true/false,
  "cleaned_text": "concise summary of the feedback",
  "user_segment": "one of: startup, mid_market, enterprise, power_user, individual, unknown",
  "relevance_reasoning": "one sentence why relevant or not"
}

Rules:
- "Notion" must refer to the productivity/workspace tool, not the English word "notion"
- Be aggressive about filtering: marketing content, unrelated mentions, bot posts → not_relevant
- Do NOT analyze or classify pain points — just filter and summarize
- Do NOT count or rank anything"""


def run_research_agent(batches: list[list[dict]], client: anthropic.Anthropic) -> tuple[list[dict], dict]:
    """Run research agent on all batches. Returns (relevant_items, agent_log)."""
    all_relevant = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_discarded = 0
    total_processed = 0

    for i, batch in enumerate(batches):
        logger.info(f"Research agent: processing batch {i+1}/{len(batches)} ({len(batch)} items)")

        user_message = json.dumps(batch, indent=2)

        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=4096,
                system=RESEARCH_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
        except Exception as e:
            logger.error(f"Research agent batch {i+1} failed: {e}")
            continue

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        raw_content = response.content[0].text if response.content else ""

        # Parse JSON from response
        try:
            # Strip markdown code fences if present
            text = raw_content.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            filtered = json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Research agent batch {i+1} JSON parse failed: {e}")
            # Try to extract JSON array from text
            import re
            match = re.search(r'\[.*\]', raw_content, re.DOTALL)
            if match:
                try:
                    filtered = json.loads(match.group())
                except Exception:
                    continue
            else:
                continue

        if not isinstance(filtered, list):
            logger.error(f"Research agent batch {i+1}: expected list, got {type(filtered)}")
            continue

        for item in filtered:
            total_processed += 1
            if item.get("is_relevant"):
                all_relevant.append(item)
            else:
                total_discarded += 1

    agent_log = {
        "agent": "research",
        "model": "claude-haiku-4-5-20251001",
        "input_item_count": sum(len(b) for b in batches),
        "output_item_count": len(all_relevant),
        "discarded_count": total_discarded,
        "batch_count": len(batches),
        "tokens_used": total_input_tokens + total_output_tokens,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
    }

    logger.info(f"Research agent done: {len(all_relevant)} relevant, {total_discarded} discarded")
    return all_relevant, agent_log
