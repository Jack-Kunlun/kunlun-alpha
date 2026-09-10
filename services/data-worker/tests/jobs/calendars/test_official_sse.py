"""Acceptance tests for the narrow SSE 2026 holiday raw-first job."""

from __future__ import annotations

import json
import traceback
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any, cast

import pytest
from ashare_contracts.calendar_holiday import Reason
from data_worker.jobs.calendars.official_sse import (
    SSE_2026_ANNOUNCEMENT_URL,
    SSE_CALENDAR_SOURCE,
    SSE_CAPTURE_STATE_SOURCE,
    SSE_PARSER_VERSION,
    SSE_RECEIPT_SOURCE,
    OfficialSseCalendarError,
    OfficialSseResponse,
    SseOfficialCalendarCollector,
    parse_sse_2026_announcement,
    replay_sse_calendar,
)
from data_worker.jobs.calendars.official_sse_runtime import main
from data_worker.jobs.calendars.repository import InMemoryCalendarRepository
from data_worker.raw import LocalFileStorage, RawObjectManifest, RawStorage

_OBSERVED_AT = datetime(2026, 1, 2, 9, 30, tzinfo=UTC)

_OFFICIAL_HTML_TEXT = """
<html>
  <head><title>关于上海证券交易所2026年部分节假日休市安排的通知</title></head>
  <body>
    <h1>关于上海证券交易所2026年部分节假日休市安排的通知</h1>
    <p>上证公告〔2025〕45号</p>
    <p>发布日期：2025-12-22</p>
    <p>上海证券交易所</p>
    <p>一、休市安排</p>
    <p>（一）元旦：1月1日（星期四）至1月3日（星期六）休市，1月5日（星期一）起照常开市。另外，1月4日（星期日）为周末休市。</p>
    <p>（二）春节：2月15日（星期日）至2月23日（星期一）休市，2月24日（星期二）起照常开市。另外，2月14日（星期六）、2月28日（星期六）为周末休市。</p>
    <p>（三）清明节：4月4日（星期六）至4月6日（星期一）休市，4月7日（星期二）起照常开市。</p>
    <p>（四）劳动节：5月1日（星期五）至5月5日（星期二）休市，5月6日（星期三）起照常开市。另外，5月9日（星期六）为周末休市。</p>
    <p>（五）端午节：6月19日（星期五）至6月21日（星期日）休市，6月22日（星期一）起照常开市。</p>
    <p>（六）中秋节：9月25日（星期五）至9月27日（星期日）休市，9月28日（星期一）起照常开市。</p>
    <p>（七）国庆节：10月1日（星期四）至10月7日（星期三）休市，10月8日（星期四）起照常开市。另外，9月20日（星期日）、10月10日（星期六）为周末休市。</p>
    <p>二、有关清算事宜，根据中国证券登记结算有限责任公司的安排进行。</p>
    <p>三、有关春节、国庆节测试事宜，本所将另行通知。</p>
  </body>
</html>
"""
_OFFICIAL_HTML = _OFFICIAL_HTML_TEXT.encode("utf-8")


def _wrong_announcement_number(body: str) -> str:
    return body.replace("上证公告〔2025〕45号", "上证公告〔2025〕46号")


def _wrong_announcement_date(body: str) -> str:
    return body.replace("2025-12-22", "2025-12-23")


def _duplicate_spring_section(body: str) -> str:
    return body.replace("（二）春节：", "（二）春节：2月15日休市。（二）春节：")


def _wrong_dragon_boat_start(body: str) -> str:
    return body.replace("6月19日", "6月18日")


def _wrong_national_section(body: str) -> str:
    return body.replace("（七）国庆节：", "（八）国庆节：")


def _wrong_top_level_section(body: str) -> str:
    return body.replace("二、有关清算事宜", "二、其他事宜")


def _extra_child_section(body: str) -> str:
    return body.replace("二、有关清算事宜", "（八）额外：1月6日休市。二、有关清算事宜")


def _extra_top_level_section(body: str) -> str:
    return body.replace(
        "三、有关春节、国庆节测试事宜", "四、其他安排。三、有关春节、国庆节测试事宜"
    )


_INVALID_HTML_MUTATIONS: tuple[Callable[[str], str], ...] = (
    _wrong_announcement_number,
    _wrong_announcement_date,
    _duplicate_spring_section,
    _wrong_dragon_boat_start,
    _wrong_national_section,
    _wrong_top_level_section,
    _extra_child_section,
    _extra_top_level_section,
)


