from __future__ import annotations
"""Hacker News tool using Algolia search_by_date API."""
import requests
from datetime import datetime, timedelta, timezone
import logging

logger = logging.getLogger(__name__)

HN_ALGOLIA_URL = "https://hn.algolia.com/api/v1/search_by_date"


def fetch_hn_items(queries: list[str] | str | None = None, lookback_days: int = 60, hits_per_page: int = 30) -> list[dict]:
    """Fetch HN stories and comments for multiple queries within lookback_days.

    Args:
        queries: List of query strings, or single query string. If None, uses default queries.
        lookback_days: Days to look back in HN history
        hits_per_page: Results per query

    Returns:
        List of deduplicated items across all queries
    """
    # Handle default/legacy single query case
    if queries is None:
        queries = [
            "Notion",
            "Notion collaboration",
            "Notion database problems",
            "Notion alternatives",
            "Notion feedback",
            "Notion offline sync",
            "Notion AI",
        ]
    elif isinstance(queries, str):
        queries = [queries]

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    cutoff_ts = int(cutoff.timestamp())

    items = []
    seen_ids = set()  # Deduplicate across queries

    for query in queries:
        params = {
            "query": query,
            "tags": "(story,comment)",
            "numericFilters": f"created_at_i>{cutoff_ts}",
            "hitsPerPage": hits_per_page,
        }

        try:
            resp = requests.get(HN_ALGOLIA_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"HN fetch failed for query '{query}': {e}")
            continue

        for hit in data.get("hits", []):
            obj_id = hit.get("objectID", "")
            if obj_id in seen_ids:
                continue
            seen_ids.add(obj_id)

            text = hit.get("story_text") or hit.get("comment_text") or hit.get("title") or ""
            if not text:
                continue

            created_at = hit.get("created_at", "")
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={obj_id}"
            platform_id = f"hn_{obj_id}"

            items.append({
                "source": "HN",
                "url": url,
                "platform_id": platform_id,
                "date": created_at[:10] if created_at else "",
                "raw_text": text[:2000],
                "star_rating": None,
                "user_segment": "unknown",
                "engagement": {
                    "upvotes": hit.get("points"),
                    "downvotes": None,
                    "star_rating": None,
                    "helpful_votes": hit.get("num_comments"),
                },
            })

        logger.info(f"HN: fetched items for query='{query}'")

    logger.info(f"HN: total {len(items)} deduplicated items across {len(queries)} queries")
    return items
