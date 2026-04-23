from __future__ import annotations
#!/usr/bin/env python3
"""
Notion PM Agent — Main Pipeline Orchestrator
6-phase pipeline: Setup → Collection → Research → Synthesis → Validation → Output
"""
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
import anthropic

# Load environment variables first
load_dotenv(override=True)

# Configure logging
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "pipeline.log", mode="a"),
    ],
)
logger = logging.getLogger(__name__)

# Internal imports
from tools.hn_tool import fetch_hn_items
from tools.firecrawl_tool import fetch_g2_reviews, fetch_notion_changelog, fetch_competitor_changelogs, scrape_single_url
from tools.seed_url_mapper import SeedURLMapper
from tools.apify_tool import fetch_reddit_posts, fetch_app_store_reviews, fetch_play_store_reviews

from pipeline.registry import dedup_within_run, dedup_cross_run, register_items
from pipeline.semantic_dedup import semantic_dedup
from pipeline.chunker import batch_items
from pipeline.clusterer import cluster_pain_points
from pipeline.scorer import score_themes, apply_effort_scores

from agents.research_agent import run_research_agent
from agents.synthesis_agent import run_synthesis_agent
from agents.harmonization_agent import run_harmonization_agent
from agents.validation_agent import run_validation_agent, check_competitor_coverage
from agents.scoring_agent import run_scoring_agent

from outputs.report_generator import generate_report
from outputs.brief_generator import generate_brief
from outputs.memory_manager import update_memory, read_memory


LOOKBACK_DAYS = 60
CONFIDENCE_THRESHOLD = 0.60
FIRECRAWL_BUDGET           = 7   # total Firecrawl credits per run
FIRECRAWL_CHANGELOG_BUDGET = 5   # credits for Notion changelog + top 4 competitors
FIRECRAWL_SEED_BUDGET      = 2   # credits for intent-targeted seed URLs

# HN queries with intent tags and signal-quality weights.
# weight: expected relevance ratio (0-1). Higher = more specific pain-area query.
HN_QUERIES = [
    {"query": "Notion",                   "intent": "brand_general",  "weight": 0.60},
    {"query": "Notion collaboration",     "intent": "feature_collab", "weight": 0.75},
    {"query": "Notion database problems", "intent": "pain_direct",    "weight": 0.85},
    {"query": "Notion alternatives",      "intent": "competitive",    "weight": 0.80},
    {"query": "Notion user feedback",     "intent": "pain_general",   "weight": 0.70},
    {"query": "Notion offline sync",      "intent": "pain_direct",    "weight": 0.90},
    {"query": "Notion AI limitations",    "intent": "pain_direct",    "weight": 0.88},
]


def _verify_api_keys() -> list[str]:
    """Check which API keys are present."""
    missing = []
    required = ["ANTHROPIC_API_KEY"]
    optional = ["FIRECRAWL_API_KEY", "APIFY_API_KEY", "TAVILY_API_KEY"]

    for key in required:
        if not os.getenv(key):
            missing.append(key)

    for key in optional:
        if not os.getenv(key):
            logger.warning(f"Optional key {key} not set — that source will be skipped")

    return missing


def _load_overrides() -> list[dict]:
    """Load human override file."""
    override_path = Path(__file__).parent / "data" / "overrides.json"
    try:
        data = json.loads(override_path.read_text())
        overrides = data.get("overrides", [])
        if overrides:
            logger.info(f"Loaded {len(overrides)} overrides")
        return overrides
    except Exception as e:
        logger.warning(f"Could not load overrides: {e}")
        return []


def _create_run_dir() -> tuple[str, Path]:
    """Create timestamped run directory."""
    run_id = datetime.now().strftime("%Y-%m-%d_%H-%M")
    run_dir = Path(__file__).parent / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_id, run_dir