class FakeTransport:
    def __init__(self, response: OfficialSseResponse | Exception) -> None:
        self.response = response
        self.calls: list[tuple[str, float, int]] = []

    def fetch(self, url: str, *, timeout_seconds: float, max_bytes: int) -> OfficialSseResponse:
        self.calls.append((url, timeout_seconds, max_bytes))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FailOnceReceiptStorage:
    def __init__(self, delegate: LocalFileStorage) -> None:
        self.delegate = delegate
        self.fail_receipt = True

    def put(self, *args: Any, **kwargs: Any) -> RawObjectManifest:
        source = kwargs.get("source", args[0] if args else None)
        if source == SSE_RECEIPT_SOURCE and self.fail_receipt:
            self.fail_receipt = False
            raise RuntimeError("receipt-storage-secret")
        return self.delegate.put(*args, **kwargs)

    def get(self, object_id: str, *, checksum: str | None = None, size: int | None = None) -> bytes:
        return self.delegate.get(object_id, checksum=checksum, size=size)

    def list(self, source: str, date: str) -> list[RawObjectManifest]:
        return self.delegate.list(source, date)

    def find_capture(self, *, market_run_id: str, capture_ordinal: int) -> RawObjectManifest | None:
        return self.delegate.find_capture(
            market_run_id=market_run_id,
            capture_ordinal=capture_ordinal,
        )


def _collector(
    tmp_path: Path,
    response: OfficialSseResponse | Exception,
    repository: InMemoryCalendarRepository | None = None,
) -> tuple[
    SseOfficialCalendarCollector, LocalFileStorage, InMemoryCalendarRepository, FakeTransport
]:
    raw = LocalFileStorage(tmp_path / "raw")
    repo = repository or InMemoryCalendarRepository()
    transport = FakeTransport(response)
    collector = SseOfficialCalendarCollector(
        raw,
        repo,
        transport=transport,
        clock=lambda: _OBSERVED_AT,
    )
    return collector, raw, repo, transport


def test_parser_strictly_maps_only_19_weekdays_to_public_holidays() -> None:
    holidays = parse_sse_2026_announcement(_OFFICIAL_HTML)

    assert len(holidays) == 19
    assert all(item.exchange.value == "SH" for item in holidays)
    assert all(item.reason is Reason.public_holiday for item in holidays)
    assert all(item.note is None for item in holidays)
    assert [item.date.isoformat() for item in holidays] == [
        "2026-01-01",
        "2026-01-02",
        "2026-02-16",
        "2026-02-17",
        "2026-02-18",
        "2026-02-19",
        "2026-02-20",
        "2026-02-23",
        "2026-04-06",
        "2026-05-01",
        "2026-05-04",
        "2026-05-05",
        "2026-06-19",
        "2026-09-25",
        "2026-10-01",
        "2026-10-02",
        "2026-10-05",
        "2026-10-06",
        "2026-10-07",
    ]
    assert "2026-01-04" not in {item.date.isoformat() for item in holidays}
    assert "2026-02-14" not in {item.date.isoformat() for item in holidays}


@pytest.mark.parametrize(
    "mutation",
    _INVALID_HTML_MUTATIONS,
)
def test_parser_rejects_changed_or_incomplete_official_shape(
    mutation: Callable[[str], str],
) -> None:
    with pytest.raises(OfficialSseCalendarError) as error:
        parse_sse_2026_announcement(mutation(_OFFICIAL_HTML_TEXT).encode("utf-8"))

    assert str(error.value) == "official SSE calendar announcement is invalid"
    assert error.value.__context__ is None


