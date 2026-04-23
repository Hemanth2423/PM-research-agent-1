from __future__ import annotations
"""SeedURLMapper: maps HN query intents to curated seed sources with fetch metadata."""
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Seed catalogue
# Each entry:
#   intent              — matches the "intent" field on HN_QUERIES / _DEFAULT_QUERIES
#   name                — human label used in logs and as platform_id prefix
#   fetch_method        — "hn_api" (free Algolia) or "firecrawl" (costs 1 credit)
#   source_type         — tag applied to items produced by this seed
#   expected_relevance  — 0.0–1.0; used for budget priority ordering
#   hn_query_override   — hn_api only: the targeted Algolia query string
#   url                 — firecrawl only: the target URL
#   wait_for            — firecrawl only: JS wait in milliseconds
# ---------------------------------------------------------------------------
_SEED_CATALOGUE: list[dict] = [
    # pain_direct — offline / sync
    {
        "intent": "pain_direct",
        "name": "HN: Notion slow offline",
        "fetch_method": "hn_api",
        "source_type": "hn_seed",
        "expected_relevance": 0.90,
        "hn_query_override": "Notion slow offline",
    },
    # pain_direct — performance / lag
    {
        "intent": "pain_direct",
        "name": "HN: Notion performance lag",
        "fetch_method": "hn_api",
        "source_type": "hn_seed",
        "expected_relevance": 0.88,
        "hn_query_override": "Notion performance lag",
    },
    # pain_general — database / setup
    {
        "intent": "pain_general",
        "name": "HN: Notion database setup complexity",
        "fetch_method": "hn_api",
        "source_type": "hn_seed",
        "expected_relevance": 0.80,
        "hn_query_override": "Notion database setup complexity",
    },
    # competitive — portability / lock-in
    {
        "intent": "competitive",
        "name": "HN: Notion export lock-in",
        "fetch_method": "hn_api",
        "source_type": "hn_seed",
        "expected_relevance": 0.82,
        "hn_query_override": "Notion export lock-in",
    },
    # feature_collab — team workflow
    {
        "intent": "feature_collab",
        "name": "HN: Notion team collaboration issues",
        "fetch_method": "hn_api",
        "source_type": "hn_seed",
        "expected_relevance": 0.76,
        "hn_query_override": "Notion team collaboration issues",
    },
    # competitive — Linear changelog (not in existing SCRAPE_TARGETS)
    {
        "intent": "competitive",
        "name": "Linear Changelog",
        "fetch_method": "firecrawl",
        "source_type": "competitor_changelog_seed",
        "expected_relevance": 0.78,
        "url": "https://linear.app/changelog",
        "wait_for": 2000,
    },
    # competitive — Obsidian vs Notion comparison article
    {
        "intent": "competitive",
        "name": "Obsidian vs Notion guide",
        "fetch_method": "firecrawl",
        "source_type": "competitive_comparison_seed",
        "expected_relevance": 0.72,
        "url": "https://www.obsidian.rocks/obsidian-vs-notion/",
        "wait_for": 2000,
    },
]


class SeedURLMapper:
    """Maps query intents to curated seed sources with budget-aware scheduling.

    Usage:
        mapper = SeedURLMapper(firecrawl_seed_budget=2)
        seeds = mapper.get_seeds_for_intents(["pain_direct", "competitive"])
        hn_query_configs = mapper.to_hn_query_configs(seeds["hn_api"])
        fc_targets = mapper.to_firecrawl_targets(seeds["firecrawl"])
    """

    def __init__(
        self,
        catalogue: list[dict] | None = None,
        firecrawl_seed_budget: int = 2,
        lookback_days: int = 60,
    ) -> None:
        self._catalogue = catalogue if catalogue is not None else _SEED_CATALOGUE
        self.firecrawl_seed_budget = firecrawl_seed_budget
        self.lookback_days = lookback_days

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_seeds_for_intents(self, intents: list[str]) -> dict[str, list[dict]]:
        """Return seeds partitioned by fetch method for the requested intents.

        Args:
            intents: list of intent strings, e.g. ["pain_direct", "competitive"]

        Returns:
            {
                "hn_api":    [seed_dict, ...],   # free; feed into fetch_hn_items()
                "firecrawl": [seed_dict, ...],   # budget-capped; feed into scrape_single_url()
            }
        """
        matched = [s for s in self._catalogue if s["intent"] in intents]
        hn_seeds = [s for s in matched if s["fetch_method"] == "hn_api"]
        fc_seeds = self._allocate_firecrawl_seeds(
            [s for s in matched if s["fetch_method"] == "firecrawl"]
        )
        logger.info(
            f"SeedURLMapper: {len(hn_seeds)} HN_API seeds, "
            f"{len(fc_seeds)} Firecrawl seeds (budget={self.firecrawl_seed_budget})"
        )
        return {"hn_api": hn_seeds, "firecrawl": fc_seeds}

    def to_hn_query_configs(self, hn_seeds: list[dict]) -> list[dict]:
        """Convert HN_API seeds into query config dicts for fetch_hn_items().

        Each entry matches the {query, intent, weight} shape of _DEFAULT_QUERIES.
        The extra _seed_name key is ignored by fetch_hn_items() silently.
        """
        return [
            {
                "query": s["hn_query_override"],
                "intent": s["intent"],
                "weight": s["expected_relevance"],
                "_seed_name": s["name"],
            }
            for s in hn_seeds
        ]

    def to_firecrawl_targets(self, fc_seeds: list[dict]) -> list[dict]:
        """Convert Firecrawl seeds into scrape target dicts for scrape_single_url().

        Each dict has: name, url, wait_for, intent, expected_relevance, source_type.
        """
        return [
            {
                "name": s["name"],
                "url": s["url"],
                "wait_for": s.get("wait_for", 2000),
                "intent": s["intent"],
                "expected_relevance": s["expected_relevance"],
                "source_type": s["source_type"],
            }
            for s in fc_seeds
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _allocate_firecrawl_seeds(self, candidates: list[dict]) -> list[dict]:
        """Select Firecrawl seed candidates by expected_relevance within budget."""
        sorted_candidates = sorted(
            candidates, key=lambda s: s["expected_relevance"], reverse=True
        )
        allocated: list[dict] = []
        remaining = self.firecrawl_seed_budget
        for seed in sorted_candidates:
            if remaining <= 0:
                break
            allocated.append(seed)
            remaining -= 1  # each Firecrawl seed costs 1 credit
        return allocated
