from __future__ import annotations
"""Batch chunker for Claude agent calls."""
import json
import logging

logger = logging.getLogger(__name__)

MAX_BATCH_CHARS = 6000
COMPRESSED_FIELDS = ("platform_id", "source", "cleaned_text", "user_segment")


def compress_item(item: dict) -> dict:
    """Compress an item to only the fields Claude needs."""
    return {
        "platform_id": item.get("platform_id", ""),
        "source": item.get("source", ""),
        "cleaned_text": item.get("cleaned_text") or item.get("raw_text", "")[:300],
        "user_segment": item.get("user_segment", "unknown"),
    }


def batch_items(items: list[dict], max_chars: int = MAX_BATCH_CHARS) -> list[list[dict]]:
    """Split items into batches that fit within max_chars when JSON-serialized."""
    batches = []
    current_batch = []
    current_chars = 0

    for item in items:
        compressed = compress_item(item)
        item_json = json.dumps(compressed)
        item_chars = len(item_json) + 2  # +2 for comma/newline

        if current_batch and current_chars + item_chars > max_chars:
            batches.append(current_batch)
            current_batch = [compressed]
            current_chars = item_chars
        else:
            current_batch.append(compressed)
            current_chars += item_chars

    if current_batch:
        batches.append(current_batch)

    logger.info(f"Chunker: {len(items)} items → {len(batches)} batches")
    return batches