def test_collector_is_raw_first_and_persists_a_provenance_only_receipt(tmp_path: Path) -> None:
    collector, raw, repository, transport = _collector(
        tmp_path,
        OfficialSseResponse(
            status_code=200, content_type="text/html; charset=utf-8", body=_OFFICIAL_HTML
        ),
    )

    result = collector.collect()

    assert transport.calls == [(SSE_2026_ANNOUNCEMENT_URL, 10.0, 512 * 1024)]
    assert result.exchange == "SH"
    assert result.year == 2026
    assert result.holiday_count == 19
    assert result.coverage_status == "UNKNOWN"
    assert result.parser_version == SSE_PARSER_VERSION
    assert result.available_at == _OBSERVED_AT
    assert result.operation_id.startswith(f"{result.capture_id}:")
    assert result.raw_checksum == result.raw_object_id
    assert repository.latest_version_id(SSE_CALENDAR_SOURCE, "SH", 2026) == result.version_id

    captures = raw.list(SSE_CALENDAR_SOURCE, "2026-01-02")
    assert len(captures) == 1
    assert raw.get(
        captures[0].object_id, checksum=captures[0].checksum, size=len(_OFFICIAL_HTML)
    ) == (_OFFICIAL_HTML)
    states = raw.list(SSE_CAPTURE_STATE_SOURCE, "2026-01-02")
    assert len(states) == 1
    state = json.loads(raw.get(states[0].object_id, checksum=states[0].checksum))
    assert set(state) == {
        "capture_id",
        "raw_object_id",
        "raw_checksum",
        "raw_size",
        "raw_date",
        "exchange",
        "year",
        "status_code",
        "redirected",
        "content_type",
        "replay_allowed",
    }
    assert state["capture_id"] == result.capture_id
    assert state["raw_checksum"] == result.raw_checksum
    assert state["status_code"] == 200
    assert state["redirected"] is False
    assert state["content_type"] == "text/html; charset=utf-8"
    assert state["replay_allowed"] is True

    receipts = raw.list(SSE_RECEIPT_SOURCE, "2026-01-02")
    assert len(receipts) == 1
    receipt = json.loads(raw.get(receipts[0].object_id, checksum=receipts[0].checksum))
    assert set(receipt) == {
        "capture_id",
        "raw_object_id",
        "raw_checksum",
        "raw_size",
        "raw_date",
        "exchange",
        "year",
        "parser_version",
        "observed_at",
        "available_at",
        "coverage_status",
        "calendar_version_id",
    }
    assert receipt["capture_id"] == result.capture_id
    assert receipt["exchange"] == "SH"
    assert receipt["year"] == 2026
    assert receipt["coverage_status"] == "UNKNOWN"
    assert receipt["available_at"] == _OBSERVED_AT.isoformat()
    assert "休市" not in receipt
    assert result.receipt_id == receipts[0].capture_id


def test_available_time_is_observed_after_the_response_returns(tmp_path: Path) -> None:
    class CompletionAwareTransport(FakeTransport):
        def __init__(self) -> None:
            super().__init__(
                OfficialSseResponse(
                    status_code=200,
                    content_type="text/html",
                    body=_OFFICIAL_HTML,
                )
            )
            self.completed = False

        def fetch(
            self,
            url: str,
            *,
            timeout_seconds: float,
            max_bytes: int,
        ) -> OfficialSseResponse:
            response = super().fetch(
                url,
                timeout_seconds=timeout_seconds,
                max_bytes=max_bytes,
            )
            self.completed = True
            return response

    transport = CompletionAwareTransport()
    observed_after_response = _OBSERVED_AT + timedelta(minutes=3)

    def clock() -> datetime:
        if not transport.completed:
            raise RuntimeError("clock-before-response-secret")
        return observed_after_response

    raw = LocalFileStorage(tmp_path / "raw")
    repository = InMemoryCalendarRepository()
    result = SseOfficialCalendarCollector(
        raw,
        repository,
        transport=transport,
        clock=clock,
    ).collect(capture_id="capture-after-response")

    assert result.available_at == observed_after_response
    assert result.observed_at == observed_after_response
    manifest = raw.list(SSE_CALENDAR_SOURCE, "2026-01-02")[0]
    assert manifest.available_time == observed_after_response


def test_invalid_scope_is_rejected_before_network_or_raw_write(tmp_path: Path) -> None:
    collector, raw, repository, transport = _collector(
        tmp_path,
        OfficialSseResponse(status_code=200, content_type="text/html", body=_OFFICIAL_HTML),
    )

    with pytest.raises(OfficialSseCalendarError) as error:
        collector.collect("SZ", 2026)

    assert str(error.value) == "official SSE calendar scope is unsupported"
    assert error.value.__context__ is None
    assert transport.calls == []
    assert raw.list(SSE_CALENDAR_SOURCE, "2026-01-02") == []
    assert repository.audit_log() == []


