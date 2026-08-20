"""Yesterday-limit premium and loss-making effect.

Measures how yesterday's limit-up (or multi-board) pool performs today. The
sample is unbiased and point-in-time correct: suspended instruments (no data),
one-word boards (opening already at limit, so no reasonable entry) and any
instrument whose observation is not yet available at the decision instant are
excluded, and every exclusion is recorded with a reason.

P2-R01 (round 2):

* Prices are :class:`PriceObservation` values — :class:`~decimal.Decimal` bound
  to event/availability instants and source/version/evidence provenance.
* ``decision_time`` is a mandatory :class:`Instant`; there is no default that
  would silently admit future data. Both the prior close and today's price must
  be available at or before the decision (fail-closed on missing or leaked
  data). ``available_time == decision_time`` is inclusive.
* Results carry a structured :class:`SampleProvenance` (algorithm version,
  as_of, included/excluded samples with reasons, source versions, evidence
  ids), and drawdown returns a structured result — never a bare float.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from emotion_core.pit import Instant, PriceObservation
from emotion_core.provenance import SampleProvenance

PREMIUM_VERSION = "premium_v1"


@dataclass(frozen=True)
class PremiumResult:
    """Premium / loss-making effect for a pool of yesterday's limit-ups."""

    sample_size: int
    average_premium: Decimal
    win_rate: Decimal
    provenance: SampleProvenance
    version: str = PREMIUM_VERSION


@dataclass(frozen=True)
class DrawdownResult:
    """Average high-to-close drawdown for a pool (loss-making effect)."""

    sample_size: int
    average_drawdown: Decimal
    provenance: SampleProvenance
    version: str = PREMIUM_VERSION


def compute_premium(
    yesterday_pool: list[str],
    yesterday_close: dict[str, PriceObservation],
    today_price: dict[str, PriceObservation],
    *,
    decision_time: Instant,
    suspended: set[str] | None = None,
    one_word_board: set[str] | None = None,
) -> PremiumResult:
    """Average premium of yesterday's pool at today's observation price.

    ``today_price`` may be the open (open-based) or close (close-based); the
    caller decides which observation to pass. Suspended, one-word-board,
    missing and not-yet-available instruments are excluded so the sample is
    unbiased and point-in-time correct.
    """
    suspended = suspended or set()
    one_word_board = one_word_board or set()

    premiums: list[Decimal] = []
    wins = 0
    included: list[str] = []
    excluded: dict[str, str] = {}
    evidence_ids: list[str] = []
    source_versions: set[str] = set()

    for code in yesterday_pool:
        if code in suspended:
            excluded[code] = "suspended"
            continue
        if code in one_word_board:
            excluded[code] = "one_word_board"
            continue
        prev = yesterday_close.get(code)
        price = today_price.get(code)
        if prev is None or price is None:
            excluded[code] = "missing_price"
            continue
        if not prev.available_at(decision_time) or not price.available_at(decision_time):
            excluded[code] = "unavailable_at_decision_time"
            continue
        if prev.value <= 0:
            excluded[code] = "missing_price"
            continue
        premium = price.value / prev.value - Decimal("1")
        premiums.append(premium)
        included.append(code)
        evidence_ids.extend((prev.evidence_id, price.evidence_id))
        source_versions.update((prev.source_version, price.source_version))
        if premium > 0:
            wins += 1

    provenance = SampleProvenance(
        algorithm_version=PREMIUM_VERSION,
        as_of=decision_time.isoformat(),
        included=tuple(included),
        excluded=excluded,
        source_versions=tuple(sorted(source_versions)),
        evidence_ids=tuple(evidence_ids),
    )

    if not premiums:
        return PremiumResult(
            sample_size=0,
            average_premium=Decimal("0"),
            win_rate=Decimal("0"),
            provenance=provenance,
        )

    count = Decimal(len(premiums))
    return PremiumResult(
        sample_size=len(premiums),
        average_premium=sum(premiums, Decimal("0")) / count,
        win_rate=Decimal(wins) / count,
        provenance=provenance,
    )


def compute_drawdown(
    pool: list[str],
    today_high: dict[str, PriceObservation],
    today_close: dict[str, PriceObservation],
    *,
    decision_time: Instant,
    suspended: set[str] | None = None,
) -> DrawdownResult:
    """Average high-to-close drawdown of a pool (loss-making effect).

    ``high`` and ``close`` are independent observations: an instrument is
    included only when *both* are available at the decision instant, so the
    measure never uses a leaked same-day value. Returns a structured, versioned,
    provenance-carrying result rather than a bare float.
    """
    suspended = suspended or set()
    drawdowns: list[Decimal] = []
    included: list[str] = []
    excluded: dict[str, str] = {}
    evidence_ids: list[str] = []
    source_versions: set[str] = set()

    for code in pool:
        if code in suspended:
            excluded[code] = "suspended"
            continue
        high = today_high.get(code)
        close = today_close.get(code)
        if high is None or close is None:
            excluded[code] = "missing_price"
            continue
        if not high.available_at(decision_time) or not close.available_at(decision_time):
            excluded[code] = "unavailable_at_decision_time"
            continue
        if high.value <= 0:
            excluded[code] = "missing_price"
            continue
        drawdowns.append((high.value - close.value) / high.value)
        included.append(code)
        evidence_ids.extend((high.evidence_id, close.evidence_id))
        source_versions.update((high.source_version, close.source_version))

    provenance = SampleProvenance(
        algorithm_version=PREMIUM_VERSION,
        as_of=decision_time.isoformat(),
        included=tuple(included),
        excluded=excluded,
        source_versions=tuple(sorted(source_versions)),
        evidence_ids=tuple(evidence_ids),
    )

    if not drawdowns:
        return DrawdownResult(
            sample_size=0,
            average_drawdown=Decimal("0"),
            provenance=provenance,
        )

    return DrawdownResult(
        sample_size=len(drawdowns),
        average_drawdown=sum(drawdowns, Decimal("0")) / Decimal(len(drawdowns)),
        provenance=provenance,
    )
