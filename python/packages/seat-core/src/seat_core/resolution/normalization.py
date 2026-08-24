"""Deterministic name normalization and standard-library similarity."""

from __future__ import annotations

import unicodedata
from decimal import ROUND_HALF_UP, Decimal, localcontext

from seat_core.resolution.models import NormalizationPolicy


def normalize_alias_name_parts(name: str, policy: NormalizationPolicy) -> tuple[str, bool]:
    if type(name) is not str or not name.strip():
        raise ValueError("name must be a non-empty string")
    value = unicodedata.normalize("NFKC", name) if policy.use_nfkc else name
    if policy.use_casefold:
        value = value.casefold()
    if policy.remove_whitespace:
        value = "".join(value.split())
    suffixes = tuple(
        "".join(unicodedata.normalize("NFKC", suffix).casefold().split())
        for suffix in policy.strip_common_suffixes
    )
    for suffix in sorted(suffixes, key=len, reverse=True):
        if value.endswith(suffix) and len(value) > len(suffix):
            return value[: -len(suffix)], True
    return value, False


def normalize_alias_name(name: str, policy: NormalizationPolicy) -> str:
    """Return the canonical comparison key; never use it as a seat id."""

    value, _ = normalize_alias_name_parts(name, policy)
    return value


def edit_similarity(left: str, right: str) -> Decimal:
    """Return deterministic normalized Levenshtein similarity in [0, 1]."""

    if not left or not right:
        return Decimal("0.0000")
    if left == right:
        return Decimal("1.0000")
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            insertion = current[right_index - 1] + 1
            deletion = previous[right_index] + 1
            substitution = previous[right_index - 1] + (left_char != right_char)
            current.append(min(insertion, deletion, substitution))
        previous = current
    distance = previous[-1]
    denominator = len(left)
    with localcontext() as context:
        context.prec = max(28, denominator * 2)
        score = Decimal(denominator - distance) / Decimal(denominator)
    return score.quantize(Decimal("0.0000"), rounding=ROUND_HALF_UP)


__all__ = ["edit_similarity", "normalize_alias_name", "normalize_alias_name_parts"]