def test_parse_failure_keeps_bounded_raw_capture_and_does_not_save(tmp_path: Path) -> None:
    bad_html = _OFFICIAL_HTML_TEXT.replace("上海证券交易所", "未经核验的发布方").encode("utf-8")
    collector, raw, repository, _transport = _collector(
        tmp_path,
        OfficialSseResponse(status_code=200, content_type="text/html", body=bad_html),
    )

    with pytest.raises(OfficialSseCalendarError) as error:
        collector.collect(capture_id="capture-parse-failure")

    assert str(error.value) == "official SSE calendar announcement is invalid"
    assert error.value.__context__ is None
    captures = raw.list(SSE_CALENDAR_SOURCE, "2026-01-02")
    assert len(captures) == 1
    assert raw.get(captures[0].object_id, checksum=captures[0].checksum) == bad_html
    assert repository.audit_log() == []


def test_non_success_response_is_saved_as_raw_before_controlled_failure(tmp_path: Path) -> None:
    body = b"<html><body>temporary unavailable</body></html>"
    collector, raw, repository, _transport = _collector(
        tmp_path,
        OfficialSseResponse(status_code=503, content_type="text/html", body=body),
    )

    with pytest.raises(OfficialSseCalendarError) as error:
        collector.collect(capture_id="capture-http-failure")

    assert str(error.value) == "official SSE calendar response is unusable"
    assert error.value.__context__ is None
    captures = raw.list(SSE_CALENDAR_SOURCE, "2026-01-02")
    assert len(captures) == 1
    assert raw.get(captures[0].object_id, checksum=captures[0].checksum) == body
    assert repository.audit_log() == []


@pytest.mark.parametrize(
    ("capture_id", "response"),
    [
        (
            "capture-replay-http-failure",
            OfficialSseResponse(
                status_code=503,
                content_type="text/html",
                body=_OFFICIAL_HTML,
            ),
        ),
        (
            "capture-replay-redirect",
            OfficialSseResponse(
                status_code=200,
                content_type="text/html",
                body=_OFFICIAL_HTML,
                redirected=True,
            ),
        ),
        (
            "capture-replay-non-html",
            OfficialSseResponse(
                status_code=200,
                content_type="application/json",
                body=_OFFICIAL_HTML,
            ),
        ),
    ],
)
def test_unusable_response_capture_cannot_be_replayed(
    tmp_path: Path,
    capture_id: str,
    response: OfficialSseResponse,
) -> None:
    collector, raw, repository, _transport = _collector(tmp_path, response)

    with pytest.raises(OfficialSseCalendarError) as collect_error:
        collector.collect(capture_id=capture_id)
    assert str(collect_error.value) == "official SSE calendar response is unusable"
    assert collect_error.value.__context__ is None

    before = repository.audit_log()
    with pytest.raises(OfficialSseCalendarError) as replay_error:
        replay_sse_calendar(
            raw,
            repository,
            capture_id=capture_id,
            date="2026-01-02",
        )
    assert str(replay_error.value) == "official SSE calendar capture integrity failed"
    assert replay_error.value.__context__ is None
    assert repository.audit_log() == before

    states = raw.list("sse-calendar-capture-state", "2026-01-02")
    assert len(states) == 1
    state = json.loads(raw.get(states[0].object_id, checksum=states[0].checksum))
    assert state["capture_id"] == capture_id
    assert state["raw_checksum"] == raw.list(SSE_CALENDAR_SOURCE, "2026-01-02")[0].checksum
    assert state["replay_allowed"] is False


@pytest.mark.parametrize(
    ("capture_id", "response", "expected_code"),
    [
        (
            "capture-redirect",
            OfficialSseResponse(
                status_code=200,
                content_type="text/html",
                body=_OFFICIAL_HTML,
                redirected=True,
            ),
            None,
        ),
        (
            "capture-non-html",
            OfficialSseResponse(
                status_code=200, content_type="application/json", body=_OFFICIAL_HTML
            ),
            None,
        ),
        (
            "capture-oversize",
            OfficialSseResponse(
                status_code=200,
                content_type="text/html",
                body=b"x" * (512 * 1024 + 1),
            ),
            "RESPONSE_TOO_LARGE",
        ),
    ],
)
def test_redirect_non_html_and_oversize_are_fail_closed_and_bounded(
    tmp_path: Path,
    capture_id: str,
    response: OfficialSseResponse,
    expected_code: str | None,
) -> None:
    collector, raw, repository, _transport = _collector(tmp_path, response)

    with pytest.raises(OfficialSseCalendarError) as error:
        collector.collect(capture_id=capture_id)

    assert str(error.value) == "official SSE calendar response is unusable"
    assert error.value.__context__ is None
    captures = raw.list(SSE_CALENDAR_SOURCE, "2026-01-02")
    assert len(captures) == 1
    stored = raw.get(captures[0].object_id, checksum=captures[0].checksum)
    if expected_code is None:
        assert stored == response.body
    else:
        assert json.loads(stored)["error_code"] == expected_code
        assert len(stored) < 256
    assert repository.audit_log() == []


