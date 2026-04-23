# Notion PM Intelligence Agent

A 6-phase Python pipeline that automatically collects user feedback from across the web, extracts pain points using Claude AI, and delivers a tiered product roadmap brief — so you spend your time acting on insights, not finding them.

---

## What It Does

Every run, the agent:

1. **Collects** feedback from Hacker News (and optionally Reddit, G2, App/Play Store)
2. **Filters** noise using an AI research agent — only Notion-specific signals pass through
3. **Extracts** pain points and groups them into themes using Claude Sonnet
4. **Validates** themes against Notion's own changelog and 4 competitor changelogs
5. **Scores** each theme with a multi-signal confidence score + RICE/RIC framework
6. **Outputs** a tiered Markdown report and a one-page executive brief

```
Data Collection → Research Filter → Synthesis → Validation → Scoring → Report
     (free)          (Haiku)         (Sonnet)     (Sonnet)    (Python)
```

---

## Quick Start

**Prerequisites:** Python 3.9+, pip

```bash
# 1. Navigate to project
cd "PM agent_p1"

# 2. Install dependencies
pip3 install -r requirements.txt

# 3. Add your API keys to .env
# ANTHROPIC_API_KEY=sk-ant-...
# FIRECRAWL_API_KEY=fc-...

# 4. Run (uses ~7 Firecrawl credits per run)
python3 main.py
```

Your report lands in `runs/YYYY-MM-DD_HH-MM/report.md`.

**Test without spending any Firecrawl credits:**
```bash
python3 main.py --mock
```

---

## Setup

### `.env` File

```env
ANTHROPIC_API_KEY=sk-ant-...        # Required
FIRECRAWL_API_KEY=fc-...            # Required for web scraping
APIFY_API_KEY=...                   # Optional: Reddit, App Store, Play Store
```

### Dependencies

```bash
pip3 install -r requirements.txt
```

| Package | Purpose |
|---|---|
| `anthropic` | Claude API (Haiku + Sonnet) |
| `python-dotenv` | Load `.env` keys |
| `requests` | HN Algolia API + Firecrawl HTTP calls |
| `numpy` | Engagement z-score calculations |
| `scikit-learn` | TF-IDF semantic deduplication |

---

## Project Structure

```
PM agent_p1/
├── main.py                    # Pipeline orchestrator (6 phases)
├── tools/
│   ├── hn_tool.py             # HN Algolia API (free, no auth)
│   ├── firecrawl_tool.py      # Web scraping for G2 + changelogs
│   ├── apify_tool.py          # Reddit, App Store, Play Store
│   └── seed_url_mapper.py     # Intent → targeted seed URLs
├── pipeline/
│   ├── registry.py            # Cross-run deduplication
│   ├── chunker.py             # Batch items for Claude API
│   ├── clusterer.py           # Group pain points into themes
│   ├── scorer.py              # Confidence + RICE/RIC scoring
│   └── semantic_dedup.py      # TF-IDF near-duplicate removal
├── agents/
│   ├── research_agent.py      # Haiku: relevance filter
│   ├── synthesis_agent.py     # Sonnet: pain point extraction
│   ├── harmonization_agent.py # Haiku: merge duplicate labels
│   ├── validation_agent.py    # Sonnet: check against changelogs
│   └── scoring_agent.py       # Sonnet: effort estimation
├── outputs/
│   ├── report_generator.py    # Full Markdown report
│   ├── brief_generator.py     # One-page executive brief
│   └── memory_manager.py      # Cross-run context (memory.md)
├── data/
│   ├── overrides.json         # PM overrides (mark items IN_PROGRESS)
│   ├── seen_registry.json     # Fingerprints of processed items
│   └── memory.md              # Cross-run memory for Claude
└── runs/                      # One folder per run (report, brief, JSON)
```

---

## Output: Tiered Findings

Every run produces three files in `runs/YYYY-MM-DD_HH-MM/`:

| File | What's in it |
|---|---|
| `report.md` | Full tiered report with scores, quotes, and competitor alerts |
| `brief.md` | One-page executive summary — top issues + flagged divergences |
| `run_data.json` | Raw structured output for downstream tooling |

### The Three Tiers

| Tier | Meaning | Confidence Threshold |
|---|---|---|
| **Tier 1** | Verified, high-confidence — act now | ≥ 6.5 |
| **Tier 2** | Emerging signals — watch list | ≥ 3.5 |
| **Tier 3** | Unverified noise — review manually | < 3.5 |

---

## Firecrawl Credit Budget

