from __future__ import annotations
"""Tavily search tool for real-time validation."""
import os
import logging
import requests

logger = logging.getLogger(__name__)

TAVILY_API_URL = "https://api.tavily.com/search"


def tavily_search(query: str, max_results: int = 5) -> list[dict]:
    """Search the web via Tavily API. Returns list of {title, url, content} dicts."""
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        logger.warning("TAVILY_API_KEY not set — skipping search")
        return []

    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "basic",
        "max_results": max_results,
        "include_answer": False,
    }

    try:
        resp = requests.post(TAVILY_API_URL, json=payload, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", "")[:800],
            }
            for r in data.get("results", [])
        ]
    except Exception as e:
        logger.error(f"Tavily search failed: {e}")
        return []