def test_receipt_failure_after_save_is_recoverable_from_the_original_capture(
    tmp_path: Path,
) -> None:
    raw = LocalFileStorage(tmp_path / "raw")
    failing_raw = FailOnceReceiptStorage(raw)
    repository = InMemoryCalendarRepository()
    transport = FakeTransport(
        OfficialSseResponse(status_code=200, content_type="text/html", body=_OFFICIAL_HTML)
    )
    collector = SseOfficialCalendarCollector(
        cast(RawStorage, failing_raw),
        repository,
        transport=transport,
        clock=lambda: _OBSERVED_AT,
    )

    with pytest.raises(OfficialSseCalendarError) as error:
        collector.collect(capture_id="capture-receipt-retry")

    assert str(error.value) == "official SSE calendar receipt failed"
    assert error.value.__context__ is None
    assert len(repository.audit_log()) == 1
    assert raw.list(SSE_RECEIPT_SOURCE, "2026-01-02") == []

    recovered = replay_sse_calendar(
        cast(RawStorage, failing_raw),
        repository,
        capture_id="capture-receipt-retry",
        date="2026-01-02",
    )
    assert recovered.version_id == repository.latest_version_id(SSE_CALENDAR_SOURCE, "SH", 2026)
    assert len(raw.list(SSE_RECEIPT_SOURCE, "2026-01-02")) == 1


def test_existing_receipt_without_operation_is_rejected_before_collect_save(
    tmp_path: Path,
) -> None:
    raw = LocalFileStorage(tmp_path / "raw")
    original_repository = InMemoryCalendarRepository()
    collector, _raw, _repository, _transport = _collector(
        tmp_path,
        OfficialSseResponse(status_code=200, content_type="text/html", body=_OFFICIAL_HTML),
        original_repository,
    )
    first = collector.collect(capture_id="capture-existing-receipt")

    replacement_repository = InMemoryCalendarRepository()
    replacement_collector = SseOfficialCalendarCollector(
        raw,
        replacement_repository,
        transport=FakeTransport(
            OfficialSseResponse(status_code=200, content_type="text/html", body=_OFFICIAL_HTML)
        ),
        clock=lambda: _OBSERVED_AT,
    )
    with pytest.raises(OfficialSseCalendarError) as error:
        replacement_collector.collect(capture_id=first.capture_id)

    assert str(error.value) == "official SSE calendar capture integrity failed"
    assert error.value.__context__ is None
    assert replacement_repository.audit_log() == []


def test_existing_receipt_without_operation_is_rejected_before_replay_save(
    tmp_path: Path,
) -> None:
    collector, raw, _repository, _transport = _collector(
        tmp_path,
        OfficialSseResponse(status_code=200, content_type="text/html", body=_OFFICIAL_HTML),
    )
    first = collector.collect(capture_id="capture-replay-existing-receipt")
    replacement_repository = InMemoryCalendarRepository()

    with pytest.raises(OfficialSseCalendarError) as error:
        replay_sse_calendar(
            raw,
            replacement_repository,
            capture_id=first.capture_id,
            date=first.raw_date,
        )

    assert str(error.value) == "official SSE calendar capture integrity failed"
    assert error.value.__context__ is None
    assert replacement_repository.audit_log() == []


def test_untrusted_timezone_failure_has_no_secret_exception_context(tmp_path: Path) -> None:
    class SecretTimezone(tzinfo):
        def utcoffset(self, value: datetime | None) -> timedelta:
            del value
            raise RuntimeError("untrusted-timezone-secret")

        def dst(self, value: datetime | None) -> timedelta:
            del value
            return timedelta(0)

    collector, raw, repository, transport = _collector(
        tmp_path,
        OfficialSseResponse(status_code=200, content_type="text/html", body=_OFFICIAL_HTML),
    )
    collector = SseOfficialCalendarCollector(
        raw,
        repository,
        transport=transport,
        clock=lambda: datetime(2026, 1, 2, tzinfo=SecretTimezone()),
    )

    with pytest.raises(OfficialSseCalendarError) as error:
        collector.collect(capture_id="capture-timezone-failure")

    assert str(error.value) == "official SSE calendar observation time is invalid"
    assert error.value.__context__ is None
    assert "untrusted-timezone-secret" not in "".join(traceback.format_exception(error.value))
    assert raw.list(SSE_CALENDAR_SOURCE, "2026-01-02") == []
    assert len(transport.calls) == 1