Each live run uses **~7 Firecrawl credits**:

| What | Credits |
|---|---|
| Notion changelog | 1 |
| Obsidian, Confluence, Coda, Craft changelogs | 4 |
| Seed URL: Linear changelog | 1 |
| Seed URL: Obsidian vs Notion comparison | 1 |
| **Total** | **7** |

> G2 is currently WAF-blocked (Datadome) — detected automatically and skipped, no credit wasted.

---

## Architectural Optimizations

### 1. Multi-Query Expansion

Instead of one broad `"Notion"` search, the pipeline runs **7 targeted HN queries** — each tagged with an `intent` and a `weight`:

```python
HN_QUERIES = [
    {"query": "Notion",                   "intent": "brand_general",  "weight": 0.60},
    {"query": "Notion database problems", "intent": "pain_direct",    "weight": 0.85},
    {"query": "Notion offline sync",      "intent": "pain_direct",    "weight": 0.90},
    {"query": "Notion alternatives",      "intent": "competitive",    "weight": 0.80},
    ...
]
```

- Higher `weight` → pain point themes from that query get a credibility boost in scoring
- `intent` tag flows through to the research agent for sharper, context-aware filtering
- All query results are deduplicated before processing — no double-counting

---

### 2. Seed URL Mapper

`tools/seed_url_mapper.py` adds a targeted enrichment layer. For each query's `intent`, it maps to additional curated sources:

```
HN Queries (intent: pain_direct, competitive, ...)
       ↓
SeedURLMapper.get_seeds_for_intents()
  ├─ HN_API seeds  →  5 extra free Algolia queries
  │     "Notion slow offline", "Notion performance lag",
  │     "Notion export lock-in", "Notion team collaboration issues" ...
  └─ Firecrawl seeds  →  2 targeted pages (budget-capped)
        Linear changelog, Obsidian vs Notion comparison
       ↓
Research Agent (now receives query_intent per item → sharper filtering)
```

**Why this matters:** Generic queries surface Notion *mentions*. Seed queries surface Notion *complaints*. The signal-to-noise ratio is significantly higher, and the research agent can apply a targeted relevance bar per intent rather than a single global filter.

---

### 3. Semantic Deduplication

Before sending items to Claude, the pipeline runs a **TF-IDF cosine similarity** pass to remove near-duplicates — the same complaint written slightly differently by different people:

```
Raw items
  → dedup_within_run()    exact hash dedup (same URL/ID)
  → semantic_dedup()      TF-IDF cosine similarity, threshold 0.85
  → dedup_cross_run()     fingerprints seen in prior runs
```

This reduces Claude API cost and prevents the same underlying issue from being split into multiple weak themes instead of one strong one. Powered by `scikit-learn` — no heavy ML model downloads required.

---

### 4. Confidence Scoring (Recalibrated)

The confidence score combines multiple signals so a theme's rank reflects real-world signal strength:

| Signal | Effect |
|---|---|
| Each unique mention | +1.0 base |
| Engagement (upvotes, comments) | z-score weighted boost |
| 3+ sources confirming same theme | ×1.5 multiplier |
| Single source only | ×0.8 (mild discount) |
| Recent content (≤30 days) | ×1.3 bonus |
| Competitor has already addressed it | ×1.2 urgency boost |
| High / critical severity | +2.0 |
| Stale content (>45 days) | ×0.7 penalty |
| High-intent query weight | +credibility bonus |

Tier thresholds were recalibrated from 15.0 / 8.0 → **6.5 / 3.5** to produce actionable results in single-source (HN-only) runs. With Reddit + App Store + G2, themes reach Tier 1 naturally.

---

## Before vs After: Mock Run Results

Same 8 fixture items, pipeline run before and after the architectural improvements:

### Before
```
114 items fetched  →  20 relevant (17.5% pass rate)  →  7 themes

  Tier 1 (Verified):   0  ✗
  Tier 2 (Emerging):   0  ✗
  Tier 3 (Unverified): 7

  Top confidence score: 4.11  (threshold was 8.0 — mathematically unreachable)
```

### After
```
144 items fetched  →  24 relevant (16.7% pass rate)  →  11 themes

  Tier 1 (Verified):   0
  Tier 2 (Emerging):   6  ✅
  Tier 3 (Unverified): 5

  Tier 2 themes found:
    • Offline Mode Unreliable           score: 6.25  (2 mentions)
    • App Performance And Bloat         score: 4.08  (3 mentions)
    • Weak Real-Time Collaboration      score: 4.83  (1 mention)
    • Setup And Maintenance Overhead    score: 4.83  (1 mention)
    • Fragmented Workflow Across Tools  score: 4.23  (1 mention)
    • Fragmented Workflow (Tasks)       score: 3.94  (2 mentions)
```

