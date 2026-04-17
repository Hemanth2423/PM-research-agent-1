from __future__ import annotations
"""Semantic deduplication: removes near-duplicate items before the research agent.

Default approach (Approach B): TF-IDF cosine similarity via scikit-learn (~50MB).
Optional upgrade (Approach A): sentence-transformers all-MiniLM-L6-v2 (~420MB).
  Install with: pip install sentence-transformers
  Then pass approach="sentence_transformers" to semantic_dedup().

Both approaches use the same interface and the same similarity threshold.
The module gracefully degrades: if the required library is missing, it logs a
warning and returns items unchanged.
"""
import logging

logger = logging.getLogger(__name__)

# Items with cosine similarity above this threshold are considered near-duplicates.
# 0.85 keeps distinct-but-related complaints separate; lower = more aggressive dedup.
SIMILARITY_THRESHOLD = 0.85


def _dedup_tfidf(items: list[dict], text_field: str) -> list[dict]:
    """Approach B: TF-IDF cosine similarity (scikit-learn). Lightweight default."""
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError:
        logger.warning(
            "scikit-learn not installed — skipping semantic dedup. "
            "Install with: pip install scikit-learn"
        )
        return items

    texts = [str(item.get(text_field, "") or "")[:1000] for item in items]
    if len(texts) < 2:
        return items

    try:
        vectorizer = TfidfVectorizer(
            max_features=5000,
            stop_words="english",
            ngram_range=(1, 2),
            min_df=1,
        )
        tfidf_matrix = vectorizer.fit_transform(texts)
    except ValueError as e:
        logger.warning(f"TF-IDF vectorization failed ({e}) — skipping semantic dedup")
        return items

    sim_matrix = cosine_similarity(tfidf_matrix)

    removed: set[int] = set()
    for i in range(len(items)):
        if i in removed:
            continue
        for j in range(i + 1, len(items)):
            if j in removed:
                continue
            if sim_matrix[i, j] >= SIMILARITY_THRESHOLD:
                # Keep the richer item (longer text = more signal)
                len_i = len(texts[i])
                len_j = len(texts[j])
                removed.add(j if len_i >= len_j else i)

    result = [item for idx, item in enumerate(items) if idx not in removed]
    if removed:
        logger.info(
            f"Semantic dedup (TF-IDF): removed {len(removed)} near-duplicates "
            f"from {len(items)} items → {len(result)} remain"
        )
    return result


def _dedup_sentence_transformers(items: list[dict], text_field: str) -> list[dict]:
    """Approach A: sentence-transformers (all-MiniLM-L6-v2).

    Higher semantic precision than TF-IDF but requires torch (~2GB).
    Falls back to TF-IDF if sentence-transformers is not installed.
    """
    try:
        from sentence_transformers import SentenceTransformer
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError:
        logger.warning(
            "sentence-transformers not installed — falling back to TF-IDF dedup. "
            "Install with: pip install sentence-transformers"
        )
        return _dedup_tfidf(items, text_field)

    texts = [str(item.get(text_field, "") or "")[:500] for item in items]
    if len(texts) < 2:
        return items

    model = SentenceTransformer("all-MiniLM-L6-v2")
    embeddings = model.encode(texts, show_progress_bar=False)
    sim_matrix = cosine_similarity(embeddings)

    removed: set[int] = set()
    for i in range(len(items)):
        if i in removed:
            continue
        for j in range(i + 1, len(items)):
            if j in removed:
                continue
            if sim_matrix[i, j] >= SIMILARITY_THRESHOLD:
                len_i = len(texts[i])
                len_j = len(texts[j])
                removed.add(j if len_i >= len_j else i)

    result = [item for idx, item in enumerate(items) if idx not in removed]
    if removed:
        logger.info(
            f"Semantic dedup (sentence-transformers): removed {len(removed)} near-duplicates "
            f"from {len(items)} items → {len(result)} remain"
        )
    return result


def semantic_dedup(
    items: list[dict],
    text_field: str = "raw_text",
    approach: str = "tfidf",
) -> list[dict]:
    """Remove semantically near-duplicate items before the research agent.

    Call this after dedup_within_run() and before dedup_cross_run() so that
    hash dedup removes exact duplicates first (cheapest), then semantic dedup
    trims near-duplicates, and finally cross-run dedup checks persistent history.

    Args:
        items:       List of item dicts. Must contain text_field.
        text_field:  Field to compare. "raw_text" works before the research agent;
                     "cleaned_text" works after. Default: "raw_text".
        approach:    "tfidf" (default, Approach B — scikit-learn)
                     "sentence_transformers" (Approach A — torch, optional).

    Returns:
        Deduplicated list preserving order of first occurrence.
    """
    if len(items) < 2:
        return items

    if approach == "sentence_transformers":
        return _dedup_sentence_transformers(items, text_field)
    return _dedup_tfidf(items, text_field)
