from __future__ import annotations
"""Cluster pain points by (product_area, cluster_label)."""
import logging

logger = logging.getLogger(__name__)


def cluster_pain_points(pain_points: list[dict], source_map: dict[str, dict]) -> list[dict]:
    """
    Group pain points into themes by (product_area, cluster_label.lower().strip()).
    source_map maps platform_id -> original item (for engagement/source metadata).
    Returns list of theme dicts.
    """
    clusters: dict[tuple, dict] = {}

    for pp in pain_points:
        product_area = pp.get("product_area", "Platform")
        raw_label = pp.get("cluster_label", "unknown issue")
        cluster_key = (product_area, raw_label.lower().strip())

        source_platform_id = pp.get("source_platform_id", "")
        original_item = source_map.get(source_platform_id, {})
        source_name = original_item.get("source", "Unknown")

        if cluster_key not in clusters:
            clusters[cluster_key] = {
                "theme_name": raw_label.lower().strip(),
                "product_area": product_area,
                "cluster_label": raw_label,
                "mention_count": 0,
                "unique_mention_count": 0,
                "source_type_count": 0,
                "sources": {},  # source_name -> count
                "platform_ids": [],
                "pain_point_texts": [],
                "quotes": [],
                "severity_counts": {"low": 0, "medium": 0, "high": 0, "critical": 0},
                "engagement_weights": [],
                "dates": [],
            }

        cluster = clusters[cluster_key]
        cluster["mention_count"] += 1

        if source_name not in cluster["sources"]:
            cluster["sources"][source_name] = 0
        cluster["sources"][source_name] += 1

        if source_platform_id not in cluster["platform_ids"]:
            cluster["platform_ids"].append(source_platform_id)
            cluster["unique_mention_count"] += 1

        pain_text = pp.get("pain_point_text", "")
        if pain_text not in cluster["pain_point_texts"]:
            cluster["pain_point_texts"].append(pain_text)

        severity = pp.get("severity", "medium")
        if severity in cluster["severity_counts"]:
            cluster["severity_counts"][severity] += 1

        raw_text = original_item.get("raw_text", "")
        if raw_text and raw_text not in cluster["quotes"] and len(cluster["quotes"]) < 3:
            cluster["quotes"].append(raw_text[:300])

        date = original_item.get("date", "")
        if date:
            cluster["dates"].append(date)

        eng = original_item.get("engagement", {})
        cluster["engagement_weights"].append(eng)

    # Finalize themes
    themes = []
    for (product_area, label_key), cluster in clusters.items():
        cluster["source_type_count"] = len(cluster["sources"])
        cluster["source_breakdown"] = dict(cluster["sources"])
        del cluster["sources"]

        # Dominant severity
        sev_counts = cluster["severity_counts"]
        dominant_severity = max(sev_counts, key=lambda k: sev_counts[k])
        cluster["dominant_severity"] = dominant_severity

        # Latest/oldest date
        sorted_dates = sorted([d for d in cluster["dates"] if d])
        cluster["latest_date"] = sorted_dates[-1] if sorted_dates else ""
        cluster["oldest_date"] = sorted_dates[0] if sorted_dates else ""

        themes.append(cluster)

    logger.info(f"Clusterer: {len(pain_points)} pain points → {len(themes)} themes")
    return themes