> Tier 1 requires cross-source confirmation (G2 + HN + Reddit). With mock data (HN-only), Tier 2 is the ceiling — which is the correct behaviour.

---

## Human Review Gate

Before writing the final report, the pipeline pauses and shows you the Tier 1 findings for confirmation:

```
──────────────────────────────────────────────────
 REVIEW GATE — Tier 1 Findings
──────────────────────────────────────────────────
   1. RICE= 3.4 | Integrations: mcp external tool integration limited
             (3 mentions, 2 sources) ⚠ RICE/RIC divergence (31%)
   2. RICE= 1.8 | Notion AI: ai limited to single page scope
             (2 mentions, 2 sources) ⚠ RICE/RIC divergence (45%)
──────────────────────────────────────────────────
Confirm these findings? (y / n):
```

- `y` → generates report and brief
- `n` → edit `data/overrides.json` to mark items as known/in-progress, then re-run

The ⚠ flag appears when RICE (with effort) and RIC (without effort) scores diverge by >30% — meaning the effort estimate is significantly affecting priority, and a human should double-check it.

---

## PM Overrides

Mark known issues so they don't resurface in future runs:

```json
{
  "overrides": [
    {
      "pain_point_keyword": "offline sync",
      "product_area": "Platform",
      "status": "IN_PROGRESS",
      "note": "Engineering scoped for Q3",
      "provided_by": "hemanth",
      "date": "2026-04-20"
    }
  ]
}
```

---

## Adding More Data Sources

| Source | How to enable |
|---|---|
| Reddit | Add `APIFY_API_KEY` to `.env` |
| App Store reviews | Add `APIFY_API_KEY` to `.env` |
| Play Store reviews | Add `APIFY_API_KEY` to `.env` |
| Custom URLs | Add entries to `_SEED_CATALOGUE` in `tools/seed_url_mapper.py` |
| G2 reviews | WAF-blocked — needs residential proxy or manual CSV export |

---

## Resetting Between Runs

The pipeline remembers what it's already processed via `seen_registry.json`. To start fresh:

```bash
# Clear processed item fingerprints
echo '{}' > data/seen_registry.json

# Also clear cross-run memory (optional)
echo '# PM Agent Memory\n\nNo prior runs.' > data/memory.md
```

---

## Full Pipeline Diagram

```
┌──────────────────────────────────────────────────────────┐
│                    PHASE 2: Collection                    │
│                                                           │
│  HN Algolia (7 queries + 5 seed queries, FREE)  ──┐      │
│  Firecrawl Seed URLs (2, budget-capped)          ─┼──────│
│  G2 / Reddit / App Store (optional, API keys)   ─┘      │
└─────────────────────┬────────────────────────────────────┘
                      │
              semantic_dedup()       ← remove near-duplicates
              dedup_cross_run()      ← skip already-seen items
                      │
┌─────────────────────▼────────────────────────────────────┐
│              PHASE 3: Research Agent (Haiku)              │
│   Binary filter + intent-aware relevance per item         │
└─────────────────────┬────────────────────────────────────┘
                      │ ~20–30% pass rate
┌─────────────────────▼────────────────────────────────────┐
│              PHASE 4: Synthesis (Sonnet)                  │
│   Extract pain points → harmonize labels → cluster        │
└─────────────────────┬────────────────────────────────────┘
                      │
┌─────────────────────▼────────────────────────────────────┐
│              PHASE 5: Validation + Scoring                │
│   Changelog check → effort estimate → RICE/RIC score      │
└─────────────────────┬────────────────────────────────────┘
                      │
               Human Review Gate
                      │
┌─────────────────────▼────────────────────────────────────┐
│              PHASE 6: Output                              │
│      report.md   │   brief.md   │   run_data.json         │
└──────────────────────────────────────────────────────────┘
```

---

## Models Used

| Agent | Model | Why |
|---|---|---|
| Research (filter) | `claude-haiku-4-5` | Fast and cheap — binary yes/no decisions |
| Synthesis (extract) | `claude-sonnet-4-6` | Nuanced pain point extraction |
| Harmonization | `claude-haiku-4-5` | Label merging — straightforward pattern matching |
| Validation | `claude-sonnet-4-6` | Changelog comparison requires precision |
| Scoring (effort) | `claude-sonnet-4-6` | Effort estimation needs domain reasoning |
