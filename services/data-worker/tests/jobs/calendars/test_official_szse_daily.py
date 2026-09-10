"""Offline contract tests for the SZSE direct-daily calendar provider."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import calendar
import hashlib
import json
import traceback
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Barrier, Lock
from typing import cast
from uuid import UUID

import data_worker.jobs.calendars.official_szse_daily as official_szse_daily
import pytest
from data_worker.jobs.calendars.official_szse_daily import (
    SZSE_CALENDAR_CONCATVERSION_URL,
    SZSE_CALENDAR_JS_URL,
    SZSE_CALENDAR_ROOT_URL,
    SZSE_CALENDAR_SOURCE,
    SZSE_DIRECT_DAILY_URL_TEMPLATE,
    SZSE_RUN_LEDGER_DATE,
    SZSE_RUN_LEDGER_SOURCE,
    OfficialSzseCalendarError,
    OfficialSzseResponse,
    SzseOfficialCalendarCollector,
    SzseOfficialDailyResult,
    _CollectionFailureError,
    _parse_identity,
    _parse_root_identity,
    replay_szse_daily_run,
    szse_direct_daily_url,
)
from data_worker.raw import LocalFileStorage
from data_worker.raw.manifest import RawObjectManifest, sanitize_request_identity
from market_core.calendar.scan_run import (
    CalendarScanRunReceipt,
    ScanRunCoverage,
    ScanRunCoverageLevel,
    calendar_scan_run_manifest_member_digest,
    calendar_scan_run_pass_member_digest,
)

_YEAR = 2026
_RUN_ID = UUID(int=42)
_CLOCK_START = datetime(2026, 9, 6, 1, 0, tzinfo=UTC)
_LIVE_PATH_URL_TEMPLATE = "https://www.szse.cn/szsePath.js?random={random_ms}"
_LIVE_CONCAT_URL_TEMPLATE = "https://res.szse.cn/common/js/concatversion.js?random={random_ms}"


def _identity_random_ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _official_root_body() -> bytes:
    return (
        _live_root_body(_identity_random_ms(_CLOCK_START + timedelta(minutes=1))).decode()
    ).encode()


def _official_concatversion_body() -> bytes:
    return (
        b"var szseDomainMap={'resStaticHttps':[domainResStaticHttps,backDomainResStaticHttps]};"
        b"var pathObj={https_file_path:domainBackSwitch('resStaticHttps'),"
        b"report_path:'/api/report'};"
        b"var sjsVersion='1.2.221';"
        b"var isDevModel=false;"
        b"function changeVertion(sUrl,sType){"
        b"var filePath='';"
        b"if(isNotHttps()){filePath=pathObj.https_file_path;}"
        b"else{filePath=pathObj.file_path;}"
        b"if(!isDevModel){var minFlag=(sUrl.indexOf('.min.'+sType)>-1);"
        b"if(!minFlag)sUrl=sUrl.replace('.'+sType,'.min.'+sType);}"
        b"switch(sType){case 'css':break;case 'js':"
        b'var jshref=" <script src=\'"+filePath+sUrl+"?version="+sjsVersion+"\'> <\\/script> ";'
        b"document.write(jshref);break;}}"
    )


def _official_path_body() -> bytes:
    return (
        b"var domainMainHttps='https://www.szse.cn';"
        b"var domainResStaticHttps='https://res.static.szse.cn';"
    )


def _official_js_body() -> bytes:
    return b'const endpoint = pathObj.report_path + "/exchange/onepersistenthour/monthList?month=";'


def _live_root_body(random_ms: int) -> bytes:
    del random_ms
    body = _live_variable_root_body().decode()
    return body.replace(
        "changeVertion('/modules/tradeCalendar/js/tradeCanledar_new.js', 'js');",
        "".join(
            (
                "changeVertion('/modules/layout.js','js');",
                "changeVertion('/modules/theme.css','css');",
                "changeVertion('/modules/tradeCalendar/js/tradeCanledar_new.js','js');",
                "changeVertion('/modules/other.js','js');",
                "changeVertion('/modules/legacy.css','css');",
                "changeVertion('/modules/analytics.js','js');",
            )
        ),
    ).encode()


def _live_variable_root_body() -> bytes:
    """Minimal copy of the observed variable-composition root identity."""

    return """
    <html><body>深圳证券交易所<script>
    (function () {
      var _versionDate = new Date().getTime();
      if (location.protocol == 'https:') {
        var _path = 'https://res.szse.cn';
      } else {
        var _path = 'http://res.static.szse.cn';
      }
      var _host = 'http://www.szse.cn';
      if (location.protocol == 'https:') {
        _host = 'https://www.szse.cn';
      }
      var backDomain = 'http://www.sse.org.cn';
      _path = _path.replace('.static.', '.');
      document.write(
        " <script src='" + _host + "/szsePath.js?random=" + _versionDate
        + "'> <\\/script> "
        + " <script src='" + _path + "/common/js/concatversion.js?random="
        + _versionDate + "'> <\\/script> "
      );
    }());
    changeVertion('/modules/tradeCalendar/js/tradeCanledar_new.js', 'js');
    </script></body></html>
    """.encode()


def test_live_root_variable_url_composition_is_accepted() -> None:
    random_ms = _identity_random_ms(_CLOCK_START + timedelta(minutes=1))
    assert _parse_root_identity(_live_variable_root_body(), random_ms=random_ms) == (
        _LIVE_PATH_URL_TEMPLATE.format(random_ms=random_ms),
        _LIVE_CONCAT_URL_TEMPLATE.format(random_ms=random_ms),
    )


@pytest.mark.parametrize(
    ("endpoint_kind", "mutation"),
    [
        ("root-target", "false && changeVertion"),
        ("root-writer", "if (false) { document.write"),
        ("concat-function", "if(false) {"),
        ("final-expression", "false && pathObj.report_path"),
    ],
)
def test_identity_rejects_unreachable_source_mutations(endpoint_kind: str, mutation: str) -> None:
    random_ms = _identity_random_ms(_CLOCK_START + timedelta(minutes=1))
    with pytest.raises(_CollectionFailureError) as error:
        if endpoint_kind == "root-target":
            body = _live_root_body(random_ms).replace(
                b"changeVertion('/modules/tradeCalendar/js/tradeCanledar_new.js','js');",
                b"false && changeVertion('/modules/tradeCalendar/js/tradeCanledar_new.js','js');",
            )
            _parse_identity(body, endpoint_kind="root", random_ms=random_ms)
        elif endpoint_kind == "root-writer":
            body = (
                _live_root_body(random_ms)
                .decode()
                .replace(
                    "      document.write(\n",
                    "      if (false) {\n        document.write(\n",
                )
                .replace(
                    "      );\n",
                    "        );\n      }\n",
                )
                .encode()
            )
            _parse_identity(body, endpoint_kind="root", random_ms=random_ms)
        elif endpoint_kind == "concat-function":
            body = (
                _official_concatversion_body()
                .replace(
                    b"function changeVertion(sUrl,sType){",
                    b"function changeVertion(sUrl,sType){if(false){",
                )
                .replace(
                    b"document.write(jshref);break;}}",
                    b"document.write(jshref);break;}}}",
                )
            )
            _parse_identity(
                body,
                endpoint_kind="concat",
                path_identity=("https://res.static.szse.cn", "/api/report"),
            )
        else:
            body = _official_js_body().replace(
                b"const endpoint = pathObj.report_path",
                b"const endpoint = false && pathObj.report_path",
            )
            _parse_identity(
                body,
                endpoint_kind="js",
                path_identity=("https://res.static.szse.cn", "/api/report"),
            )
    assert error.value.code == "identity"


def _month_body(month: int, *, nowdate: str = "2026-09-06") -> bytes:
    rows = [
        {
            "jyrq": f"2026-{month:02d}-{day:02d}",
            "jybz": "1" if datetime(2026, month, day).weekday() < 5 else "0",
            "zrxh": (datetime(2026, month, day).weekday() + 1) % 7 + 1,
        }
        for day in range(1, calendar.monthrange(2026, month)[1] + 1)
    ]
    return json.dumps({"data": rows, "nowdate": nowdate}, separators=(",", ":")).encode()


class _FakeTransport:
    def __init__(self, responses: dict[str, OfficialSzseResponse]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def fetch(self, url: str, *, timeout_seconds: float, max_bytes: int) -> OfficialSzseResponse:
        del timeout_seconds, max_bytes
        self.calls.append(url)
        return self.responses[url]


class _SequenceTransport:
    def __init__(
        self,
        responses: Mapping[str, OfficialSzseResponse | list[OfficialSzseResponse]],
    ) -> None:
        self.responses = {
            url: list(value) if isinstance(value, list) else [value]
            for url, value in responses.items()
        }
        self.calls: list[str] = []

    def fetch(self, url: str, *, timeout_seconds: float, max_bytes: int) -> OfficialSzseResponse:
        del timeout_seconds, max_bytes
        self.calls.append(url)
        values = self.responses.get(url)
        if not values:
            raise RuntimeError("missing fake response")
        return values.pop(0) if len(values) > 1 else values[0]


class _Clock:
    def __init__(self) -> None:
        self.current = _CLOCK_START

    def __call__(self) -> datetime:
        value = self.current
        self.current += timedelta(minutes=1)
        return value


class _RollbackClock:
    def __init__(self) -> None:
        self.index = 0

    def __call__(self) -> datetime:
        value = _CLOCK_START + timedelta(minutes=self.index)
        if self.index == 4:
            value -= timedelta(minutes=2)
        self.index += 1
        return value


class _ExplodingTransport:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch(self, url: str, *, timeout_seconds: float, max_bytes: int) -> OfficialSzseResponse:
        del timeout_seconds, max_bytes
        self.calls.append(url)
        raise AssertionError("duplicate run must not fetch the network")


class _ExplodingClock:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        raise AssertionError("duplicate run must not read the clock")


def _transport() -> _FakeTransport:
    random_ms = _identity_random_ms(_CLOCK_START + timedelta(minutes=1))
    path_url = _LIVE_PATH_URL_TEMPLATE.format(random_ms=random_ms)
    concat_url = _LIVE_CONCAT_URL_TEMPLATE.format(random_ms=random_ms)
    responses = {
        SZSE_CALENDAR_ROOT_URL: OfficialSzseResponse(
            status_code=200,
            content_type="text/html; charset=utf-8",
            body=_official_root_body(),
        ),
        path_url: OfficialSzseResponse(
            status_code=200,
            content_type="application/javascript; charset=utf-8",
            body=_official_path_body(),
        ),
        concat_url: OfficialSzseResponse(
            status_code=200,
            content_type="application/javascript; charset=utf-8",
            body=_official_concatversion_body(),
        ),
        SZSE_CALENDAR_JS_URL: OfficialSzseResponse(
            status_code=200,
            content_type="application/javascript; charset=utf-8",
            body=_official_js_body(),
        ),
    }
    for month in range(1, 13):
        responses[SZSE_DIRECT_DAILY_URL_TEMPLATE.format(year=_YEAR, month=month)] = (
            OfficialSzseResponse(
                status_code=200,
                content_type="application/json; charset=utf-8",
                body=_month_body(month),
            )
        )
    return _FakeTransport(responses)


def _response_map() -> dict[str, OfficialSzseResponse | list[OfficialSzseResponse]]:
    return dict(_transport().responses)


def _live_response_map(
    random_ms: int,
) -> dict[str, OfficialSzseResponse | list[OfficialSzseResponse]]:
    responses = _response_map()
    path_url = _LIVE_PATH_URL_TEMPLATE.format(random_ms=random_ms)
    concat_url = _LIVE_CONCAT_URL_TEMPLATE.format(random_ms=random_ms)
    responses[SZSE_CALENDAR_ROOT_URL] = OfficialSzseResponse(
        status_code=200,
        content_type="text/html; charset=utf-8",
        body=_live_root_body(random_ms),
    )
    responses[path_url] = OfficialSzseResponse(
        status_code=200,
        content_type="application/javascript; charset=utf-8",
        body=_official_path_body(),
    )
    responses[concat_url] = OfficialSzseResponse(
        status_code=200,
        content_type="application/javascript; charset=utf-8",
        body=_official_concatversion_body(),
    )
    responses[SZSE_CALENDAR_JS_URL] = OfficialSzseResponse(
        status_code=200,
        content_type="application/javascript; charset=utf-8",
        body=_official_js_body(),
    )
    return responses


def _official_identity_response_map() -> dict[
    str, OfficialSzseResponse | list[OfficialSzseResponse]
]:
    responses = _response_map()
    responses[SZSE_CALENDAR_ROOT_URL] = OfficialSzseResponse(
        status_code=200,
        content_type="text/html; charset=utf-8",
        body=(
            "<html><body>深圳证券交易所<script>"
            "<script src='/modules/js/concatversion.js'></script>"
            "changeVertion('/modules/tradeCalendar/js/tradeCanledar_new.js','js');"
            "</script></body></html>"
        ).encode(),
    )
    responses[SZSE_CALENDAR_CONCATVERSION_URL] = OfficialSzseResponse(
        status_code=200,
        content_type="application/javascript; charset=utf-8",
        body=_official_concatversion_body(),
    )
    return responses


def test_live_root_path_concatversion_identity_chain_is_collected_and_replayed(
    tmp_path: Path,
) -> None:
    random_ms = _identity_random_ms(_CLOCK_START + timedelta(minutes=1))
    transport = _SequenceTransport(_live_response_map(random_ms))
    collector, raw, _ = _collect(tmp_path, transport=transport)

    result = collector.collect()

    path_url = _LIVE_PATH_URL_TEMPLATE.format(random_ms=random_ms)
    concat_url = _LIVE_CONCAT_URL_TEMPLATE.format(random_ms=random_ms)
    assert transport.calls[:4] == [
        SZSE_CALENDAR_ROOT_URL,
        path_url,
        concat_url,
        SZSE_CALENDAR_JS_URL,
    ]
    assert len(result.identity_assets) == 4
    assert len(result.attempts) == 28
    assert tuple(reference.kind for reference in result.identity_assets) == (
        "root",
        "path",
        "concat",
        "js",
    )
    replayed = replay_szse_daily_run(
        raw,
        run_id=result.run_id,
        manifest_date=result.raw_manifest_ref.raw_date,
        manifest_capture_id=result.raw_manifest_ref.capture_id,
    )
    assert replayed.proof.proof_digest == result.proof.proof_digest
    typed_references = (
        result.identity_assets
        + result.catalog_refs
        + tuple(
            attempt.raw_ref
            for attempt in result.attempts
            if attempt.endpoint_kind == "page" and attempt.raw_ref is not None
        )
        + tuple(attempt.state_ref for attempt in result.attempts if attempt.state_ref is not None)
        + (result.raw_manifest_ref,)
    )
    assert len(typed_references) == 69
    assert len({reference.capture_id for reference in typed_references}) == 69


def test_fictional_direct_tag_identity_fixture_is_rejected(
    tmp_path: Path,
) -> None:
    transport = _SequenceTransport(_official_identity_response_map())
    collector, raw, _ = _collect(tmp_path, transport=transport)

    with pytest.raises(OfficialSzseCalendarError) as error:
        collector.collect()

    assert str(error.value) == "official SZSE calendar source identity is invalid"
    assert transport.calls == [SZSE_CALENDAR_ROOT_URL]
    assert collector.attempts[-1].endpoint_kind == "root"
    assert collector.attempts[-1].error_code == "identity"
    assert raw.list("szse-calendar", "2026-09-06")


@pytest.mark.parametrize(
    "root_body",
    [
        "<html><body>深圳证券交易所"
        "<script>changeVertion('/modules/tradeCalendar/js/tradeCanledar_new.js','js');</script>"
        "</body></html>",
        "<html><head>"
        '<script src="/modules/js/concatversion.js"></script>'
        '<script src="/modules/js/concatversion.js"></script>'
        "</head><body>深圳证券交易所"
        "<script>changeVertion('/modules/tradeCalendar/js/tradeCanledar_new.js','js');</script>"
        "</body></html>",
        "<html><head>"
        '<script src="/modules/js/concatversion.js"></script>'
        '<script src="/modules/js/concatversion.js?cache=2"></script>'
        "</head><body>深圳证券交易所"
        "<script>changeVertion('/modules/tradeCalendar/js/tradeCanledar_new.js','js');</script>"
        "</body></html>",
        "<html><head>"
        '<script src="/modules/js/concatversion.js"></script>'
        "</head><body>深圳证券交易所"
        "<script>changeVertion('/modules/other.js','js');</script>"
        "</body></html>",
    ],
)
def test_root_identity_grammar_rejects_missing_extra_or_changed_script(
    tmp_path: Path, root_body: str
) -> None:
    responses = _response_map()
    responses[SZSE_CALENDAR_ROOT_URL] = OfficialSzseResponse(
        status_code=200,
        content_type="text/html",
        body=root_body.encode(),
    )
    transport = _SequenceTransport(responses)
    collector, raw, _ = _collect(tmp_path, transport=transport)

    with pytest.raises(OfficialSzseCalendarError) as error:
        collector.collect()

    assert str(error.value) == "official SZSE calendar source identity is invalid"
    assert transport.calls == [SZSE_CALENDAR_ROOT_URL]
    assert collector.attempts[-1].endpoint_kind == "root"
    assert collector.attempts[-1].error_code == "identity"
    assert raw.list("szse-calendar", "2026-09-06")


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-path",
        "duplicate-concat",
        "mismatched-random",
        "extra-direct-script",
        "wrong-target-type",
        "nested-target",
        "dynamic-target",
    ],
)
def test_live_root_identity_grammar_rejects_script_chain_tampering(
    tmp_path: Path, mutation: str
) -> None:
    random_ms = _identity_random_ms(_CLOCK_START + timedelta(minutes=1))
    body = _live_root_body(random_ms).decode()
    if mutation == "missing-path":
        body = body.replace("/szsePath.js?random=", "/missing.js?random=")
    elif mutation == "duplicate-concat":
        body = body.replace(
            "</script></body>",
            "".join(
                (
                    'document.write(" <script src=\'" + _host '
                    ' + "/szsePath.js?random=" + _versionDate '
                    ' + "\'> <\\/script> "'
                    ' + " <script src=\'" + _path '
                    ' + "/common/js/concatversion.js?random=" '
                    ' + _versionDate + "\'> <\\/script> ");'
                    "</script></body>",
                )
            ),
        )
    elif mutation == "mismatched-random":
        body = body.replace(
            '_versionDate + "\'> <\\/script> "',
            '_otherDate + "\'> <\\/script> "',
        )
    elif mutation == "extra-direct-script":
        body = body.replace(
            "<script>\n    (function ()",
            "<script src='/szsePath.js'></script><script>\n    (function ()",
            1,
        )
    elif mutation == "wrong-target-type":
        body = body.replace(
            "changeVertion('/modules/tradeCalendar/js/tradeCanledar_new.js','js');",
            "changeVertion('/modules/tradeCalendar/js/tradeCanledar_new.js','css');",
        )
    elif mutation == "nested-target":
        body = body.replace(
            "changeVertion('/modules/tradeCalendar/js/tradeCanledar_new.js','js');",
            "if (true) { changeVertion('/modules/tradeCalendar/js/tradeCanledar_new.js','js'); }",
        )
    else:
        body = body.replace(
            "changeVertion('/modules/tradeCalendar/js/tradeCanledar_new.js','js');",
            "changeVertion(calendarPath,'js');",
        )
    responses = _live_response_map(random_ms)
    responses[SZSE_CALENDAR_ROOT_URL] = OfficialSzseResponse(
        status_code=200,
        content_type="text/html",
        body=body.encode(),
    )
    transport = _SequenceTransport(responses)
    collector, raw, _ = _collect(tmp_path, transport=transport)

    with pytest.raises(OfficialSzseCalendarError) as error:
        collector.collect()

    assert str(error.value) == "official SZSE calendar source identity is invalid"
    assert error.value.__context__ is None
    assert transport.calls == [SZSE_CALENDAR_ROOT_URL]
    assert collector.attempts[-1].endpoint_kind == "root"
    assert collector.attempts[-1].error_code == "identity"
    assert raw.list("szse-calendar", "2026-09-06")


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("wrong-version", "identity"),
        ("multiple-version", "identity"),
        ("string-version", "identity"),
        ("changed-transform", "identity"),
        ("wrong-case", "identity"),
        ("wrong-dev-model", "identity"),
        ("duplicate-case", "identity"),
        ("duplicate-path", "identity"),
        ("malicious-version", "identity"),
        ("missing-query", "identity"),
    ],
)
def test_concatversion_identity_grammar_rejects_tampered_transform(
    tmp_path: Path, mutation: str, expected_code: str
) -> None:
    body = _official_concatversion_body().decode()
    if mutation == "wrong-version":
        body = body.replace("1.2.221", "1.2.220")
    elif mutation == "multiple-version":
        body = "var sjsVersion='1.2.220';" + body
    elif mutation == "string-version":
        body = "var marker=\"sjsVersion='1.2.221';\";" + body.replace(
            "var sjsVersion='1.2.221';", ""
        )
    elif mutation == "changed-transform":
        body = body.replace(".min.'+sType", ".bundle.'+sType")
    elif mutation == "wrong-case":
        body = body.replace("case 'js':", "case 'css':")
    elif mutation == "wrong-dev-model":
        body = body.replace("isDevModel=false", "isDevModel=true")
    elif mutation == "duplicate-case":
        body = body.replace("case 'js':", "case 'js':case 'js':")
    elif mutation == "duplicate-path":
        body = body.replace(
            "pathObj.https_file_path", "pathObj.https_file_path+pathObj.https_file_path"
        )
    elif mutation == "malicious-version":
        body = body.replace("sjsVersion='1.2.221'", "sjsVersion=getVersion()")
    else:
        body = body.replace('+"?version="+sjsVersion', "+sjsVersion")
    responses = _response_map()
    random_ms = _identity_random_ms(_CLOCK_START + timedelta(minutes=1))
    concat_url = _LIVE_CONCAT_URL_TEMPLATE.format(random_ms=random_ms)
    responses[concat_url] = OfficialSzseResponse(
        status_code=200,
        content_type="application/javascript",
        body=body.encode(),
    )
    transport = _SequenceTransport(responses)
    collector, raw, _ = _collect(tmp_path, transport=transport)

    with pytest.raises(OfficialSzseCalendarError) as error:
        collector.collect()

    assert str(error.value) == "official SZSE calendar source identity is invalid"
    assert error.value.__context__ is None
    assert transport.calls == [
        SZSE_CALENDAR_ROOT_URL,
        _LIVE_PATH_URL_TEMPLATE.format(random_ms=random_ms),
        concat_url,
    ]
    assert collector.attempts[-1].endpoint_kind == "concat"
    assert collector.attempts[-1].error_code == expected_code
    assert raw.list("szse-calendar", "2026-09-06")


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (OfficialSzseResponse(status_code=503, content_type="text/html", body=b"busy"), "status"),
        (
            OfficialSzseResponse(
                status_code=200,
                content_type="text/html",
                body=b"redirected",
                redirected=True,
            ),
            "redirect",
        ),
        (
            OfficialSzseResponse(
                status_code=200,
                content_type="application/json",
                body=_official_concatversion_body(),
            ),
            "content_type",
        ),
    ],
)
def test_concatversion_http_identity_failures_are_captured_before_acceptance(
    tmp_path: Path, response: OfficialSzseResponse, expected_code: str
) -> None:
    responses = _response_map()
    random_ms = _identity_random_ms(_CLOCK_START + timedelta(minutes=1))
    concat_url = _LIVE_CONCAT_URL_TEMPLATE.format(random_ms=random_ms)
    responses[concat_url] = response
    transport = _SequenceTransport(responses)
    collector, raw, _ = _collect(tmp_path, transport=transport)

    with pytest.raises(OfficialSzseCalendarError) as error:
        collector.collect()

    assert str(error.value) == "official SZSE calendar response is unusable"
    assert error.value.__context__ is None
    assert transport.calls == [
        SZSE_CALENDAR_ROOT_URL,
        _LIVE_PATH_URL_TEMPLATE.format(random_ms=random_ms),
        concat_url,
    ]
    assert collector.attempts[-1].endpoint_kind == "concat"
    assert collector.attempts[-1].error_code == expected_code
    assert collector.attempts[-1].replay_allowed is False
    assert raw.list("szse-calendar", "2026-09-06")


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong-static-host",
        "wrong-main-host",
        "duplicate-static",
        "duplicate-main",
    ],
)
def test_path_identity_grammar_rejects_tampered_static_composition(
    tmp_path: Path, mutation: str
) -> None:
    random_ms = _identity_random_ms(_CLOCK_START + timedelta(minutes=1))
    path_url = _LIVE_PATH_URL_TEMPLATE.format(random_ms=random_ms)
    body = _official_path_body().decode()
    if mutation == "wrong-static-host":
        body = body.replace("https://res.static.szse.cn", "https://evil.invalid")
    elif mutation == "wrong-main-host":
        body = body.replace("https://www.szse.cn", "https://evil.invalid")
    elif mutation == "duplicate-static":
        body += "var domainResStaticHttps='https://res.static.szse.cn';"
    else:
        body += "var domainMainHttps='https://www.szse.cn';"
    responses = _live_response_map(random_ms)
    responses[path_url] = OfficialSzseResponse(
        status_code=200,
        content_type="application/javascript",
        body=body.encode(),
    )
    transport = _SequenceTransport(responses)
    collector, raw, _ = _collect(tmp_path, transport=transport)

    with pytest.raises(OfficialSzseCalendarError) as error:
        collector.collect()

    assert str(error.value) == "official SZSE calendar source identity is invalid"
    assert error.value.__context__ is None
    assert transport.calls == [SZSE_CALENDAR_ROOT_URL, path_url]
    assert collector.attempts[-1].endpoint_kind == "path"
    assert collector.attempts[-1].error_code == "identity"
    assert raw.list("szse-calendar", "2026-09-06")


@pytest.mark.parametrize("mutation", ["changed-endpoint", "duplicate-endpoint"])
def test_final_js_identity_grammar_rejects_tampered_endpoint_composition(
    tmp_path: Path, mutation: str
) -> None:
    random_ms = _identity_random_ms(_CLOCK_START + timedelta(minutes=1))
    body = _official_js_body().decode()
    if mutation == "changed-endpoint":
        body = body.replace(
            "onepersistenthour/monthList?month=", "onepersistenthour/dayList?month="
        )
    else:
        body += (
            "const duplicate = pathObj.report_path "
            '+ "/exchange/onepersistenthour/monthList?month=";'
        )
    responses = _live_response_map(random_ms)
    responses[SZSE_CALENDAR_JS_URL] = OfficialSzseResponse(
        status_code=200,
        content_type="application/javascript",
        body=body.encode(),
    )
    transport = _SequenceTransport(responses)
    collector, raw, _ = _collect(tmp_path, transport=transport)

    with pytest.raises(OfficialSzseCalendarError) as error:
        collector.collect()

    assert str(error.value) == "official SZSE calendar source identity is invalid"
    assert error.value.__context__ is None
    assert transport.calls == [
        SZSE_CALENDAR_ROOT_URL,
        _LIVE_PATH_URL_TEMPLATE.format(random_ms=random_ms),
        _LIVE_CONCAT_URL_TEMPLATE.format(random_ms=random_ms),
        SZSE_CALENDAR_JS_URL,
    ]
    assert collector.attempts[-1].endpoint_kind == "js"
    assert collector.attempts[-1].error_code == "identity"
    assert raw.list("szse-calendar", "2026-09-06")


def _month_body_with_zrxh(month: int, *, nowdate: str = "2026-09-06") -> bytes:
    payload = json.loads(_month_body(month, nowdate=nowdate).decode())
    payload["data"] = [
        {
            **row,
            "zrxh": (datetime.fromisoformat(row["jyrq"]).weekday() + 1) % 7 + 1,
        }
        for row in payload["data"]
    ]
    return json.dumps(payload, separators=(",", ":")).encode()


@pytest.fixture(autouse=True)
def _fixture_identity_policy(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    fixture_bodies = {
        "root": _official_root_body(),
        "path": _official_path_body(),
        "concat": _official_concatversion_body(),
        "js": _official_js_body(),
    }
    monkeypatch.setattr(
        official_szse_daily,
        "_IDENTITY_SOURCE_SHA256",
        {kind: hashlib.sha256(body).hexdigest() for kind, body in fixture_bodies.items()},
    )


def _collect(
    tmp_path: Path,
    *,
    transport: _FakeTransport | _SequenceTransport | None = None,
    clock: Callable[[], datetime] | None = None,
    max_bytes: int = 512 * 1024,
) -> tuple[SzseOfficialCalendarCollector, LocalFileStorage, _FakeTransport | _SequenceTransport]:
    raw = LocalFileStorage(tmp_path / "raw")
    selected_transport = _transport() if transport is None else transport
    collector = SzseOfficialCalendarCollector(
        raw,
        transport=selected_transport,
        clock=_Clock() if clock is None else clock,
        run_id=_RUN_ID,
        max_bytes=max_bytes,
    )
    return collector, raw, selected_transport


def test_official_szse_module_exposes_raw_first_collection_contract(tmp_path: Path) -> None:
    raw = LocalFileStorage(tmp_path / "raw")
    transport = _transport()
    collector = SzseOfficialCalendarCollector(
        raw,
        transport=transport,
        clock=_Clock(),
        run_id=_RUN_ID,
    )

    result = collector.collect(exchange="SZ", year=_YEAR)

    assert result.run_id == _RUN_ID
    assert result.proof.exchange == "SZ"
    assert result.proof.coverage.confirmed_through is not None
    assert result.proof.coverage.confirmed_through <= datetime(2026, 9, 5).date()
    assert len(transport.calls) == 28


def test_unsupported_scope_fails_before_transport(tmp_path: Path) -> None:
    raw = LocalFileStorage(tmp_path / "raw")
    transport = _transport()
    collector = SzseOfficialCalendarCollector(raw, transport=transport, clock=_Clock())

    with pytest.raises(OfficialSzseCalendarError):
        collector.collect(exchange="SH", year=_YEAR)

    assert transport.calls == []


@pytest.mark.parametrize("year,month", [(2025, 1), (2026, 0), (2026, 13), (2026, True)])
def test_url_helper_has_no_caller_controlled_scope(year: int, month: int) -> None:
    with pytest.raises(OfficialSzseCalendarError) as error:
        szse_direct_daily_url(year, month)

    assert str(error.value) == "official SZSE calendar scope is unsupported"
    assert error.value.__context__ is None


def test_replay_is_a_read_only_path(tmp_path: Path) -> None:
    raw = LocalFileStorage(tmp_path / "raw")
    result = SzseOfficialCalendarCollector(
        raw,
        transport=_transport(),
        clock=_Clock(),
        run_id=_RUN_ID,
    ).collect()

    replayed = replay_szse_daily_run(
        raw,
        run_id=result.run_id,
        manifest_date=result.raw_manifest_ref.raw_date,
        manifest_capture_id=result.raw_manifest_ref.capture_id,
    )

    assert replayed.proof.proof_digest == result.proof.proof_digest


def test_direct_replay_rejects_manifest_without_final_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collector, raw, _ = _collect(tmp_path)
    result = collector.collect()
    original_list = raw.list

    def hide_ledger(source: str, date: str) -> list[RawObjectManifest]:
        if source == SZSE_RUN_LEDGER_SOURCE:
            return []
        return original_list(source, date)

    monkeypatch.setattr(raw, "list", hide_ledger)
    with pytest.raises(OfficialSzseCalendarError) as error:
        replay_szse_daily_run(
            raw,
            run_id=result.run_id,
            manifest_date=result.raw_manifest_ref.raw_date,
            manifest_capture_id=result.raw_manifest_ref.capture_id,
        )

    assert str(error.value) == "official SZSE calendar replay is invalid"
    assert error.value.__context__ is None


def test_direct_replay_rejects_an_incomplete_claim_without_final_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collector, raw, _ = _collect(tmp_path)
    result = collector.collect()
    original_list = raw.list

    def hide_final(source: str, date: str) -> list[RawObjectManifest]:
        manifests = original_list(source, date)
        if source == SZSE_RUN_LEDGER_SOURCE and date == SZSE_RUN_LEDGER_DATE:
            return manifests[:1]
        return manifests

    monkeypatch.setattr(raw, "list", hide_final)
    with pytest.raises(OfficialSzseCalendarError) as error:
        replay_szse_daily_run(
            raw,
            run_id=result.run_id,
            manifest_date=result.raw_manifest_ref.raw_date,
            manifest_capture_id=result.raw_manifest_ref.capture_id,
        )

    assert str(error.value) == "official SZSE calendar replay is invalid"
    assert error.value.__context__ is None


def test_direct_replay_rejects_a_tampered_final_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collector, raw, _ = _collect(tmp_path)
    result = collector.collect()
    final_manifest = raw.list(SZSE_RUN_LEDGER_SOURCE, SZSE_RUN_LEDGER_DATE)[-1]
    original_get = raw.get

    def tampered_get(
        object_id: str, *, checksum: str | None = None, size: int | None = None
    ) -> bytes:
        content = original_get(object_id, checksum=checksum, size=size)
        if object_id != final_manifest.object_id:
            return content
        payload = json.loads(content.decode())
        payload["proof_digest"] = "0" * 64
        return json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()

    monkeypatch.setattr(raw, "get", tampered_get)
    with pytest.raises(OfficialSzseCalendarError) as error:
        replay_szse_daily_run(
            raw,
            run_id=result.run_id,
            manifest_date=result.raw_manifest_ref.raw_date,
            manifest_capture_id=result.raw_manifest_ref.capture_id,
        )

    assert str(error.value) == "official SZSE calendar replay is invalid"
    assert error.value.__context__ is None


@pytest.mark.parametrize(
    "old_version",
    [
        "szse-calendar-run-manifest-v1",
        "szse-calendar-run-manifest-v2",
        "szse-calendar-run-manifest-v3",
    ],
)
def test_replay_rejects_previous_manifest_protocols(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, old_version: str
) -> None:
    collector, raw, _ = _collect(tmp_path)
    result = collector.collect()
    original_get = raw.get

    def old_manifest_get(
        object_id: str, *, checksum: str | None = None, size: int | None = None
    ) -> bytes:
        content = original_get(object_id, checksum=checksum, size=size)
        if object_id != result.raw_manifest_ref.object_id:
            return content
        payload = json.loads(content.decode())
        payload["version"] = old_version
        return json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()

    monkeypatch.setattr(raw, "get", old_manifest_get)
    with pytest.raises(OfficialSzseCalendarError) as error:
        replay_szse_daily_run(
            raw,
            run_id=result.run_id,
            manifest_date=result.raw_manifest_ref.raw_date,
            manifest_capture_id=result.raw_manifest_ref.capture_id,
        )

    assert str(error.value) == "official SZSE calendar replay is invalid"
    assert error.value.__context__ is None


def test_claim_and_final_ledger_entries_share_a_claim_nonce(tmp_path: Path) -> None:
    collector, raw, _ = _collect(tmp_path)
    result = collector.collect()
    entries = raw.list(SZSE_RUN_LEDGER_SOURCE, SZSE_RUN_LEDGER_DATE)
    assert len(entries) == 2
    payloads = [
        json.loads(raw.get(entry.object_id, checksum=entry.checksum).decode()) for entry in entries
    ]
    claim = next(payload for payload in payloads if payload["kind"] == "claim")
    final = next(payload for payload in payloads if payload["kind"] == "final")

    assert claim["claim_nonce"] == final["claim_nonce"]
    assert result.proof.proof_digest == final["proof_digest"]
    assert claim["identity_policy_version"] == official_szse_daily.SZSE_IDENTITY_POLICY_VERSION
    assert claim["identity_policy_digest"] == final["identity_policy_digest"]


def test_replay_rejects_a_final_ledger_claim_nonce_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collector, raw, _ = _collect(tmp_path)
    result = collector.collect()
    final_manifest = next(
        entry
        for entry in raw.list(SZSE_RUN_LEDGER_SOURCE, SZSE_RUN_LEDGER_DATE)
        if json.loads(raw.get(entry.object_id, checksum=entry.checksum).decode())["kind"] == "final"
    )
    original_list = raw.list
    original_get = raw.get
    payload = json.loads(original_get(final_manifest.object_id, checksum=final_manifest.checksum))
    payload["claim_nonce"] = "0" * 32
    tampered_content = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    tampered_checksum = hashlib.sha256(tampered_content).hexdigest()
    tampered_manifest = replace(
        final_manifest,
        object_id=tampered_checksum,
        checksum=tampered_checksum,
        size=len(tampered_content),
    )

    def tampered_list(source: str, date: str) -> list[RawObjectManifest]:
        values = original_list(source, date)
        if source != SZSE_RUN_LEDGER_SOURCE or date != SZSE_RUN_LEDGER_DATE:
            return values
        return [
            tampered_manifest if item.capture_id == final_manifest.capture_id else item
            for item in values
        ]

    def tampered_get(
        object_id: str, *, checksum: str | None = None, size: int | None = None
    ) -> bytes:
        if object_id == tampered_manifest.object_id:
            return tampered_content
        return original_get(object_id, checksum=checksum, size=size)

    monkeypatch.setattr(raw, "list", tampered_list)
    monkeypatch.setattr(raw, "get", tampered_get)
    with pytest.raises(OfficialSzseCalendarError) as error:
        replay_szse_daily_run(
            raw,
            run_id=result.run_id,
            manifest_date=result.raw_manifest_ref.raw_date,
            manifest_capture_id=result.raw_manifest_ref.capture_id,
        )

    assert str(error.value) == "official SZSE calendar replay is invalid"
    assert error.value.__context__ is None


def _proof_with_replaced_page(
    result: SzseOfficialDailyResult, page_index: int, **changes: object
) -> CalendarScanRunReceipt:
    """Keep the domain proof internally coherent while changing public page provenance."""

    proof = result.proof
    pages = list(proof.pages)
    pages[page_index] = replace(pages[page_index], **changes)
    page_values = tuple(pages)
    pass_values = tuple(
        replace(
            receipt,
            member_digest=calendar_scan_run_pass_member_digest(page_values[offset : offset + 12]),
        )
        for receipt, offset in zip(proof.pass_receipts, (0, 12), strict=True)
    )
    manifest = replace(
        proof.manifest,
        canonical_member_digest=calendar_scan_run_manifest_member_digest(
            proof.catalog_receipts, pass_values, page_values
        ),
    )
    return replace(
        proof,
        pages=page_values,
        pass_receipts=pass_values,
        manifest=manifest,
        proof_digest="",
    )


@pytest.mark.parametrize(
    "attack",
    [
        "PAGE_RAW_PROOF_CHECKSUM_MISMATCH",
        "PAGE_RAW_PROOF_TIME_MISMATCH",
        "ATTEMPT_AFTER_CUTOFF",
        "STATE_KIND_AND_MIME_MISMATCH",
        "IDENTITY_MIME_AND_WINDOW_MISMATCH",
        "MANIFEST_MIME_AND_OBSERVED_TIME_MISMATCH",
        "ATTEMPT_VS_RAW_TIME_MISMATCH",
        "ATTEMPT_VS_STATE_TIME_MISMATCH",
        "FORGED_MANIFEST_ROUTE",
        "CATALOG_CHECKSUM_MISMATCH",
        "CATALOG_TIME_MISMATCH",
        "CATALOG_KIND_MISMATCH",
        "CATALOG_ROUTE_MISMATCH",
    ],
)
def test_public_result_rejects_provenance_and_pit_attacks(tmp_path: Path, attack: str) -> None:
    collector, _raw, _ = _collect(tmp_path)
    result = collector.collect()
    attempts = list(result.attempts)
    identity_assets = list(result.identity_assets)
    catalog_refs = list(result.catalog_refs)
    raw_manifest_ref = result.raw_manifest_ref
    proof = result.proof

    def assert_rejected(action: Callable[[], object]) -> None:
        with pytest.raises(Exception) as error:
            action()
        assert "sentinel" not in repr(error.value)

    if attack == "PAGE_RAW_PROOF_CHECKSUM_MISMATCH":
        tampered_proof = _proof_with_replaced_page(result, 0, raw_artifact_sha256="a" * 64)
        assert_rejected(lambda: replace(result, proof=tampered_proof))
    elif attack == "PAGE_RAW_PROOF_TIME_MISMATCH":
        tampered_proof = _proof_with_replaced_page(
            result,
            0,
            observed_at=proof.opened_at,
            available_at=proof.opened_at + timedelta(seconds=1),
        )
        assert_rejected(lambda: replace(result, proof=tampered_proof))
    elif attack == "ATTEMPT_AFTER_CUTOFF":
        attempt = attempts[0]
        attempts[0] = replace(
            attempt,
            observed_at=proof.cutoff_at + timedelta(seconds=1),
            available_at=proof.cutoff_at + timedelta(seconds=2),
        )
        assert_rejected(lambda: replace(result, attempts=tuple(attempts)))
    elif attack == "STATE_KIND_AND_MIME_MISMATCH":
        attempt = attempts[0]
        assert attempt.state_ref is not None
        attempts[0] = replace(
            attempt,
            state_ref=replace(attempt.state_ref, kind="page", content_type="text/html"),
        )
        assert_rejected(lambda: replace(result, attempts=tuple(attempts)))
    elif attack == "IDENTITY_MIME_AND_WINDOW_MISMATCH":
        identity_assets[0] = replace(
            identity_assets[0],
            content_type="application/json",
            observed_at=proof.cutoff_at + timedelta(seconds=1),
            available_at=proof.cutoff_at + timedelta(seconds=2),
        )
        assert_rejected(lambda: replace(result, identity_assets=tuple(identity_assets)))
    elif attack == "MANIFEST_MIME_AND_OBSERVED_TIME_MISMATCH":
        raw_manifest_ref = replace(
            raw_manifest_ref,
            content_type="text/html",
            observed_at=proof.cutoff_at - timedelta(seconds=1),
        )
        assert_rejected(lambda: replace(result, raw_manifest_ref=raw_manifest_ref))
    elif attack == "ATTEMPT_VS_RAW_TIME_MISMATCH":
        attempt = attempts[2]
        attempts[2] = replace(
            attempt,
            observed_at=attempt.observed_at + timedelta(seconds=1),
            available_at=attempt.available_at + timedelta(seconds=1),
        )
        assert_rejected(lambda: replace(result, attempts=tuple(attempts)))
    elif attack == "ATTEMPT_VS_STATE_TIME_MISMATCH":
        attempt = attempts[2]
        assert attempt.state_ref is not None
        attempts[2] = replace(
            attempt,
            state_ref=replace(
                attempt.state_ref,
                observed_at=attempt.available_at + timedelta(seconds=1),
                available_at=attempt.available_at + timedelta(seconds=1),
            ),
        )
        assert_rejected(lambda: replace(result, attempts=tuple(attempts)))
    elif attack == "FORGED_MANIFEST_ROUTE":
        raw_manifest_ref = replace(
            raw_manifest_ref,
            route_digest="a" * 64,
            request_identity="PUT path_sha256=" + "a" * 64,
        )
        assert_rejected(lambda: replace(result, raw_manifest_ref=raw_manifest_ref))
    elif attack == "CATALOG_CHECKSUM_MISMATCH":
        catalog_refs[0] = replace(catalog_refs[0], object_id="b" * 64, checksum="b" * 64)
        assert_rejected(lambda: replace(result, catalog_refs=tuple(catalog_refs)))

    elif attack == "CATALOG_TIME_MISMATCH":
        catalog_refs[0] = replace(
            catalog_refs[0],
            observed_at=proof.cutoff_at,
            available_at=proof.cutoff_at,
        )
        assert_rejected(lambda: replace(result, catalog_refs=tuple(catalog_refs)))
    elif attack == "CATALOG_KIND_MISMATCH":
        catalog_refs[0] = replace(catalog_refs[0], kind="page")
        assert_rejected(lambda: replace(result, catalog_refs=tuple(catalog_refs)))
    else:
        catalog_refs[0] = replace(
            catalog_refs[0],
            route_digest="a" * 64,
            request_identity="PUT path_sha256=" + "a" * 64,
        )
        assert_rejected(lambda: replace(result, catalog_refs=tuple(catalog_refs)))


def test_public_result_rejects_tampered_derived_proof_coverage(tmp_path: Path) -> None:
    collector, _raw, _ = _collect(tmp_path)
    result = collector.collect()
    proof = result.proof
    original_coverage = proof.coverage
    forged_coverage = ScanRunCoverage(
        level=ScanRunCoverageLevel.FINAL_YEAR,
        confirmed_through=date(_YEAR, 12, 31),
        source_nowdate=original_coverage.source_nowdate,
        publication_cutoff=original_coverage.publication_cutoff,
    )
    object.__setattr__(proof, "_coverage", forged_coverage)
    try:
        with pytest.raises(Exception) as error:
            replace(result)
        assert "sentinel" not in repr(error.value)
    finally:
        object.__setattr__(proof, "_coverage", original_coverage)


def test_replay_rejects_identity_ref_splice_between_manifest_and_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collector, raw, _ = _collect(tmp_path)
    result = collector.collect()
    original_get = raw.get

    def tampered_get(
        object_id: str, *, checksum: str | None = None, size: int | None = None
    ) -> bytes:
        content = original_get(object_id, checksum=checksum, size=size)
        if object_id != result.raw_manifest_ref.object_id:
            return content
        payload = json.loads(content.decode())
        payload["identity_assets"][0] = payload["attempts"][1]["raw_ref"]
        return json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()

    monkeypatch.setattr(raw, "get", tampered_get)
    with pytest.raises(OfficialSzseCalendarError) as error:
        replay_szse_daily_run(
            raw,
            run_id=result.run_id,
            manifest_date=result.raw_manifest_ref.raw_date,
            manifest_capture_id=result.raw_manifest_ref.capture_id,
        )

    assert str(error.value) == "official SZSE calendar replay is invalid"
    assert error.value.__context__ is None


def test_zrxh_must_match_the_official_sunday_first_weekday_number(
    tmp_path: Path,
) -> None:
    responses = _response_map()
    month_url = SZSE_DIRECT_DAILY_URL_TEMPLATE.format(year=_YEAR, month=1)
    payload = json.loads(_month_body(1).decode())
    payload["data"][0]["zrxh"] = 1
    responses[month_url] = OfficialSzseResponse(
        status_code=200,
        content_type="application/json",
        body=json.dumps(payload, separators=(",", ":")).encode(),
    )
    collector, _raw, _ = _collect(tmp_path, transport=_SequenceTransport(responses))

    with pytest.raises(OfficialSzseCalendarError) as error:
        collector.collect()

    assert str(error.value) == "official SZSE calendar data is invalid"
    assert error.value.__context__ is None


def test_official_zrxh_rows_are_accepted_without_changing_trading_semantics(
    tmp_path: Path,
) -> None:
    responses = _response_map()
    for month in range(1, 13):
        responses[SZSE_DIRECT_DAILY_URL_TEMPLATE.format(year=_YEAR, month=month)] = (
            OfficialSzseResponse(
                status_code=200,
                content_type="application/json",
                body=_month_body_with_zrxh(month),
            )
        )
    collector, _raw, _ = _collect(tmp_path, transport=_SequenceTransport(responses))

    result = collector.collect()

    assert len(result.proof.pages[0].days) == calendar.monthrange(_YEAR, 1)[1]


@pytest.mark.parametrize(
    "mutation", ["missing", "unknown", "bool", "float", "string", "zero", "eight"]
)
def test_zrxh_schema_variants_fail_closed(tmp_path: Path, mutation: str) -> None:
    responses = _response_map()
    for month in range(1, 13):
        responses[SZSE_DIRECT_DAILY_URL_TEMPLATE.format(year=_YEAR, month=month)] = (
            OfficialSzseResponse(
                status_code=200,
                content_type="application/json",
                body=_month_body_with_zrxh(month),
            )
        )
    month_url = SZSE_DIRECT_DAILY_URL_TEMPLATE.format(year=_YEAR, month=1)
    response = responses[month_url]
    assert type(response) is OfficialSzseResponse
    payload = json.loads(response.body.decode())
    if mutation == "missing":
        payload["data"][0].pop("zrxh")
    elif mutation == "unknown":
        payload["data"][0]["unexpected"] = 1
    elif mutation == "bool":
        payload["data"][0]["zrxh"] = True
    elif mutation == "float":
        payload["data"][0]["zrxh"] = 1.0
    elif mutation == "string":
        payload["data"][0]["zrxh"] = "1"
    elif mutation == "zero":
        payload["data"][0]["zrxh"] = 0
    else:
        payload["data"][0]["zrxh"] = 8
    responses[month_url] = OfficialSzseResponse(
        status_code=200,
        content_type="application/json",
        body=json.dumps(payload, separators=(",", ":")).encode(),
    )
    collector, _raw, _ = _collect(tmp_path, transport=_SequenceTransport(responses))

    with pytest.raises(OfficialSzseCalendarError) as error:
        collector.collect()

    assert str(error.value) == "official SZSE calendar data is invalid"
    assert error.value.__context__ is None


def test_raw_manifest_route_rewrite_is_rejected_during_collect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collector, raw, _ = _collect(tmp_path)
    original_put = raw.put

    def rewritten_put(*args: object, **kwargs: object) -> RawObjectManifest:
        put = cast(Callable[..., RawObjectManifest], original_put)
        manifest = put(*args, **kwargs)
        if kwargs.get("source") == SZSE_CALENDAR_SOURCE and kwargs.get("capture_id"):
            return replace(
                manifest,
                request=sanitize_request_identity("GET https://evil.invalid/replaced"),
            )
        return manifest

    monkeypatch.setattr(raw, "put", rewritten_put)
    with pytest.raises(OfficialSzseCalendarError) as error:
        collector.collect()

    assert str(error.value) == "official SZSE calendar capture integrity failed"
    assert error.value.__context__ is None


def test_raw_manifest_route_rewrite_is_rejected_during_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collector, raw, _ = _collect(tmp_path)
    result = collector.collect()
    original_list = raw.list

    def rewritten_list(source: str, date: str) -> list[RawObjectManifest]:
        manifests = original_list(source, date)
        if source != SZSE_CALENDAR_SOURCE:
            return manifests
        return [
            replace(
                manifest,
                request=sanitize_request_identity("GET https://evil.invalid/replaced"),
            )
            if manifest.capture_id == result.identity_assets[0].capture_id
            else manifest
            for manifest in manifests
        ]

    monkeypatch.setattr(raw, "list", rewritten_list)
    with pytest.raises(OfficialSzseCalendarError) as error:
        replay_szse_daily_run(
            raw,
            run_id=result.run_id,
            manifest_date=result.raw_manifest_ref.raw_date,
            manifest_capture_id=result.raw_manifest_ref.capture_id,
        )

    assert str(error.value) == "official SZSE calendar replay is invalid"
    assert error.value.__context__ is None


def test_clock_rollback_in_catalog_capture_is_rejected(tmp_path: Path) -> None:
    collector, _raw, _ = _collect(tmp_path, clock=_RollbackClock())

    with pytest.raises(OfficialSzseCalendarError) as error:
        collector.collect()

    assert str(error.value) == "official SZSE calendar scan is unstable"
    assert error.value.__context__ is None


def test_same_run_id_returns_existing_final_without_transport(tmp_path: Path) -> None:
    collector, raw, transport = _collect(tmp_path)
    result = collector.collect()
    duplicate_transport = _ExplodingTransport()
    duplicate = SzseOfficialCalendarCollector(
        raw,
        transport=duplicate_transport,
        clock=_Clock(),
        run_id=result.run_id,
    ).collect()

    assert duplicate.proof.proof_digest == result.proof.proof_digest
    assert transport.calls
    assert duplicate_transport.calls == []


def test_same_run_id_is_idempotent_across_a_new_shanghai_date(tmp_path: Path) -> None:
    collector, raw, _ = _collect(tmp_path)
    result = collector.collect()
    duplicate_transport = _ExplodingTransport()
    duplicate_clock = _ExplodingClock()
    duplicate = SzseOfficialCalendarCollector(
        raw,
        transport=duplicate_transport,
        clock=duplicate_clock,
        run_id=result.run_id,
    ).collect()

    assert duplicate.proof.proof_digest == result.proof.proof_digest
    assert duplicate_transport.calls == []
    assert duplicate_clock.calls == 0


def test_all_persisted_evidence_refs_fit_the_run_window_in_creation_order(
    tmp_path: Path,
) -> None:
    collector, raw, _ = _collect(tmp_path)
    result = collector.collect()
    manifest_payload = json.loads(
        raw.get(result.raw_manifest_ref.object_id, checksum=result.raw_manifest_ref.checksum)
    )
    catalog_refs = raw.list("szse-calendar-catalog", result.raw_manifest_ref.raw_date)
    assert len(catalog_refs) == 12
    ordered: list[tuple[datetime, datetime]] = []
    for attempt in result.attempts[:4]:
        assert attempt.raw_ref is not None
        assert attempt.state_ref is not None
        ordered.extend(
            (
                (attempt.raw_ref.observed_at, attempt.raw_ref.available_at),
                (attempt.state_ref.observed_at, attempt.state_ref.available_at),
            )
        )
    ordered.extend(
        (reference.ingest_time, reference.available_time)
        for reference in catalog_refs
        if reference.available_time is not None
    )
    for attempt in result.attempts[4:]:
        assert attempt.raw_ref is not None
        assert attempt.state_ref is not None
        ordered.extend(
            (
                (attempt.raw_ref.observed_at, attempt.raw_ref.available_at),
                (attempt.state_ref.observed_at, attempt.state_ref.available_at),
            )
        )
    ordered.append((result.raw_manifest_ref.observed_at, result.raw_manifest_ref.available_at))
    assert len(manifest_payload["catalogs"]) == 12
    previous = result.proof.opened_at
    for observed_at, available_at in ordered:
        assert result.proof.opened_at <= observed_at <= available_at <= result.proof.cutoff_at
        assert previous <= observed_at
        previous = available_at


def test_incomplete_run_claim_blocks_a_new_collector(tmp_path: Path) -> None:
    responses = _response_map()
    responses[SZSE_CALENDAR_ROOT_URL] = OfficialSzseResponse(
        status_code=200,
        content_type="text/html",
        body=b"not-the-official-calendar",
    )
    raw = LocalFileStorage(tmp_path / "raw")
    first = SzseOfficialCalendarCollector(
        raw,
        transport=_SequenceTransport(responses),
        clock=_Clock(),
        run_id=_RUN_ID,
    )
    with pytest.raises(OfficialSzseCalendarError) as first_error:
        first.collect()
    assert str(first_error.value) == "official SZSE calendar source identity is invalid"

    duplicate_transport = _ExplodingTransport()
    second = SzseOfficialCalendarCollector(
        raw,
        transport=duplicate_transport,
        clock=_Clock(),
        run_id=_RUN_ID,
    )
    with pytest.raises(OfficialSzseCalendarError) as second_error:
        second.collect()
    assert str(second_error.value) == "official SZSE calendar run is already claimed"
    assert duplicate_transport.calls == []


def test_concurrent_collectors_have_one_claim_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = LocalFileStorage(tmp_path / "raw")
    transports = [_transport(), _transport()]
    collectors = [
        SzseOfficialCalendarCollector(
            raw,
            transport=transport,
            clock=_Clock(),
            run_id=_RUN_ID,
        )
        for transport in transports
    ]
    original_put = raw.put
    claims_barrier = Barrier(2)
    calls_lock = Lock()
    ledger_puts = 0

    def gated_put(*args: object, **kwargs: object) -> RawObjectManifest:
        nonlocal ledger_puts
        if kwargs.get("source") == "szse-calendar-run-ledger":
            with calls_lock:
                ledger_puts += 1
                ordinal = ledger_puts
            if ordinal <= 2:
                claims_barrier.wait(timeout=10)
        put = cast(Callable[..., RawObjectManifest], original_put)
        return put(*args, **kwargs)

    monkeypatch.setattr(raw, "put", gated_put)

    def collect_one(collector: SzseOfficialCalendarCollector) -> tuple[bool, str | None]:
        try:
            collector.collect()
        except OfficialSzseCalendarError as error:
            return False, str(error)
        return True, None

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(collect_one, collectors))

    assert sorted(outcome[0] for outcome in outcomes) == [False, True]
    assert [outcome[1] for outcome in outcomes].count(
        "official SZSE calendar run is already claimed"
    ) == 1
    assert sorted(len(transport.calls) for transport in transports) == [0, 28]


def test_final_manifest_has_no_orphan_manifest_state(tmp_path: Path) -> None:
    collector, raw, _ = _collect(tmp_path)
    result = collector.collect()
    state_payloads = [
        json.loads(raw.get(item.object_id, checksum=item.checksum))
        for item in raw.list("szse-calendar-state", result.raw_manifest_ref.raw_date)
    ]

    assert len(state_payloads) == 28
    assert all(item["endpoint_kind"] != "manifest" for item in state_payloads)


def test_replay_does_not_call_transport_or_raw_put(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collector, raw, transport = _collect(tmp_path)
    result = collector.collect()
    manifest_date = result.raw_manifest_ref.raw_date
    manifest_capture_id = result.raw_manifest_ref.capture_id
    manifest_before = raw.list("szse-calendar-manifest", manifest_date)
    raw_count_before = sum(
        len(raw.list(source, day))
        for source in (
            "szse-calendar",
            "szse-calendar-state",
            "szse-calendar-catalog",
            "szse-calendar-manifest",
        )
        for day in {item.raw_date for item in (result.identity_assets + (result.raw_manifest_ref,))}
    )

    def forbidden_put(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("replay must not put raw bytes")

    monkeypatch.setattr(raw, "put", forbidden_put)
    replayed = replay_szse_daily_run(
        raw,
        run_id=result.run_id,
        manifest_date=manifest_date,
        manifest_capture_id=manifest_capture_id,
    )

    assert replayed.proof.proof_digest == result.proof.proof_digest
    random_ms = _identity_random_ms(_CLOCK_START + timedelta(minutes=1))
    assert transport.calls == [
        SZSE_CALENDAR_ROOT_URL,
        _LIVE_PATH_URL_TEMPLATE.format(random_ms=random_ms),
        _LIVE_CONCAT_URL_TEMPLATE.format(random_ms=random_ms),
        SZSE_CALENDAR_JS_URL,
        *(
            SZSE_DIRECT_DAILY_URL_TEMPLATE.format(year=_YEAR, month=month)
            for _pass in (1, 2)
            for month in range(1, 13)
        ),
    ]
    assert raw.list("szse-calendar-manifest", manifest_date) == manifest_before
    raw_count_after = sum(
        len(raw.list(source, day))
        for source in (
            "szse-calendar",
            "szse-calendar-state",
            "szse-calendar-catalog",
            "szse-calendar-manifest",
        )
        for day in {item.raw_date for item in (result.identity_assets + (result.raw_manifest_ref,))}
    )
    assert raw_count_after == raw_count_before


@pytest.mark.parametrize("tamper_kind", ["manifest", "state", "page"])
def test_replay_rejects_tampered_raw_or_state_without_leaking_details(
    tmp_path: Path, tamper_kind: str
) -> None:
    collector, raw, _ = _collect(tmp_path)
    result = collector.collect()
    if tamper_kind == "manifest":
        target = result.raw_manifest_ref
    elif tamper_kind == "state":
        state_manifest = raw.list("szse-calendar-state", result.raw_manifest_ref.raw_date)[0]
        target = state_manifest
    else:
        page_attempt = next(item for item in result.attempts if item.endpoint_kind == "page")
        assert page_attempt.raw_ref is not None
        target = page_attempt.raw_ref
    object_path = tmp_path / "raw" / "objects" / target.object_id
    object_path.write_bytes(b"tampered-provider-secret")

    with pytest.raises(OfficialSzseCalendarError) as error:
        replay_szse_daily_run(
            raw,
            run_id=result.run_id,
            manifest_date=result.raw_manifest_ref.raw_date,
            manifest_capture_id=result.raw_manifest_ref.capture_id,
        )

    assert str(error.value) == "official SZSE calendar replay is invalid"
    assert error.value.__context__ is None
    assert "tampered-provider-secret" not in "".join(traceback.format_exception(error.value))


def test_replay_rejects_unknown_manifest_capture_id(tmp_path: Path) -> None:
    collector, raw, _ = _collect(tmp_path)
    result = collector.collect()

    with pytest.raises(OfficialSzseCalendarError) as error:
        replay_szse_daily_run(
            raw,
            run_id=result.run_id,
            manifest_date=result.raw_manifest_ref.raw_date,
            manifest_capture_id="capture-does-not-exist",
        )

    assert str(error.value) == "official SZSE calendar replay is invalid"
    assert error.value.__context__ is None


def test_replay_rejects_manifest_rebinding_even_when_member_bytes_are_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collector, raw, _ = _collect(tmp_path)
    result = collector.collect()
    original_get = raw.get

    def tampered_get(
        object_id: str, *, checksum: str | None = None, size: int | None = None
    ) -> bytes:
        content = original_get(object_id, checksum=checksum, size=size)
        if object_id != result.raw_manifest_ref.object_id:
            return content
        payload = json.loads(content.decode())
        payload["manifest_domain"]["capture_id"] = str(UUID(int=999))
        return json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()

    monkeypatch.setattr(raw, "get", tampered_get)
    with pytest.raises(OfficialSzseCalendarError) as error:
        replay_szse_daily_run(
            raw,
            run_id=result.run_id,
            manifest_date=result.raw_manifest_ref.raw_date,
            manifest_capture_id=result.raw_manifest_ref.capture_id,
        )

    assert str(error.value) == "official SZSE calendar replay is invalid"
    assert error.value.__context__ is None


@pytest.mark.parametrize("exchange,year", [("SH", _YEAR), ("BJ", _YEAR), ("SZ", 2025)])
def test_unsupported_scope_is_rejected_before_any_transport_or_raw_write(
    tmp_path: Path, exchange: str, year: int
) -> None:
    collector, _raw, transport = _collect(tmp_path)

    with pytest.raises(OfficialSzseCalendarError) as error:
        collector.collect(exchange=exchange, year=year)

    assert str(error.value) == "official SZSE calendar scope is unsupported"
    assert error.value.__context__ is None
    assert transport.calls == []
    assert not (tmp_path / "raw").exists()
    assert collector.attempts == ()


def test_response_is_stored_before_malformed_month_is_parsed(tmp_path: Path) -> None:
    responses = _response_map()
    bad_body = b'{"data": [], "nowdate": "2026-09-06"}'
    month_url = SZSE_DIRECT_DAILY_URL_TEMPLATE.format(year=_YEAR, month=1)
    responses[month_url] = OfficialSzseResponse(
        status_code=200,
        content_type="application/json; charset=utf-8",
        body=bad_body,
    )
    transport = _SequenceTransport(responses)
    collector, raw, _ = _collect(tmp_path, transport=transport)

    with pytest.raises(OfficialSzseCalendarError) as error:
        collector.collect()

    assert str(error.value) == "official SZSE calendar data is invalid"
    assert error.value.__context__ is None
    page_captures = [
        item
        for item in raw.list("szse-calendar", "2026-09-06")
        if raw.get(item.object_id, checksum=item.checksum) == bad_body
    ]
    assert len(page_captures) == 1
    assert raw.get(page_captures[0].object_id, checksum=page_captures[0].checksum) == bad_body
    assert collector.attempts[-1].endpoint_kind == "page"
    assert collector.attempts[-1].error_code == "month_days"
    assert collector.attempts[-1].replay_allowed is False
    states = raw.list("szse-calendar-state", "2026-09-06")
    state_payloads = [
        json.loads(raw.get(item.object_id, checksum=item.checksum)) for item in states
    ]
    assert any(
        item["error_code"] == "month_days" and item["replay_allowed"] is False
        for item in state_payloads
    )


def test_transport_failure_leaves_non_replayable_attempt_and_state(tmp_path: Path) -> None:
    collector, raw, transport = _collect(tmp_path, transport=_SequenceTransport({}))

    with pytest.raises(OfficialSzseCalendarError) as error:
        collector.collect()

    assert str(error.value) == "official SZSE calendar response is unusable"
    assert error.value.__context__ is None
    assert transport.calls == [SZSE_CALENDAR_ROOT_URL]
    assert collector.attempts[-1].error_code == "transport"
    assert collector.attempts[-1].replay_allowed is False
    state_payloads = [
        json.loads(raw.get(item.object_id, checksum=item.checksum))
        for item in raw.list("szse-calendar-state", "2026-09-06")
    ]
    assert state_payloads[-1]["error_code"] == "transport"
    assert state_payloads[-1]["replay_allowed"] is False


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (
            OfficialSzseResponse(status_code=503, content_type="text/html", body=b"busy"),
            "status",
        ),
        (
            OfficialSzseResponse(
                status_code=200,
                content_type="text/html",
                body=b"redirected",
                redirected=True,
            ),
            "redirect",
        ),
        (
            OfficialSzseResponse(status_code=200, content_type="application/json", body=b"{}"),
            "content_type",
        ),
    ],
)
def test_http_response_failures_keep_non_replayable_attempt_state(
    tmp_path: Path, response: OfficialSzseResponse, code: str
) -> None:
    responses = _response_map()
    responses[SZSE_CALENDAR_ROOT_URL] = response
    collector, raw, _ = _collect(tmp_path, transport=_SequenceTransport(responses))

    with pytest.raises(OfficialSzseCalendarError) as error:
        collector.collect()

    assert error.value.__context__ is None
    assert collector.attempts[-1].error_code == code
    assert collector.attempts[-1].replay_allowed is False
    captures = raw.list("szse-calendar", "2026-09-06")
    assert captures
    stored = raw.get(captures[0].object_id, checksum=captures[0].checksum)
    if code != "content_type" or response.body == b"{}":
        assert stored == response.body
    state_payloads = [
        json.loads(raw.get(item.object_id, checksum=item.checksum))
        for item in raw.list("szse-calendar-state", "2026-09-06")
    ]
    assert state_payloads[-1]["error_code"] == code
    assert state_payloads[-1]["replay_allowed"] is False


def test_oversize_response_is_replaced_by_bounded_failure_marker(tmp_path: Path) -> None:
    responses = _response_map()
    responses[SZSE_CALENDAR_ROOT_URL] = OfficialSzseResponse(
        status_code=200,
        content_type="text/html",
        body=b"x" * 1025,
    )
    collector, raw, _ = _collect(
        tmp_path,
        transport=_SequenceTransport(responses),
        max_bytes=1024,
    )

    with pytest.raises(OfficialSzseCalendarError) as error:
        collector.collect()

    assert error.value.__context__ is None
    assert collector.attempts[-1].error_code == "size"
    attempt = collector.attempts[-1]
    assert attempt.raw_ref is not None
    marker = raw.get(attempt.raw_ref.object_id, checksum=attempt.raw_ref.checksum)
    assert len(marker) < 256
    assert b"x" * 64 not in marker


@pytest.mark.parametrize("endpoint", ["root", "js"])
def test_identity_asset_drift_is_saved_but_never_scanned(tmp_path: Path, endpoint: str) -> None:
    responses = _response_map()
    if endpoint == "root":
        responses[SZSE_CALENDAR_ROOT_URL] = OfficialSzseResponse(
            status_code=200,
            content_type="text/html",
            body="深圳证券交易所但没有固定脚本".encode(),
        )
    else:
        responses[SZSE_CALENDAR_JS_URL] = OfficialSzseResponse(
            status_code=200,
            content_type="application/javascript",
            body=b"monthList moved",
        )
    transport = _SequenceTransport(responses)
    collector, raw, _ = _collect(tmp_path, transport=transport)

    with pytest.raises(OfficialSzseCalendarError) as error:
        collector.collect()

    assert str(error.value) == "official SZSE calendar source identity is invalid"
    assert error.value.__context__ is None
    assert all("monthList" not in call or endpoint == "js" for call in transport.calls)
    assert collector.attempts[-1].error_code == "identity"
    assert raw.list("szse-calendar", "2026-09-06")


@pytest.mark.parametrize(
    "mutation", ["missing", "duplicate", "cross-month", "invalid-date", "unknown-jybz"]
)
def test_month_schema_variants_fail_closed_after_raw_capture(tmp_path: Path, mutation: str) -> None:
    responses = _response_map()
    month_url = SZSE_DIRECT_DAILY_URL_TEMPLATE.format(year=_YEAR, month=1)
    payload = json.loads(_month_body(1).decode())
    if mutation == "missing":
        payload["data"] = payload["data"][:-1]
    elif mutation == "duplicate":
        payload["data"][1]["jyrq"] = payload["data"][0]["jyrq"]
    elif mutation == "cross-month":
        payload["data"][0]["jyrq"] = "2026-02-01"
    elif mutation == "invalid-date":
        payload["data"][0]["jyrq"] = "2026-01-00"
    else:
        payload["data"][0]["jybz"] = "全日休市"
    responses[month_url] = OfficialSzseResponse(
        status_code=200,
        content_type="application/json",
        body=json.dumps(payload, separators=(",", ":")).encode(),
    )
    collector, raw, _ = _collect(tmp_path, transport=_SequenceTransport(responses))

    with pytest.raises(OfficialSzseCalendarError) as error:
        collector.collect()

    assert str(error.value) == "official SZSE calendar data is invalid"
    assert error.value.__context__ is None
    assert collector.attempts[-1].endpoint_kind == "page"
    assert collector.attempts[-1].error_code in {"schema", "month_days"}
    assert raw.list("szse-calendar", "2026-09-06")


@pytest.mark.parametrize("nowdate", ["2026-09-07", "2026-09-05"])
def test_future_or_stale_nowdate_is_rejected_against_capture_clock(
    tmp_path: Path, nowdate: str
) -> None:
    responses = _response_map()
    month_url = SZSE_DIRECT_DAILY_URL_TEMPLATE.format(year=_YEAR, month=1)
    responses[month_url] = OfficialSzseResponse(
        status_code=200,
        content_type="application/json",
        body=_month_body(1, nowdate=nowdate),
    )
    collector, _raw, _ = _collect(tmp_path, transport=_SequenceTransport(responses))

    with pytest.raises(OfficialSzseCalendarError) as error:
        collector.collect()

    assert str(error.value) == "official SZSE calendar nowdate is invalid"
    assert error.value.__context__ is None
    assert collector.attempts[-1].error_code == "nowdate"


def test_nowdate_crossing_shanghai_midnight_fails_closed(tmp_path: Path) -> None:
    clock = _Clock()
    clock.current = datetime(2026, 9, 5, 15, 35, tzinfo=UTC)
    random_ms = _identity_random_ms(clock.current + timedelta(minutes=1))
    responses = _live_response_map(random_ms)
    for month in range(1, 13):
        responses[SZSE_DIRECT_DAILY_URL_TEMPLATE.format(year=_YEAR, month=month)] = (
            OfficialSzseResponse(
                status_code=200,
                content_type="application/json",
                body=_month_body(month, nowdate="2026-09-05"),
            )
        )
    collector, _raw, _ = _collect(
        tmp_path,
        transport=_SequenceTransport(responses),
        clock=clock,
    )

    with pytest.raises(OfficialSzseCalendarError) as error:
        collector.collect()

    assert str(error.value) == "official SZSE calendar nowdate is invalid"
    assert error.value.__context__ is None
    assert collector.attempts[-1].error_code == "nowdate"


def test_pass_drift_is_rejected_and_does_not_return_a_proof(tmp_path: Path) -> None:
    responses = _response_map()
    month_url = SZSE_DIRECT_DAILY_URL_TEMPLATE.format(year=_YEAR, month=1)
    changed = json.loads(_month_body(1).decode())
    changed["data"][0]["jybz"] = "0" if changed["data"][0]["jybz"] == "1" else "1"
    responses[month_url] = [
        OfficialSzseResponse(
            status_code=200,
            content_type="application/json",
            body=_month_body(1),
        ),
        OfficialSzseResponse(
            status_code=200,
            content_type="application/json",
            body=json.dumps(changed, separators=(",", ":")).encode(),
        ),
    ]
    collector, _raw, _ = _collect(tmp_path, transport=_SequenceTransport(responses))

    with pytest.raises(OfficialSzseCalendarError) as error:
        collector.collect()

    assert str(error.value) == "official SZSE calendar capture integrity failed"
    assert error.value.__context__ is None
    assert all(attempt.replay_allowed for attempt in collector.attempts)


def test_identical_payloads_across_passes_have_distinct_capture_receipts(tmp_path: Path) -> None:
    collector, _raw, _ = _collect(tmp_path)
    result = collector.collect()
    pages = [attempt for attempt in result.attempts if attempt.endpoint_kind == "page"]
    assert len(pages) == 24
    first, second = pages[:12], pages[12:]
    assert {item.capture_id for item in first}.isdisjoint(item.capture_id for item in second)
    first_refs = [item.raw_ref for item in first]
    second_refs = [item.raw_ref for item in second]
    assert all(ref is not None for ref in (*first_refs, *second_refs))
    assert all(
        left.object_id == right.object_id
        for left, right in zip(first_refs, second_refs, strict=True)
        if left is not None and right is not None
    )
    assert all(
        left.capture_id != right.capture_id
        for left, right in zip(first_refs, second_refs, strict=True)
        if left is not None and right is not None
    )


def test_default_clock_is_timezone_aware(tmp_path: Path) -> None:
    # The real transport is never reached: scope validation is enough to
    # exercise constructor defaults without any network access.
    collector = SzseOfficialCalendarCollector(LocalFileStorage(tmp_path / "raw"))
    with pytest.raises(OfficialSzseCalendarError):
        collector.collect(exchange="SH")


def test_hostile_timezone_failure_is_fixed_and_does_not_echo_secret(tmp_path: Path) -> None:
    from datetime import tzinfo

    class HostileTimezone(tzinfo):
        def utcoffset(self, _value: datetime | None) -> timedelta:
            raise RuntimeError("timezone-secret")

        def dst(self, _value: datetime | None) -> timedelta:
            return timedelta(0)

    collector, raw, transport = _collect(
        tmp_path,
        clock=lambda: datetime(2026, 9, 6, tzinfo=HostileTimezone()),
    )
    with pytest.raises(OfficialSzseCalendarError) as error:
        collector.collect()
    assert str(error.value) == "official SZSE calendar observation time is invalid"
    assert error.value.__context__ is None
    assert "timezone-secret" not in "".join(traceback.format_exception(error.value))
    assert transport.calls == []
    assert raw.list("szse-calendar", "2026-09-06") == []
