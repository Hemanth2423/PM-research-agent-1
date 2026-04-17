from __future__ import annotations
"""Firecrawl tool for scraping G2 reviews and changelogs."""
import os
import re
import logging
import requests
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

FIRECRAWL_BASE = "https://api.firecrawl.dev/v1"

NOTION_CHANGELOG_URL = "https://www.notion.so/releases"
G2_NOTION_URL = "https://www.g2.com/products/notion/reviews"

# Credit budget per run. Lower this if you are running low on Firecrawl credits.
FIRECRAWL_BUDGET = 7

# Ordered scrape targets with priority and expected relevance.
# Targets with skip_reason set are never scraped (e.g. WAF-blocked sites).
SCRAPE_TARGETS = [
    {
        "name": "Notion Changelog",
        "url": NOTION_CHANGELOG_URL,
        "type": "own_changelog",
        "priority": 1,
        "expected_relevance": 1.00,
        "credits": 1,
        "skip_reason": None,
        "wait_for": 3000,
    },
    {
        "name": "G2 Reviews",
        "url": G2_NOTION_URL,
        "type": "review_site",
        "priority": 2,
        "expected_relevance": 0.90,
        "credits": 1,
        "skip_reason": "WAF-blocked (Datadome)",
        "wait_for": 5000,
    },
    {
        "name": "Obsidian",
        "url": "https://obsidian.md/changelog",
        "type": "competitor_changelog",
        "priority": 3,
        "expected_relevance": 0.85,
        "credits": 1,
        "skip_reason": None,
        "wait_for": 2000,
    },
    {
        "name": "Confluence",
        "url": "https://www.atlassian.com/blog/confluence",
        "type": "competitor_changelog",
        "priority": 4,
        "expected_relevance": 0.80,
        "credits": 1,
        "skip_reason": None,
        "wait_for": 2000,
    },
    {
        "name": "Coda",
        "url": "https://coda.io/changelog",
        "type": "competitor_changelog",
        "priority": 5,
        "expected_relevance": 0.75,
        "credits": 1,
        "skip_reason": None,
        "wait_for": 2000,
    },
    {
        "name": "Craft",
        "url": "https://www.craft.do/updates",
        "type": "competitor_changelog",
        "priority": 6,
        "expected_relevance": 0.65,
        "credits": 1,
        "skip_reason": None,
        "wait_for": 2000,
    },
    {
        "name": "Google Docs",
        "url": "https://workspace.google.com/whatsnew",
        "type": "competitor_changelog",
        "priority": 7,
        "expected_relevance": 0.55,
        "credits": 1,
        "skip_reason": None,
        "wait_for": 2000,
    },
    {
        "name": "Mem.ai",
        "url": "https://mem.ai/changelog",
        "type": "competitor_changelog",
        "priority": 8,
        "expected_relevance": 0.45,
        "credits": 1,
        "skip_reason": None,
        "wait_for": 2000,
    },
]


def select_scrape_targets(budget: int = FIRECRAWL_BUDGET) -> list[dict]:
    """Return highest-priority scrape targets that fit within the credit budget.

    Blocked targets (skip_reason set) are always excluded.
    Remaining targets are selected in priority order until budget is exhausted.
    """
    eligible = sorted(
        [t for t in SCRAPE_TARGETS if not t["skip_reason"]],
        key=lambda t: t["priority"],
    )
    selected, remaining = [], budget
    for target in eligible:
        if target["credits"] <= remaining:
            selected.append(target)
            remaining -= target["credits"]
        if remaining <= 0:
            break

    blocked = [t["name"] for t in SCRAPE_TARGETS if t["skip_reason"]]
    logger.info(
        f"Firecrawl: {len(selected)} targets selected within {budget}-credit budget "
        f"(skipped blocked: {blocked})"
    )
    return selected


