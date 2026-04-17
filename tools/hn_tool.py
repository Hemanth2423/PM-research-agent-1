from __future__ import annotations
"""Hacker News tool using Algolia search_by_date API."""
import requests
from datetime import datetime, timedelta, timezone
import logging

logger = logging.getLogger(__name__)

HN_ALGOLIA_URL = "https://hn.algolia.com/api/v1/search_by_date"

_DEFAULT_QUERIES = [
    {"query": "Notion",                   "intent": "brand_general",  "weight": 0.60},
    {"query": "Notion collaboration",     "intent": "feature_collab", "weight": 0.75},
    {"query": "Notion database problems", "intent": "pain_direct",    "weight": 0.85},
    {"query": "Notion alternatives",      "intent": "competitive",    "weight": 0.80},
    {"query": "Notion user feedback",     "intent": "pain_general",   "weight": 0.70},
    {"query": "Notion offline sync",      "intent": "pain_direct",    "weight": 0.90},
    {"query": "Notion AI limitations",    "intent": "pain_direct",    "weight": 0.88},
]


def fetch_hn_items(queries: list | str | None = None, lookback_days: int = 60, hits_per_page: int = 30) -> list[dict]:
    """Fetch HN stories and comments for multiple queries within lookback_days.

    Args:
        queries: list[dict] with {query, intent, weight}, list[str] (legacy), or None (uses defaults).
        lookback_days: Days to look back in HN history.
        hits_per_page: Results per query.

    Returns:
        Deduplicated items across all queries, each tagged with query_weight.
    """
    # Normalise to list[dict] regardless of input format
    if queries is None:
        query_configs = _DEFAULT_QUERIES
    elif isinstance(queries, str):
        query_configs = [{"query": queries, "intent": "custom", "weight": 1.0}]
    elif isinstance(queries, list) and queries and isinstance(queries[0], dict):
        query_configs = queries   # already list[dict]
    else:
        # plain list[str] — backward compat
        query_configs = [{"query": q, "intent": "custom", "weight": 1.0} for q in queries]

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    cutoff_ts = int(cutoff.timestamp())

    items = []
    seen_ids: set[str] = set()

    for qcfg in query_configs:
        query = qcfg["query"]
        query_weight = float(qcfg.get("weight", 1.0))

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
                "query_weight": query_weight,
                "engagement": {
                    "upvotes": hit.get("points"),
                    "downvotes": None,
                    "star_rating": None,
                    "helpful_votes": hit.get("num_comments"),
                },
            })

        logger.info(f"HN: fetched items for query='{query}' (weight={query_weight})")

    logger.info(f"HN: total {len(items)} deduplicated items across {len(query_configs)} queries")
    return items
