"""Deterministic, offline text-similarity proxies for near-duplicate detection.

V1 similarity is an explicit, deterministic *textual* similarity proxy — it is
**not** model-based semantic understanding, and this module never uses an LLM,
an online embedding, a remote model or any network call. It uses character
n-gram shingles plus a Jaccard set overlap, which works for Chinese, English,
digits and common punctuation without relying on whitespace tokenization (a
whitespace tokenizer would be wrong for Chinese).

All scores are quantized to integer basis points in ``[0, 10000]`` (see
:data:`event_core.dedup.models.BASIS_POINTS_SCALE`) so that a threshold
comparison is deterministic across platforms and never drifts on a float
epsilon at the boundary.
"""

from __future__ import annotations

from event_core.dedup.models import BASIS_POINTS_SCALE


def ngram_shingles(text: str, ngram_size: int) -> frozenset[str]:
    """Character n-gram shingles of ``text`` (deterministic, order-free set).

    Whitespace is collapsed to a single space first so that incidental spacing
    differences do not change the shingle set. If the text is shorter than
    ``ngram_size`` the whole (collapsed) text is a single shingle, so short
    strings still compare meaningfully. An empty text yields the empty set.
    """
    if ngram_size < 1:
        raise ValueError("ngram_size must be >= 1")
    collapsed = " ".join(text.split())
    if not collapsed:
        return frozenset()
    if len(collapsed) <= ngram_size:
        return frozenset({collapsed})
    return frozenset(collapsed[i : i + ngram_size] for i in range(len(collapsed) - ngram_size + 1))


def jaccard_bps(left: frozenset[str], right: frozenset[str]) -> int:
    """Jaccard overlap of two shingle sets, quantized to integer basis points.

    ``|A ∩ B| / |A ∪ B|`` scaled to ``[0, 10000]``. Two empty sets are defined
    as ``0`` (no positive evidence), never ``1`` — an absence of content is
    never treated as a match, fail-closed. The computation is integer-exact
    (multiply before divide, banker-free ``round``) so the result is identical
    on every platform.
    """
    if not left and not right:
        return 0
    intersection = len(left & right)
    union = len(left | right)
    if union == 0:
        return 0
    return round(BASIS_POINTS_SCALE * intersection / union)


def title_similarity_bps(left: str, right: str, ngram_size: int) -> int:
    """Character n-gram Jaccard similarity of two titles, in basis points."""
    return jaccard_bps(ngram_shingles(left, ngram_size), ngram_shingles(right, ngram_size))


def body_similarity_bps(left: str, right: str, ngram_size: int) -> int:
    """Character n-gram Jaccard similarity of two bodies, in basis points."""
    return jaccard_bps(ngram_shingles(left, ngram_size), ngram_shingles(right, ngram_size))