def test_one_shot_cli_requires_explicit_raw_root_and_does_not_echo_dsn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("KUNLUN_RAW_ROOT", raising=False)
    monkeypatch.delenv("KUNLUN_POSTGRES_DSN", raising=False)

    assert main([]) == 1
    first = capsys.readouterr()
    assert first.err == "official SSE calendar raw root is required\n"

    assert main(["--raw-root", str(tmp_path / "raw")]) == 1
    second = capsys.readouterr()
    assert second.err == "official SSE calendar database is unavailable\n"
    assert "postgres" not in second.err.lower()


def test_network_failure_writes_safe_attempt_evidence_without_exception_context(
    tmp_path: Path,
) -> None:
    collector, raw, repository, _transport = _collector(
        tmp_path,
        RuntimeError("untrusted-network-secret"),
    )

    with pytest.raises(OfficialSseCalendarError) as error:
        collector.collect(capture_id="capture-network-failure")

    assert str(error.value) == "official SSE calendar request failed"
    assert error.value.__context__ is None
    assert "untrusted-network-secret" not in str(error.value)
    assert "untrusted-network-secret" not in "".join(traceback.format_exception(error.value))
    captures = raw.list(SSE_CALENDAR_SOURCE, "2026-01-02")
    assert len(captures) == 1
    attempt = raw.get(captures[0].object_id, checksum=captures[0].checksum)
    assert json.loads(attempt) == {
        "capture_id": "capture-network-failure",
        "error_code": "NETWORK_FAILURE",
        "exchange": "SH",
        "kind": "attempt",
        "source": SSE_CALENDAR_SOURCE,
        "year": 2026,
    }
    assert repository.audit_log() == []


def test_same_capture_is_idempotent_but_same_bytes_with_new_capture_is_new_event(
    tmp_path: Path,
) -> None:
    response = OfficialSseResponse(status_code=200, content_type="text/html", body=_OFFICIAL_HTML)
    collector, raw, repository, _transport = _collector(tmp_path, response)

    first = collector.collect(capture_id="capture-a")
    retry = collector.collect(capture_id="capture-a")
    second = collector.collect(capture_id="capture-b")

    assert retry.version_id == first.version_id
    assert retry.receipt_id == first.receipt_id
    assert second.capture_id != first.capture_id
    assert second.version_id != first.version_id
    assert second.raw_object_id == first.raw_object_id
    assert {manifest.capture_id for manifest in raw.list(SSE_CALENDAR_SOURCE, "2026-01-02")} == {
        "capture-a",
        "capture-b",
    }
    assert len(repository.audit_log()) == 2


def test_replay_uses_original_capture_without_network_and_rejects_wrong_capture_or_date(
    tmp_path: Path,
) -> None:
    collector, raw, repository, _transport = _collector(
        tmp_path,
        OfficialSseResponse(status_code=200, content_type="text/html", body=_OFFICIAL_HTML),
    )
    first = collector.collect(capture_id="capture-replay")

    class NoNetworkTransport:
        def fetch(self, url: str, *, timeout_seconds: float, max_bytes: int) -> OfficialSseResponse:
            raise AssertionError("replay must not fetch")

    replayed = replay_sse_calendar(
        raw,
        repository,
        capture_id="capture-replay",
        date="2026-01-02",
        exchange="SH",
        year=2026,
    )
    assert replayed.version_id == first.version_id
    assert replayed.receipt_id == first.receipt_id

    del NoNetworkTransport
    before = repository.audit_log()
    with pytest.raises(OfficialSseCalendarError) as error:
        replay_sse_calendar(
            raw,
            repository,
            capture_id="capture-missing",
            date="2026-01-02",
            exchange="SH",
            year=2026,
        )
    assert str(error.value) == "official SSE calendar capture is unavailable"
    assert error.value.__context__ is None
    assert repository.audit_log() == before

    with pytest.raises(OfficialSseCalendarError) as error:
        replay_sse_calendar(
            raw,
            repository,
            capture_id="capture-replay",
            date="2026-01-03",
            exchange="SH",
            year=2026,
        )
    assert str(error.value) == "official SSE calendar capture is unavailable"
    assert error.value.__context__ is None
    assert repository.audit_log() == before
