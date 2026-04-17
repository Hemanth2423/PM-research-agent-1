from __future__ import annotations
"""Generate full Markdown report from run data."""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def generate_report(run_data: dict) -> str:
    """Generate a full Markdown report from run_data."""
    run_id = run_data.get("run_id", "unknown")
    stats = run_data.get("pipeline_stats", {})
    themes = run_data.get("themes", [])
    flagged = run_data.get("flagged_items", [])

    tier1 = [t for t in themes if t.get("tier") == 1]
    tier2 = [t for t in themes if t.get("tier") == 2]
    tier3 = [t for t in themes if t.get("tier") == 3]

    lines = []
    lines.append(f"# Notion PM Intelligence Report")
    lines.append(f"\n**Run:** {run_id}  ")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}  ")
    lines.append(f"**Sources:** {stats.get('total_items_fetched', 0)} items fetched, {stats.get('items_after_research', 0)} relevant")
    lines.append(f"\n---\n")

    # Pipeline summary
    lines.append("## Pipeline Summary\n")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total items fetched | {stats.get('total_items_fetched', 0)} |")
    lines.append(f"| Items after dedup | {stats.get('items_after_dedup', 0)} |")
    lines.append(f"| Items after research filter | {stats.get('items_after_research', 0)} |")
    lines.append(f"| Pain points extracted | {stats.get('pain_points_extracted', 0)} |")
    lines.append(f"| Themes identified | {stats.get('themes_count', 0)} |")
    lines.append(f"| Tier 1 (Verified) | {len(tier1)} |")
    lines.append(f"| Tier 2 (Emerging) | {len(tier2)} |")
    lines.append(f"| Tier 3 (Unverified) | {len(tier3)} |")
    lines.append(f"| Flagged (low confidence) | {len(flagged)} |")
    lines.append("")

    # Source availability
    source_errors = run_data.get("source_errors", {})
    if source_errors:
        lines.append("### Source Availability Issues\n")
        for src, err in source_errors.items():
            lines.append(f"- **{src}**: {err}")
        lines.append("")

    lines.append("\n---\n")

    # Tier 1
    lines.append("## Tier 1 — Verified Problems\n")
    if not tier1:
        lines.append("_No Tier 1 themes this run._\n")
    else:
        lines.append("| # | Theme | Product Area | RICE | RIC | Effort | Mentions | Sources |")
        lines.append("|---|-------|--------------|------|-----|--------|----------|---------|")
        for i, t in enumerate(tier1, 1):
            rice = t.get("rice_score", t.get("confidence_score", "-"))
            ric = t.get("ric_score", "-")
            effort = t.get("effort_label") or "-"
            mentions = t.get("unique_mention_count", 0)
            src_breakdown = t.get("source_breakdown", {})
            src_str = ", ".join(f"{k}: {v}" for k, v in src_breakdown.items())
            theme_name = t.get("theme_name", "").title()
            lines.append(f"| {i} | {theme_name} | {t.get('product_area', '-')} | {rice} | {ric} | {effort} | {mentions} | {src_str} |")
        lines.append("")

        for i, t in enumerate(tier1, 1):
            lines.append(f"\n### {i}. {t.get('theme_name', '').title()}\n")
            lines.append(f"**Product Area:** {t.get('product_area', '-')}  ")
            lines.append(f"**Confidence:** {t.get('confidence_score', '-')} ({t.get('confidence_label', '-')})  ")
            lines.append(f"**Validation:** {t.get('validation_status', 'UNADDRESSED')}  ")

            if t.get("divergence_flag"):
                pct = int(t.get("divergence_pct", 0) * 100)
                lines.append(f"**⚠ RICE/RIC Divergence: {pct}%** — Effort estimate may need verification  ")

            if t.get("override_flag"):
                lines.append(f"**[OVERRIDE]** {t.get('validation_evidence', '')}  ")

            lines.append(f"\n**Representative Quotes:**")
            for q in t.get("quotes", [])[:3]:
                lines.append(f"> _{q[:250]}_\n")

            if t.get("competitor_addressed"):
                lines.append(f"\n**Competitor Alert:** At least one competitor has addressed this issue.")

            if t.get("effort_label"):
                lines.append(f"\n**Effort Estimate:** {t['effort_label']}")

    lines.append("\n---\n")

    # Tier 2
    lines.append("## Tier 2 — Emerging Signals\n")
    if not tier2:
        lines.append("_No Tier 2 themes this run._\n")
    else:
        lines.append("| Theme | Product Area | Confidence | Mentions | Sources |")
        lines.append("|-------|--------------|------------|----------|---------|")
        for t in tier2:
            src_breakdown = t.get("source_breakdown", {})
            src_str = ", ".join(f"{k}: {v}" for k, v in src_breakdown.items())
            lines.append(f"| {t.get('theme_name', '').title()} | {t.get('product_area', '-')} | {t.get('confidence_score', '-')} | {t.get('unique_mention_count', 0)} | {src_str} |")
        lines.append("")

    lines.append("\n---\n")

    # Tier 3
    lines.append("## Tier 3 — Unverified Dump\n")
    lines.append("_Review manually — you may recognize items from customer calls._\n")
    if not tier3:
        lines.append("_No Tier 3 themes this run._\n")
    else:
        for t in tier3:
            lines.append(f"- **{t.get('product_area', '-')}**: {t.get('theme_name', '')} (score: {t.get('confidence_score', '-')}, mentions: {t.get('unique_mention_count', 0)})")
        lines.append("")

    lines.append("\n---\n")

    # Flagged
    if flagged:
        lines.append("## Flagged Items (Low Classification Confidence)\n")
        for f in flagged:
            conf = f.get("classification_confidence", "-")
            text = f.get("pain_point_text", "")[:150]
            lines.append(f"- (conf: {conf}) {text}")
        lines.append("")

    return "\n".join(lines)