def _human_review_gate(tier1_themes: list[dict]) -> bool:
    """Display Tier 1 findings and ask for human confirmation."""
    if not tier1_themes:
        print("\nNo Tier 1 themes to review. Proceeding to output generation.")
        return True

    print("\n" + "─" * 50)
    print(" REVIEW GATE — Tier 1 Findings")
    print("─" * 50)

    for i, t in enumerate(tier1_themes, 1):
        rice = t.get("rice_score", t.get("confidence_score", "-"))
        mentions = t.get("unique_mention_count", 0)
        src_count = t.get("source_type_count", 0)
        divergence = " ⚠ RICE/RIC divergence ({:.0f}%)".format(t.get("divergence_pct", 0) * 100) if t.get("divergence_flag") else ""
        print(f"   {i}. RICE={rice:>6} | {t.get('product_area', '-')}: {t.get('theme_name', '')}")
        print(f"              ({mentions} mentions, {src_count} sources){divergence}")

    print("─" * 50)
    answer = input("Confirm these findings? (y to finalize / n to edit overrides.json and re-run): ").strip().lower()
    return answer == "y"


def run_pipeline(mock_mode: bool = False) -> None:
    """Execute the full 6-phase PM agent pipeline."""

    # ── Phase 1: Setup ──────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("PHASE 1: Setup")
    logger.info("=" * 60)

    missing_keys = _verify_api_keys()
    if missing_keys:
        logger.error(f"Missing required API keys: {missing_keys}")
        sys.exit(1)

    overrides = _load_overrides()
    run_id, run_dir = _create_run_dir()
    logger.info(f"Run ID: {run_id}")

    # Read prior memory for context
    prior_memory = read_memory()
    if prior_memory:
        logger.info(f"Loaded prior memory ({len(prior_memory)} chars)")

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    pipeline_stats = {
        "run_id": run_id,
        "total_items_fetched": 0,
        "items_after_dedup": 0,
        "items_after_research": 0,
        "pain_points_extracted": 0,
        "themes_count": 0,
        "active_sources": 0,
    }
    source_errors = {}
    agent_logs = []

    # ── Phase 2: Data Collection ─────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("PHASE 2: Data Collection")
    logger.info("=" * 60)

    all_items = []

    if mock_mode:
        logger.info("MOCK MODE: Using fixture data")
        all_items = _generate_mock_items()
    else:
        # HN (free, no auth)
        try:
            hn_items = fetch_hn_items(queries=HN_QUERIES, lookback_days=LOOKBACK_DAYS)
            all_items.extend(hn_items)
            if hn_items:
                pipeline_stats["active_sources"] += 1
        except Exception as e:
            source_errors["HN"] = str(e)
            logger.error(f"HN fetch failed: {e}")

        # SeedURLMapper: intent-targeted seed expansion (free HN + budget Firecrawl)
        active_intents = list({q["intent"] for q in HN_QUERIES})
        seed_mapper = SeedURLMapper(
            firecrawl_seed_budget=FIRECRAWL_SEED_BUDGET,
            lookback_days=LOOKBACK_DAYS,
        )
        seeds = seed_mapper.get_seeds_for_intents(active_intents)

        if seeds["hn_api"]:
            try:
                hn_seed_items = fetch_hn_items(
                    queries=seed_mapper.to_hn_query_configs(seeds["hn_api"]),
                    lookback_days=LOOKBACK_DAYS,
                )
                all_items.extend(hn_seed_items)
                logger.info(f"HN seed queries: {len(hn_seed_items)} additional items")
            except Exception as e:
                source_errors["HN_seeds"] = str(e)
                logger.error(f"HN seed fetch failed: {e}")

        # G2 (requires Firecrawl)
        try:
            g2_items = fetch_g2_reviews(lookback_days=LOOKBACK_DAYS)
            all_items.extend(g2_items)
            if g2_items:
                pipeline_stats["active_sources"] += 1
        except Exception as e:
            source_errors["G2"] = str(e)
            logger.error(f"G2 fetch failed: {e}")

        # Reddit (requires Apify)
        try:
            reddit_items = fetch_reddit_posts(lookback_days=LOOKBACK_DAYS)
            all_items.extend(reddit_items)
            if reddit_items:
                pipeline_stats["active_sources"] += 1
        except Exception as e:
            source_errors["Reddit"] = str(e)
            logger.error(f"Reddit fetch failed: {e}")

        # App Store (requires Apify)
        try:
            app_items = fetch_app_store_reviews(lookback_days=LOOKBACK_DAYS)
            all_items.extend(app_items)
            if app_items:
                pipeline_stats["active_sources"] += 1
        except Exception as e:
            source_errors["App Store"] = str(e)
            logger.error(f"App Store fetch failed: {e}")

        # Play Store (requires Apify)
        try:
            play_items = fetch_play_store_reviews(lookback_days=LOOKBACK_DAYS)
            all_items.extend(play_items)
            if play_items:
                pipeline_stats["active_sources"] += 1
        except Exception as e:
            source_errors["Play Store"] = str(e)
            logger.error(f"Play Store fetch failed: {e}")

    pipeline_stats["total_items_fetched"] = len(all_items)
    logger.info(f"Total items fetched: {len(all_items)}")

    if not all_items:
        logger.error("No items fetched from any source. Exiting.")
        sys.exit(1)

    # Deduplication
    all_items = dedup_within_run(all_items)
    all_items = semantic_dedup(all_items, text_field="raw_text")  # remove near-duplicates before cross-run check
    all_items, skipped = dedup_cross_run(all_items)
    pipeline_stats["items_after_dedup"] = len(all_items)
    logger.info(f"After dedup: {len(all_items)} items ({skipped} skipped from prior runs)")

    # Save raw data
    (run_dir / "raw_items.json").write_text(json.dumps(all_items, indent=2))

    # Collect changelogs
    notion_changelog = ""
    competitor_changelogs = {}
    if not mock_mode and os.getenv("FIRECRAWL_API_KEY"):
        logger.info("Fetching Notion changelog...")
        try:
            notion_changelog = fetch_notion_changelog(budget=FIRECRAWL_CHANGELOG_BUDGET)
        except Exception as e:
            logger.warning(f"Notion changelog fetch failed: {e}")

        logger.info("Fetching competitor changelogs...")
        try:
            competitor_changelogs = fetch_competitor_changelogs(budget=FIRECRAWL_CHANGELOG_BUDGET - 1)
        except Exception as e:
            logger.warning(f"Competitor changelog fetch failed: {e}")

        # Firecrawl seed URLs (budget-capped, high-relevance intent-targeted pages)
        if seeds.get("firecrawl"):
            for target in seed_mapper.to_firecrawl_targets(seeds["firecrawl"]):
                try:
                    markdown = scrape_single_url(target["url"], wait_for=target["wait_for"])
                    if markdown and len(markdown) > 200:
                        safe_name = target["name"].lower().replace(" ", "_").replace(":", "")
                        all_items.append({
                            "source": "Firecrawl_Seed",
                            "url": target["url"],
                            "platform_id": f"fc_seed_{safe_name}",
                            "date": datetime.now().strftime("%Y-%m-%d"),
                            "raw_text": markdown[:2000],
                            "star_rating": None,
                            "user_segment": "unknown",
                            "query_intent": target["intent"],
                            "query_weight": target["expected_relevance"],
                            "engagement": {
                                "upvotes": None, "downvotes": None,
                                "star_rating": None, "helpful_votes": None,
                            },
                        })
                        logger.info(f"Firecrawl seed scraped: {target['name']}")
                except Exception as e:
                    source_errors[f"fc_seed_{target['name']}"] = str(e)
                    logger.error(f"Firecrawl seed scrape failed for {target['name']}: {e}")
    else:
        logger.info("Skipping changelog fetches (no Firecrawl key or mock mode)")

    # ── Phase 3: Research Agent ───────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("PHASE 3: Research Agent (Haiku)")
    logger.info("=" * 60)

    research_batches = batch_items(all_items)
    relevant_items, research_log = run_research_agent(research_batches, client)
    agent_logs.append(research_log)
    pipeline_stats["items_after_research"] = len(relevant_items)

    if not relevant_items:
        logger.error("No relevant items after research filtering. Exiting.")
        sys.exit(1)

    # Build source map for later use
    source_map = {item["platform_id"]: item for item in all_items}

    # Merge cleaned_text back into source_map items
    for rel in relevant_items:
        pid = rel.get("platform_id", "")
        if pid in source_map:
            source_map[pid]["cleaned_text"] = rel.get("cleaned_text", "")
            source_map[pid]["user_segment"] = rel.get("user_segment", "unknown")

    # ── Phase 4: Synthesis + Clustering ──────────────────────────────────────
    logger.info("=" * 60)
    logger.info("PHASE 4: Synthesis Agent (Sonnet) + Clustering")
    logger.info("=" * 60)

    synthesis_batches = batch_items(relevant_items)
    pain_points, flagged_items, synthesis_log = run_synthesis_agent(
        synthesis_batches, client, confidence_threshold=CONFIDENCE_THRESHOLD
    )
    agent_logs.append(synthesis_log)
    pipeline_stats["pain_points_extracted"] = len(pain_points)

    # Label harmonization
    pain_points, harmonization_log = run_harmonization_agent(pain_points, client)
    agent_logs.append(harmonization_log)

    # Cluster into themes
    themes = cluster_pain_points(pain_points, source_map)
    pipeline_stats["themes_count"] = len(themes)

    if not themes:
        logger.error("No themes produced after clustering. Exiting.")
        sys.exit(1)

    # Enrich themes with avg_query_weight so the scorer can reward
    # pain-area queries over generic brand queries
    for theme in themes:
        weights = [
            source_map.get(pid, {}).get("query_weight", 1.0)
            for pid in theme.get("platform_ids", [])
        ]
        theme["avg_query_weight"] = round(sum(weights) / len(weights), 3) if weights else 1.0

    # ── Phase 5: Validation + Scoring ─────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("PHASE 5: Validation + Scoring")
    logger.info("=" * 60)

    # Competitor cross-reference
    competitor_coverage = check_competitor_coverage(themes, competitor_changelogs)

    # Initial scoring (no effort yet)
    scored_themes = score_themes(themes, competitor_coverage)

    # Changelog validation
    validated_themes, validation_log = run_validation_agent(
        scored_themes, notion_changelog, overrides, client
    )
    agent_logs.append(validation_log)

    # Effort estimation for Tier 1 only
    tier1_themes = [t for t in validated_themes if t.get("tier") == 1]
    effort_data, scoring_log = run_scoring_agent(tier1_themes, client)
    agent_logs.append(scoring_log)

    # Apply effort → recompute RICE/RIC
    final_themes = apply_effort_scores(validated_themes, effort_data)

    # Sort Tier 1 by RICE score
    tier1_final = sorted(
        [t for t in final_themes if t.get("tier") == 1],
        key=lambda t: t.get("rice_score") or t.get("confidence_score", 0),
        reverse=True,
    )
    tier2_final = sorted(
        [t for t in final_themes if t.get("tier") == 2],
        key=lambda t: t.get("confidence_score", 0),
        reverse=True,
    )
    tier3_final = sorted(
        [t for t in final_themes if t.get("tier") == 3],
        key=lambda t: t.get("confidence_score", 0),
        reverse=True,
    )
    final_themes_sorted = tier1_final + tier2_final + tier3_final

    scoring_stats = {
        "tier1_count": len(tier1_final),
        "tier2_count": len(tier2_final),
        "tier3_count": len(tier3_final),
        "scored_count": len(effort_data),
    }

    # ── Human Review Gate ─────────────────────────────────────────────────────
    confirmed = _human_review_gate(tier1_final)
    if not confirmed:
        print("\nReview declined. Edit data/overrides.json and re-run.")
        sys.exit(0)

    # ── Phase 6: Outputs ──────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("PHASE 6: Outputs")
    logger.info("=" * 60)

    # Register processed items
    register_items(all_items)

    # Build full run_data
    run_data = {
        "run_id": run_id,
        "pipeline_stats": pipeline_stats,
        "scoring_stats": scoring_stats,
        "themes": final_themes_sorted,
        "flagged_items": flagged_items,
        "agent_logs": agent_logs,
        "source_errors": source_errors,
        "total_cost_usd_approx": _estimate_cost(agent_logs),
    }

    # Write run_data.json
    run_data_path = run_dir / "run_data.json"
    run_data_path.write_text(json.dumps(run_data, indent=2, default=str))
    logger.info(f"Written: {run_data_path}")

    # Generate and write report.md
    report_md = generate_report(run_data)
    report_path = run_dir / "report.md"
    report_path.write_text(report_md)
    logger.info(f"Written: {report_path}")

    # Generate and write brief.md
    brief_md = generate_brief(run_data)
    brief_path = run_dir / "brief.md"
    brief_path.write_text(brief_md)
    logger.info(f"Written: {brief_path}")

    # Update memory
    update_memory(run_data)

    # Print brief to console
    print("\n" + "=" * 60)
    print(brief_md)
    print("=" * 60)
    print(f"\nFull report: {report_path}")
    print(f"Run data: {run_data_path}")
    logger.info(f"Pipeline complete. Run ID: {run_id}")


