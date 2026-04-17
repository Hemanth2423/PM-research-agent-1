"""Generate one-page executive brief."""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def generate_brief(run_data: dict) -> str:
    """Generate a one-page executive brief."""
    run_id = run_data.get("run_id", "unknown")
    stats = run_data.get("pipeline_stats", {})
    themes = run_data.get("themes", [])
    source_errors = run_data.get("source_errors", {})

    tier1 = sorted([t for t in themes if t.get("tier") == 1], key=lambda t: t.get("rice_score") or t.get("confidence_score", 0), reverse=True)
    tier2 = [t for t in themes if t.get("tier") == 2]

    total_unaddressed = sum(1 for t in themes if t.get("validation_status") == "UNADDRESSED")

    lines = []
    lines.append("NOTION PM INTELLIGENCE BRIEF")
    lines.append(f"Run: {run_id[:10]} | Sources: {stats.get('total_items_fetched', 0)} items across {stats.get('active_sources', 0)} active sources")
    lines.append("")
    lines.append("AT A GLANCE")
    lines.append(f"- {stats.get('total_items_fetched', 0)} new signals processed")
    lines.append(f"- {len(tier1)} verified problems (Tier 1), {len(tier2)} emerging signals (Tier 2)")
    lines.append(f"- {total_unaddressed} themes remain unaddressed across all product areas")

    if source_errors:
        errs = ", ".join(f"{src}" for src in source_errors.keys())
        lines.append(f"- {len(source_errors)} sources unavailable this run ({errs})")

    lines.append("")

    if tier1:
        lines.append("TOP 3 PRIORITY ISSUES")
        lines.append("")

        for i, t in enumerate(tier1[:3], 1):
            rice = t.get("rice_score", t.get("confidence_score", "-"))
            ric = t.get("ric_score", "-")
            effort = t.get("effort_label", "-")
            mentions = t.get("unique_mention_count", 0)
            src_count = t.get("source_type_count", 0)
            srcs = ", ".join(t.get("source_breakdown", {}).keys())

            lines.append(f"{i}. {t.get('theme_name', '').title()}")
            lines.append(f"   RICE: {rice} | RIC: {ric} | Effort: {effort} | {mentions} mentions | {src_count} sources ({srcs})")

            if t.get("competitor_addressed"):
                lines.append(f"   Competitor alert: Competitor has addressed this issue")

            quotes = t.get("quotes", [])
            if quotes:
                q = quotes[0][:200]
                src_name = list(t.get("source_breakdown", {}).keys())[0] if t.get("source_breakdown") else ""
                lines.append(f'   Evidence: "{q}" — {src_name}')

            if t.get("divergence_flag"):
                pct = int(t.get("divergence_pct", 0) * 100)
                lines.append(f"   ⚠ RICE/RIC DIVERGENCE ({pct}%) — Effort estimate may need verification")

            lines.append("")

    # Needs attention
    attention_items = [t for t in tier1 if t.get("divergence_flag")]
    if attention_items:
        lines.append("NEEDS YOUR ATTENTION")
        for t in attention_items:
            pct = int(t.get("divergence_pct", 0) * 100)
            effort = t.get("effort_label", "unknown")
            lines.append(f"- {t.get('theme_name', '').title()}: {pct}% RICE/RIC gap — effort estimate of {effort} is driving this ranking. Verify before acting.")
        lines.append("")

    lines.append(f"FULL REPORT: runs/{run_id}/report.md")

    return "\n".join(lines)
