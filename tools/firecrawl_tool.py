from __future__ import annotations
"""Firecrawl tool for scraping G2 reviews and changelogs."""
import os
import re
import logging
import requests
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

FIRECRAWL_BASE = "https://api.firecrawl.dev/v1"

COMPETITOR_CHANGELOGS = {
    "Coda": "https://coda.io/changelog",
    "Confluence": "https://www.atlassian.com/blog/confluence",
    "Obsidian": "https://obsidian.md/changelog",
    "Craft": "https://www.craft.do/updates",
    "Google Docs": "https://workspace.google.com/whatsnew",
    "Mem.ai": "https://mem.ai/changelog",
}

NOTION_CHANGELOG_URL = "https://www.notion.so/releases"
G2_NOTION_URL = "https://www.g2.com/products/notion/reviews"


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
    if len(markdown) < 200 and ("enable js" in markdown.lower() or "ad blocker" in markdown.lower() or "captcha" in markdown.lower()):
        logger.warning("G2 scrape blocked by WAF — skipping (0 reviews)")
        return []
    return _parse_g2_reviews(markdown, lookback_days)


def fetch_notion_changelog() -> str:
    """Fetch Notion's own changelog as markdown."""
    markdown = _firecrawl_scrape(NOTION_CHANGELOG_URL, wait_for=3000)
    return markdown or ""


def fetch_competitor_changelogs() -> dict[str, str]:
    """Fetch all competitor changelogs. Returns dict of competitor_name -> markdown."""
    results = {}
    for name, url in COMPETITOR_CHANGELOGS.items():
        logger.info(f"Fetching {name} changelog...")
        content = _firecrawl_scrape(url, wait_for=2000)
        results[name] = content or ""
    return results