def _firecrawl_scrape(url: str, wait_for: int = 2000) -> str | None:
    """Scrape a URL via Firecrawl and return markdown content."""
    api_key = os.getenv("FIRECRAWL_API_KEY")
    if not api_key:
        logger.warning("FIRECRAWL_API_KEY not set — skipping scrape")
        return None

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "url": url,
        "formats": ["markdown"],
        "waitFor": wait_for,
    }

    try:
        resp = requests.post(f"{FIRECRAWL_BASE}/scrape", json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("markdown", "")
    except Exception as e:
        logger.error(f"Firecrawl scrape failed for {url}: {e}")
        return None


def _parse_g2_reviews(markdown: str, lookback_days: int = 60) -> list[dict]:
    """Parse G2 review markdown into structured items."""
    if not markdown:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    items = []

    # Split on review boundaries
    review_blocks = re.split(r'(?=###?\s)', markdown)

    review_count = 0
    for block in review_blocks:
        if "What do you like best" not in block and "What do you dislike" not in block:
            continue

        # Extract date
        date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', block)
        if date_match:
            try:
                review_date = datetime.strptime(date_match.group(1), "%m/%d/%Y").replace(tzinfo=timezone.utc)
                if review_date < cutoff:
                    continue
                date_str = review_date.strftime("%Y-%m-%d")
            except ValueError:
                date_str = ""
        else:
            date_str = ""

        # Extract star rating
        star_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:out of\s*)?(?:/\s*)?5\s*stars?', block, re.I)
        star_rating = float(star_match.group(1)) if star_match else None

        # Extract company size
        size_match = re.search(r'(?:company size|employees?).*?(\d+)', block, re.I)
        if size_match:
            emp_count = int(size_match.group(1))
            if emp_count < 50:
                user_segment = "startup"
            elif emp_count < 500:
                user_segment = "mid_market"
            else:
                user_segment = "enterprise"
        else:
            user_segment = "unknown"

        # Extract review text
        likes_match = re.search(r'What do you like best[^?]*\?[^\n]*\n(.*?)(?=What do you dislike|$)', block, re.S)
        dislikes_match = re.search(r'What do you dislike[^?]*\?[^\n]*\n(.*?)(?=###|$)', block, re.S)

        likes = likes_match.group(1).strip()[:500] if likes_match else ""
        dislikes = dislikes_match.group(1).strip()[:500] if dislikes_match else ""

        raw_text = ""
        if likes:
            raw_text += f"Likes: {likes}\n"
        if dislikes:
            raw_text += f"Dislikes: {dislikes}"
        raw_text = raw_text.strip()

        if not raw_text:
            continue

        review_count += 1
        platform_id = f"g2_review_{review_count}_{date_str.replace('-', '') or 'unknown'}"

        items.append({
            "source": "G2",
            "url": G2_NOTION_URL,
            "platform_id": platform_id,
            "date": date_str,
            "raw_text": raw_text[:1500],
            "star_rating": star_rating,
            "user_segment": user_segment,
            "engagement": {
                "upvotes": None,
                "downvotes": None,
                "star_rating": star_rating,
                "helpful_votes": None,
            },
        })

    logger.info(f"G2: parsed {len(items)} reviews")
    return items


def fetch_g2_reviews(lookback_days: int = 60) -> list[dict]:
    """Fetch and parse G2 reviews for Notion."""
    markdown = _firecrawl_scrape(G2_NOTION_URL, wait_for=5000)
    if not markdown:
        return []
    # G2 uses Datadome WAF — detect blocked response
    if len(markdown) < 200 and (
        "enable js" in markdown.lower()
        or "ad blocker" in markdown.lower()
        or "captcha" in markdown.lower()
    ):
        logger.warning("G2 scrape blocked by WAF — skipping (0 reviews)")
        return []
    return _parse_g2_reviews(markdown, lookback_days)


def fetch_notion_changelog(budget: int | None = None) -> str:
    """Fetch Notion's own changelog as markdown.

    Args:
        budget: If provided, checks whether Notion Changelog is within the budget
                before scraping. Pass None to always scrape (legacy behaviour).
    """
    if budget is not None:
        targets = select_scrape_targets(budget)
        if not any(t["name"] == "Notion Changelog" for t in targets):
            logger.info("Notion Changelog skipped — credit budget exhausted")
            return ""
    markdown = _firecrawl_scrape(NOTION_CHANGELOG_URL, wait_for=3000)
    return markdown or ""


def fetch_competitor_changelogs(budget: int | None = None) -> dict[str, str]:
    """Fetch competitor changelogs within the credit budget.

    Args:
        budget: Credits available for competitor scrapes. If None, scrapes all
                non-blocked competitors (legacy behaviour).

    Returns:
        Dict of competitor_name -> markdown content.
    """
    if budget is not None:
        all_targets = select_scrape_targets(budget)
        competitor_targets = [t for t in all_targets if t["type"] == "competitor_changelog"]
    else:
        competitor_targets = [
            t for t in SCRAPE_TARGETS
            if t["type"] == "competitor_changelog" and not t["skip_reason"]
        ]

    results = {}
    for target in competitor_targets:
        logger.info(f"Fetching {target['name']} changelog...")
        content = _firecrawl_scrape(target["url"], wait_for=target.get("wait_for", 2000))
        results[target["name"]] = content or ""
    return results
