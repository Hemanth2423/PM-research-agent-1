from __future__ import annotations
"""Cross-run deduplication registry (FR3/FR4)."""
import json
import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

REGISTRY_PATH = Path(__file__).parent.parent / "data" / "seen_registry.json"


def _load_registry() -> dict:
    try:
        return json.loads(REGISTRY_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_registry(registry: dict) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2))


def fingerprint_item(item: dict) -> str:
    """Compute a stable fingerprint for an item."""
    key = f"{item.get('source', '')}|{item.get('url', '')}|{item.get('platform_id', '')}"
    return hashlib.sha256(key.encode()).hexdigest()


def dedup_within_run(items: list[dict]) -> list[dict]:
    """Remove duplicates within a single run (FR3)."""
    seen = set()
    result = []
    for item in items:
        fp = fingerprint_item(item)
        if fp not in seen:
            seen.add(fp)
            result.append(item)
    removed = len(items) - len(result)
    if removed:
        logger.info(f"Within-run dedup: removed {removed} duplicates")
    return result


def dedup_cross_run(items: list[dict]) -> tuple[list[dict], int]:
    """Remove items seen in previous runs (FR4). Returns (new_items, skipped_count)."""
    registry = _load_registry()
    new_items = []
    skipped = 0

    for item in items:
        fp = fingerprint_item(item)
        if fp in registry:
            skipped += 1
        else:
            new_items.append(item)

    logger.info(f"Cross-run dedup: {skipped} items skipped (seen before), {len(new_items)} new")
    return new_items, skipped


def register_items(items: list[dict]) -> None:
    """Add processed items to the registry so future runs skip them."""
    registry = _load_registry()
    for item in items:
        fp = fingerprint_item(item)
        registry[fp] = item.get("date", "")
    _save_registry(registry)
    logger.info(f"Registry: added {len(items)} fingerprints ({len(registry)} total)")
