"""Point-in-time and decimal-safe NAV validation tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from market_core.funds.validation import FundNav, fund_nav_from_dict, premium_rate, validate_nav


def _nav(**overrides: object) -> FundNav:
    values: dict[str, object] = {
        "unified_code": "518880.SH",
        "date": "2026-08-13",
        "nav": Decimal("1.20"),
        "inav": Decimal("1.25"),
        "event_time": datetime(2026, 8, 13, 8, 0, tzinfo=UTC),
        "publish_time": datetime(2026, 8, 13, 9, 0, tzinfo=UTC),
        "ingest_time": datetime(2026, 8, 13, 9, 1, tzinfo=UTC),
        "available_time": datetime(2026, 8, 13, 9, 2, tzinfo=UTC),
        "processing_time": datetime(2026, 8, 13, 9, 3, tzinfo=UTC),
        "raw_object_id": "sha256:nav-evidence",
        "source": "provider-x",
    }
    values.update(overrides)
    return FundNav(**values)  # type: ignore[arg-type]


def test_fund_nav_preserves_decimal_values_and_all_point_in_time_timestamps() -> None:
    nav = fund_nav_from_dict(
        {
            "unifiedCode": "518880.SH",
            "date": "2026-08-13",
            "nav": Decimal("0.1"),
            "inav": "0.3",
            "eventTime": "2026-08-13T08:00:00Z",
            "publishTime": "2026-08-13T09:00:00+00:00",
            "ingestTime": "2026-08-13T09:01:00+00:00",
            "availableTime": "2026-08-13T09:02:00+00:00",
            "processingTime": "2026-08-13T09:03:00+00:00",
            "rawObjectId": "sha256:nav-evidence",
            "source": "provider-x",
        }
    )

    assert nav.nav == Decimal("0.1")
    assert nav.inav == Decimal("0.3")
    assert nav.available_time.tzinfo is not None
    assert nav.raw_object_id == "sha256:nav-evidence"


def test_fund_nav_rejects_binary_float_at_decimal_boundary() -> None:
    with pytest.raises(TypeError, match="float is not an accepted decimal boundary value"):
        fund_nav_from_dict(
            {
                "unifiedCode": "518880.SH",
                "date": "2026-08-13",
                "nav": 0.1 + 0.2,
                "inav": None,
                "eventTime": "2026-08-13T08:00:00Z",
                "publishTime": "2026-08-13T09:00:00Z",
                "ingestTime": "2026-08-13T09:01:00Z",
                "availableTime": "2026-08-13T09:02:00Z",
                "processingTime": "2026-08-13T09:03:00Z",
                "rawObjectId": "sha256:nav-evidence",
                "source": "provider-x",
            }
        )


def test_validate_nav_rejects_naive_timestamps() -> None:
    nav = _nav(event_time=datetime(2026, 8, 13, 8, 0))

    result = validate_nav(
        nav,
        today=date(2026, 8, 13),
        now=datetime(2026, 8, 13, 12, 0, tzinfo=UTC),
    )

    assert result.valid is False
    assert any(issue.kind == "NAIVE_TIMESTAMP" for issue in result.issues)


def test_validate_nav_rejects_future_available_data() -> None:
    nav = _nav(available_time=datetime(2026, 8, 14, 9, 0, tzinfo=UTC))

    result = validate_nav(
        nav,
        today=date(2026, 8, 13),
        now=datetime(2026, 8, 13, 12, 0, tzinfo=UTC),
    )

    assert result.valid is False
    assert any(issue.kind == "NOT_YET_AVAILABLE" for issue in result.issues)


def test_validate_nav_requires_available_time_before_processing_time() -> None:
    nav = _nav(
        available_time=datetime(2026, 8, 13, 10, 0, tzinfo=UTC),
        processing_time=datetime(2026, 8, 13, 9, 0, tzinfo=UTC),
    )

    result = validate_nav(
        nav,
        today=date(2026, 8, 13),
        now=datetime(2026, 8, 13, 12, 0, tzinfo=UTC),
    )

    assert result.valid is False
    assert any(issue.kind == "INVALID_TIMESTAMP_ORDER" for issue in result.issues)


def test_premium_rate_returns_exact_decimal_and_rejects_non_positive_nav() -> None:
    nav = _nav(nav=Decimal("1.20"))
    assert premium_rate(nav, Decimal("1.32")) == Decimal("0.1")

    with pytest.raises(ValueError, match="nav must be > 0"):
        premium_rate(_nav(nav=Decimal("0")), Decimal("1.32"))
