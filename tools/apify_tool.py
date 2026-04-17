from __future__ import annotations
"""Apify tool for Reddit, App Store, and Play Store scraping."""
import os
import logging
import requests
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

APIFY_BASE = "https://api.apify.com/v2"
MAX_ITEMS = 50


def _run_apify_actor(actor_id: str, run_input: dict) -> list[dict]:
    """Run an Apify actor and return the dataset items."""
    api_key = os.getenv("APIFY_API_KEY")
    if not api_key:
        logger.warning("APIFY_API_KEY not set — skipping actor")
        return []

    headers = {"Content-Type": "application/json"}
    url = f"{APIFY_BASE}/acts/{actor_id}/runs?token={api_key}"

    try:
        # Start the run
        resp = requests.post(url, json=run_input, headers=headers, timeout=30)
        resp.raise_for_status()
        run_id = resp.json()["data"]["id"]

        # Wait for completion (poll)
        import time
        for _ in range(30):
            time.sleep(5)
            status_resp = requests.get(
                f"{APIFY_BASE}/actor-runs/{run_id}?token={api_key}", timeout=15
            )
            status_resp.raise_for_status()
            status = status_resp.json()["data"]["status"]
            if status in ("SUCCEEDED", "FAILED", "ABORTED"):
                break

        if status != "SUCCEEDED":
            logger.warning(f"Apify actor {actor_id} finished with status: {status}")
            return []

        # Fetch dataset
        dataset_id = status_resp.json()["data"]["defaultDatasetId"]
        items_resp = requests.get(
            f"{APIFY_BASE}/datasets/{dataset_id}/items?token={api_key}&limit={MAX_ITEMS}",
            timeout=30,
        )
        items_resp.raise_for_status()
        return items_resp.json()

    except Exception as e:
        logger.error(f"Apify actor {actor_id} failed: {e}")
        return []


def fetch_reddit_posts(subreddits: list[str] | None = None, lookback_days: int = 60) -> list[dict]:
    """Fetch Reddit posts about Notion."""
    if subreddits is None:
        subreddits = ["r/Notion", "r/productivity"]

    run_input = {
        "startUrls": [{"url": f"https://www.reddit.com/{sub}/search/?q=notion&sort=new"} for sub in subreddits],
        "maxItems": MAX_ITEMS,
        "searchMode": True,
    }

    raw_items = _run_apify_actor("trudax~reddit-scraper", run_input)

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    items = []

    for raw in raw_items:
        created_utc = raw.get("createdAt") or raw.get("created_utc", "")
        try:
            if isinstance(created_utc, (int, float)):
                item_date = datetime.fromtimestamp(created_utc, tz=timezone.utc)
            else:
                item_date = datetime.fromisoformat(str(created_utc).replace("Z", "+00:00"))
            if item_date < cutoff:
                continue
            date_str = item_date.strftime("%Y-%m-%d")
        except Exception:
            date_str = ""

        text = raw.get("selftext") or raw.get("body") or raw.get("title") or ""
        if not text or text == "[deleted]" or text == "[removed]":
            continue

        items.append({
            "source": "Reddit",
            "url": raw.get("url", ""),
            "platform_id": f"reddit_{raw.get('id', '')}",
            "date": date_str,
            "raw_text": text[:1500],
            "star_rating": None,
            "user_segment": "unknown",
            "engagement": {
                "upvotes": raw.get("score") or raw.get("ups"),
                "downvotes": raw.get("downs"),
                "star_rating": None,
                "helpful_votes": raw.get("num_comments"),
            },
        })

    logger.info(f"Reddit: fetched {len(items)} posts")
    return items


def fetch_app_store_reviews(lookback_days: int = 60) -> list[dict]:
    """Fetch iOS App Store reviews for Notion."""
    run_input = {
        "appId": "1232780281",
        "country": "us",
        "maxReviews": MAX_ITEMS,
    }

    raw_items = _run_apify_actor("epctex~app-store-scraper", run_input)

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    items = []

    for raw in raw_items:
        date_str_raw = raw.get("date") or raw.get("updated", "")
        try:
            item_date = datetime.fromisoformat(str(date_str_raw).replace("Z", "+00:00"))
            if item_date < cutoff:
                continue
            date_str = item_date.strftime("%Y-%m-%d")
        except Exception:
            date_str = ""

        text = raw.get("review") or raw.get("body") or ""
        if not text:
            continue

        star_rating = raw.get("score") or raw.get("rating")

        items.append({
            "source": "App Store",
            "url": raw.get("url", "https://apps.apple.com/app/notion/id1232780281"),
            "platform_id": f"appstore_{raw.get('id', '')}",
            "date": date_str,
            "raw_text": text[:1500],
            "star_rating": float(star_rating) if star_rating else None,
            "user_segment": "individual",
            "engagement": {
                "upvotes": None,
                "downvotes": None,
                "star_rating": float(star_rating) if star_rating else None,
                "helpful_votes": None,
            },
        })

    logger.info(f"App Store: fetched {len(items)} reviews")
    return items


def fetch_play_store_reviews(lookback_days: int = 60) -> list[dict]:
    """Fetch Google Play Store reviews for Notion."""
    run_input = {
        "packageName": "notion.id",
        "maxReviews": MAX_ITEMS,
        "language": "en",
    }

    raw_items = _run_apify_actor("epctex~google-play-scraper", run_input)

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    items = []

    for raw in raw_items:
        date_str_raw = raw.get("at") or raw.get("date") or raw.get("updated", "")
        try:
            item_date = datetime.fromisoformat(str(date_str_raw).replace("Z", "+00:00"))
            if item_date < cutoff:
                continue
            date_str = item_date.strftime("%Y-%m-%d")
        except Exception:
            date_str = ""

        text = raw.get("content") or raw.get("text") or raw.get("body") or ""
        if not text:
            continue

        star_rating = raw.get("score") or raw.get("rating")

        items.append({
            "source": "Play Store",
            "url": "https://play.google.com/store/apps/details?id=notion.id",
            "platform_id": f"playstore_{raw.get('reviewId', raw.get('id', ''))}",
            "date": date_str,
            "raw_text": text[:1500],
            "star_rating": float(star_rating) if star_rating else None,
            "user_segment": "individual",
            "engagement": {
                "upvotes": raw.get("thumbsUpCount"),
                "downvotes": None,
                "star_rating": float(star_rating) if star_rating else None,
                "helpful_votes": None,
            },
        })

    logger.info(f"Play Store: fetched {len(items)} reviews")
    return items
