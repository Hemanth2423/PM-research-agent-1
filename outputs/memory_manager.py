from __future__ import annotations
"""Manage Claude memory file — append run summaries."""
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

MEMORY_PATH = Path(__file__).parent.parent / "data" / "memory.md"


def update_memory(run_data: dict) -> None:
    """Append a summary of this run to data/memory.md."""
    run_id = run_data.get("run_id", "unknown")
    stats = run_data.get("pipeline_stats", {})
    themes = run_data.get("themes", [])

    tier1 = [t for t in themes if t.get("tier") == 1]
    tier2 = [t for t in themes if t.get("tier") == 2]

    lines = []
    lines.append(f"\n## Run: {run_id}")
    lines.append(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}  ")
    lines.append(f"**Items processed:** {stats.get('total_items_fetched', 0)} → {stats.get('items_after_research', 0)} relevant  ")
    lines.append(f"**Themes:** {stats.get('themes_count', 0)} total, Tier1={len(tier1)}, Tier2={len(tier2)}")
    lines.append("")

    if tier1:
        lines.append("**Top Tier 1 Issues:**")
        for t in tier1[:3]:
            rice = t.get("rice_score", t.get("confidence_score", "-"))
            lines.append(f"- {t.get('theme_name', '').title()} (RICE: {rice}, Area: {t.get('product_area', '-')})")
        lines.append("")

    summary = "\n".join(lines)

    # Load existing memory
    try:
        existing = MEMORY_PATH.read_text()
        # Replace "_No runs yet._" if present
        existing = existing.replace("_No runs yet._", "")
    except FileNotFoundError:
        existing = "# PM Agent Memory\n\n## Run History\n"

    MEMORY_PATH.write_text(existing + summary)
    logger.info(f"Memory updated with run {run_id}")


def read_memory() -> str:
    """Read the current memory file."""
    try:
        return MEMORY_PATH.read_text()
    except FileNotFoundError:
        return ""