def _estimate_cost(agent_logs: list[dict]) -> float:
    """Rough cost estimate based on token usage."""
    total = 0.0
    for log in agent_logs:
        model = log.get("model", "")
        inp = log.get("input_tokens", 0)
        out = log.get("output_tokens", 0)
        if "haiku" in model:
            total += inp * 1.0 / 1_000_000 + out * 5.0 / 1_000_000
        else:  # sonnet
            total += inp * 3.0 / 1_000_000 + out * 15.0 / 1_000_000
    return round(total, 4)


def _generate_mock_items() -> list[dict]:
    """Generate mock feedback items for testing without API keys."""
    from datetime import date, timedelta
    today = date.today()

    items = []
    mock_data = [
        ("G2", "g2_mock_001", "enterprise", 3.0,
         "Likes: Notion is flexible but the MCP integration is extremely limited. "
         "Dislikes: Cannot connect external tools properly. Competitor offers much better integrations."),
        ("G2", "g2_mock_002", "startup", 4.0,
         "Likes: Good for docs. Dislikes: Notion AI only works on the current page, "
         "cannot query across databases or other pages in the workspace."),
        ("HN", "hn_mock_001", "unknown", None,
         "Notion's offline mode is completely broken. Tried to access my notes during a flight and got blank screens."),
        ("HN", "hn_mock_002", "unknown", None,
         "The MCP integration in Notion is years behind what Coda and Obsidian offer. "
         "Building anything with external tool connections is painful."),
        ("Play Store", "ps_mock_001", "individual", 2.0,
         "App is unusable offline. Just shows a blank screen when there's no internet."),
        ("Play Store", "ps_mock_002", "individual", 3.0,
         "Notion AI is great but only works page by page. I want to ask questions about my entire workspace."),
        ("HN", "hn_mock_003", "unknown", None,
         "Switched from Notion to Obsidian for offline-first sync. Notion loses work constantly."),
        ("G2", "g2_mock_003", "mid_market", 3.0,
         "Likes: Good collaboration. Dislikes: MCP tools are missing. Cannot build the integrations our team needs."),
    ]

    for i, (source, pid, segment, stars, text) in enumerate(mock_data):
        date_str = (today - timedelta(days=i * 5 + 3)).strftime("%Y-%m-%d")
        items.append({
            "source": source,
            "url": f"https://example.com/{source.lower()}/{pid}",
            "platform_id": pid,
            "date": date_str,
            "raw_text": text,
            "star_rating": stars,
            "user_segment": segment,
            "engagement": {
                "upvotes": 10 + i * 3,
                "downvotes": None,
                "star_rating": stars,
                "helpful_votes": i * 2,
            },
        })

    return items


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Notion PM Agent Pipeline")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock data instead of live API calls (for testing)",
    )
    args = parser.parse_args()

    run_pipeline(mock_mode=args.mock)
