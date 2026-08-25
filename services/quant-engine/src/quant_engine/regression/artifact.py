"""Immutable regression-run artifact contract and digest binding."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import cast

from ashare_contracts.backtest_regression_semantics import (
    ROOT_PYPROJECT_ENTRY,
    SERVICE_PYPROJECT_ENTRY,
    UV_LOCK_ENTRY,
    toolchain_evidence_sha256,
)

from .canonical import (
    RegressionCanonicalizationError,
    canonical_json,
    canonical_sha256,
    canonicalize,
    decimal_string,
    require_sha256,
    require_timestamp,
)


class RegressionValidationError(ValueError):
    """Raised when an artifact, baseline, or comparison payload is invalid."""


class RegressionIntegrityError(RegressionValidationError):
    """Raised when content and an integrity binding disagree."""


_SCHEMA_VERSION = "backtest-regression-run-v1"
_C14N_VERSION = "backtest-regression-c14n-v1"
_ID_MAX = 128
_ID_ALLOWED = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")
_METRIC_NAMES = (
    "cumulativeChainedReturn",
    "annualizedReturn",
    "annualizedVolatility",
    "maximumDrawdown",
    "sharpe",
    "sortino",
    "calmar",
)


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RegressionValidationError(f"{field_name} must be an object")
    return cast(dict[str, object], value)


def _exact(value: object, keys: set[str], field_name: str) -> dict[str, object]:
    item = _mapping(value, field_name)
    actual = set(item)
    missing = keys - actual
    unknown = actual - keys
    if missing:
        raise RegressionValidationError(f"{field_name} missing keys: {sorted(missing)}")
    if unknown:
        raise RegressionValidationError(f"{field_name} contains unknown keys: {sorted(unknown)}")
    return item


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise RegressionValidationError(f"{field_name} must be a non-empty string")
    return value


def safe_id(value: object, field_name: str) -> str:
    text = _text(value, field_name)
    if len(text) > _ID_MAX or any(char not in _ID_ALLOWED for char in text):
        raise RegressionValidationError(f"{field_name} is not a safe ASCII id")
    if ".." in text or any(char.isspace() for char in text) or "\x00" in text:
        raise RegressionValidationError(f"{field_name} is not a safe path id")
    return text


def _list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise RegressionValidationError(f"{field_name} must be an array")
    return cast(list[object], value)


def _nonnegative_int(value: object, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise RegressionValidationError(f"{field_name} must be a non-negative integer")
    return value


def _decimal(value: object, field_name: str) -> str:
    try:
        if not isinstance(value, str):
            raise RegressionCanonicalizationError(
                f"{field_name} must be a canonical Decimal string"
            )
        normalized = decimal_string(value, field_name)
        if normalized != value:
            raise RegressionCanonicalizationError(
                f"{field_name} must use canonical Decimal spelling"
            )
        return value
    except (RegressionCanonicalizationError, TypeError) as error:
        raise RegressionValidationError(str(error)) from error


def _time(value: object, field_name: str) -> str:
    try:
        return require_timestamp(value, field_name)
    except RegressionCanonicalizationError as error:
        raise RegressionValidationError(str(error)) from error


def _digest(value: object, field_name: str) -> str:
    try:
        return require_sha256(value, field_name)
    except RegressionCanonicalizationError as error:
        raise RegressionValidationError(str(error)) from error


def _digest_reference(value: object, field_name: str) -> dict[str, object]:
    item = _mapping(value, field_name)
    kind = item.get("kind")
    if kind == "CONTENT_SHA256":
        result = _exact(item, {"kind", "sha256"}, field_name)
        _digest(result["sha256"], f"{field_name}.sha256")
        return result
    if kind == "OPAQUE_EXTERNAL":
        result = _exact(item, {"kind", "namespace", "value"}, field_name)
        _text(result["namespace"], f"{field_name}.namespace")
        _text(result["value"], f"{field_name}.value")
        return result
    raise RegressionValidationError(f"{field_name}.kind is unsupported")


def _validate_observations(value: object, field_name: str, value_key: str) -> None:
    items = _list(value, field_name)
    if len(items) < 4:
        raise RegressionValidationError(f"{field_name} must contain at least four observations")
    previous: str | None = None
    for index, raw in enumerate(items):
        item = _exact(
            raw,
            {"observationTime", value_key, "provenanceDigest"},
            f"{field_name}[{index}]",
        )
        current = _time(item["observationTime"], f"{field_name}[{index}].observationTime")
        if previous is not None and current <= previous:
            raise RegressionValidationError(f"{field_name} must be strictly time ordered")
        previous = current
        _decimal(item[value_key], f"{field_name}[{index}].{value_key}")
        _digest(item["provenanceDigest"], f"{field_name}[{index}].provenanceDigest")


def _validate_t_plus_one(value: object, field_name: str, *, inputs: bool) -> None:
    if inputs:
        item = _exact(
            value,
            {
                "buyOrderId",
                "sellOrderId",
                "buyExecutionInputDigest",
                "sameDaySellExecutionInputDigest",
                "nextDaySellExecutionInputDigest",
                "sameDaySellabilityDigest",
                "nextDaySellabilityDigest",
                "sameDayBatchDigest",
                "nextDayBatchDigest",
            },
            field_name,
        )
        safe_id(item["buyOrderId"], f"{field_name}.buyOrderId")
        safe_id(item["sellOrderId"], f"{field_name}.sellOrderId")
        for name in (
            "buyExecutionInputDigest",
            "sameDaySellExecutionInputDigest",
            "nextDaySellExecutionInputDigest",
            "sameDaySellabilityDigest",
            "nextDaySellabilityDigest",
            "sameDayBatchDigest",
            "nextDayBatchDigest",
        ):
            _digest(item[name], f"{field_name}.{name}")
        return

    results = _exact(value, {"sameDay", "nextDay"}, field_name)
    for name in ("sameDay", "nextDay"):
        item = _exact(
            results[name],
            {
                "orderId",
                "status",
                "rejectReason",
                "fillCount",
                "batchDigest",
                "resultDigest",
                "tradingDate",
                "sellabilityDigest",
            },
            f"{field_name}.{name}",
        )
        safe_id(item["orderId"], f"{field_name}.{name}.orderId")
        if item["status"] not in ("REJECTED", "FILLED"):
            raise RegressionValidationError(f"{field_name}.{name}.status is unsupported")
        if item["rejectReason"] is not None:
            _text(item["rejectReason"], f"{field_name}.{name}.rejectReason")
        _nonnegative_int(item["fillCount"], f"{field_name}.{name}.fillCount")
        _digest(item["batchDigest"], f"{field_name}.{name}.batchDigest")
        _digest(item["resultDigest"], f"{field_name}.{name}.resultDigest")
        trading_date = _text(item["tradingDate"], f"{field_name}.{name}.tradingDate")
        if len(trading_date) != 10 or trading_date[4] != "-" or trading_date[7] != "-":
            raise RegressionValidationError(f"{field_name}.{name}.tradingDate is invalid")
        if item["sellabilityDigest"] is not None:
            _digest(item["sellabilityDigest"], f"{field_name}.{name}.sellabilityDigest")


def _validate_artifact_payload(payload: dict[str, object]) -> None:
    required = {
        "schemaVersion",
        "canonicalizationVersion",
        "suiteId",
        "runId",
        "fixtureId",
        "trust",
        "manifest",
        "inputs",
        "provenance",
        "versions",
        "results",
        "artifactSha256",
    }
    _exact(payload, required, "artifact")
    if payload["schemaVersion"] != _SCHEMA_VERSION:
        raise RegressionValidationError("artifact.schemaVersion is unsupported")
    if payload["canonicalizationVersion"] != _C14N_VERSION:
        raise RegressionValidationError("artifact.canonicalizationVersion is unsupported")
    for field_name in ("suiteId", "runId", "fixtureId"):
        safe_id(payload[field_name], f"artifact.{field_name}")

    trust = _exact(
        payload["trust"],
        {"mode", "evidenceIntegrityConfidence", "evidenceRefs"},
        "artifact.trust",
    )
    if trust["mode"] not in ("FIXTURE_SELF_CONTAINED", "VERIFIED"):
        raise RegressionValidationError("artifact.trust.mode is unsupported")
    if trust["evidenceIntegrityConfidence"] not in ("LOW", "MEDIUM", "HIGH"):
        raise RegressionValidationError("artifact.trust.evidenceIntegrityConfidence is unsupported")
    refs = _list(trust["evidenceRefs"], "artifact.trust.evidenceRefs")
    for index, ref in enumerate(refs):
        _digest_reference(ref, f"artifact.trust.evidenceRefs[{index}]")

    manifest = _exact(payload["manifest"], {"json", "sha256"}, "artifact.manifest")
    manifest_json = _mapping(manifest["json"], "artifact.manifest.json")
    manifest_digest = _digest(manifest["sha256"], "artifact.manifest.sha256")
    if canonical_sha256(manifest_json) != manifest_digest:
        raise RegressionIntegrityError("manifest digest does not match manifest JSON")

    inputs = _exact(
        payload["inputs"],
        {
            "fixtureSha256",
            "executionInputDigests",
            "portfolioHistoryRef",
            "valuationLineage",
            "navObservations",
            "riskFreeObservations",
            "tPlusOne",
        },
        "artifact.inputs",
    )
    _digest(inputs["fixtureSha256"], "artifact.inputs.fixtureSha256")
    execution_digests = _list(
        inputs["executionInputDigests"], "artifact.inputs.executionInputDigests"
    )
    for index, value in enumerate(execution_digests):
        _digest(value, f"artifact.inputs.executionInputDigests[{index}]")
    if tuple(execution_digests) != tuple(
        sorted(set(cast(tuple[str, ...], tuple(execution_digests))))
    ):
        raise RegressionValidationError(
            "artifact.inputs.executionInputDigests must be sorted and unique"
        )
    history = _exact(
        inputs["portfolioHistoryRef"],
        {"tapeId", "eventTapeDigest", "eventCount"},
        "artifact.inputs.portfolioHistoryRef",
    )
    safe_id(history["tapeId"], "artifact.inputs.portfolioHistoryRef.tapeId")
    _digest(history["eventTapeDigest"], "artifact.inputs.portfolioHistoryRef.eventTapeDigest")
    _nonnegative_int(history["eventCount"], "artifact.inputs.portfolioHistoryRef.eventCount")
    lineage = _exact(
        inputs["valuationLineage"],
        {"valuationPolicyId", "valuationPolicyVersion", "valuationPolicyDigest", "valuations"},
        "artifact.inputs.valuationLineage",
    )
    _text(lineage["valuationPolicyId"], "artifact.inputs.valuationLineage.valuationPolicyId")
    _text(
        lineage["valuationPolicyVersion"], "artifact.inputs.valuationLineage.valuationPolicyVersion"
    )
    _digest(
        lineage["valuationPolicyDigest"], "artifact.inputs.valuationLineage.valuationPolicyDigest"
    )
    valuations = _list(lineage["valuations"], "artifact.inputs.valuationLineage.valuations")
    previous_time: str | None = None
    for index, raw in enumerate(valuations):
        item = _exact(
            raw,
            {"observationTime", "inputDigest", "markDigest", "stateDigest", "nav"},
            f"artifact.inputs.valuationLineage.valuations[{index}]",
        )
        current_time = _time(item["observationTime"], f"valuation[{index}].observationTime")
        if previous_time is not None and current_time <= previous_time:
            raise RegressionValidationError("valuation lineage must be strictly time ordered")
        previous_time = current_time
        for name in ("inputDigest", "markDigest", "stateDigest"):
            _digest(item[name], f"valuation[{index}].{name}")
        _decimal(item["nav"], f"valuation[{index}].nav")
    _validate_observations(inputs["navObservations"], "artifact.inputs.navObservations", "nav")
    _validate_observations(
        inputs["riskFreeObservations"], "artifact.inputs.riskFreeObservations", "rate"
    )
    nav_times = tuple(
        cast(dict[str, object], item)["observationTime"]
        for item in _list(inputs["navObservations"], "artifact.inputs.navObservations")
    )
    rf_times = tuple(
        cast(dict[str, object], item)["observationTime"]
        for item in _list(inputs["riskFreeObservations"], "artifact.inputs.riskFreeObservations")
    )
    if nav_times != rf_times:
        raise RegressionValidationError("NAV and risk-free observations must be aligned")
    _validate_t_plus_one(inputs["tPlusOne"], "artifact.inputs.tPlusOne", inputs=True)

    provenance = _exact(
        payload["provenance"],
        {"code", "config", "dependencies", "toolchain"},
        "artifact.provenance",
    )
    code = _exact(provenance["code"], {"allowlist", "treeSha256"}, "artifact.provenance.code")
    allowlist = _list(code["allowlist"], "artifact.provenance.code.allowlist")
    paths: list[str] = []
    for index, raw in enumerate(allowlist):
        item = _exact(raw, {"path", "sha256"}, f"artifact.provenance.code.allowlist[{index}]")
        path = _text(item["path"], f"allowlist[{index}].path")
        if (
            not path
            or "\\" in path
            or path.startswith("/")
            or "://" in path
            or any(part in ("", ".", "..") for part in path.split("/"))
        ):
            raise RegressionValidationError("code allowlist paths must be relative")
        paths.append(path)
        _digest(item["sha256"], f"allowlist[{index}].sha256")
    if tuple(paths) != tuple(sorted(set(paths))):
        raise RegressionValidationError("code allowlist must be sorted and unique")
    _digest(code["treeSha256"], "artifact.provenance.code.treeSha256")

    for name in ("config", "dependencies"):
        entries = _list(provenance[name], f"artifact.provenance.{name}")
        entry_names: list[str] = []
        for index, raw in enumerate(entries):
            item = _exact(raw, {"name", "version", "sha256"}, f"{name}[{index}]")
            entry_names.append(_text(item["name"], f"{name}[{index}].name"))
            _text(item["version"], f"{name}[{index}].version")
            _digest(item["sha256"], f"{name}[{index}].sha256")
        if tuple(entry_names) != tuple(sorted(set(entry_names))):
            raise RegressionValidationError(f"artifact.provenance.{name} must be sorted and unique")

    toolchain = _exact(
        provenance["toolchain"],
        {
            "python",
            "uv",
            "hatchling",
            "rootPyprojectSha256",
            "servicePyprojectSha256",
            "uvLockSha256",
            "evidenceSha256",
        },
        "artifact.provenance.toolchain",
    )
    if (
        toolchain["python"] != "3.12.13"
        or toolchain["uv"] != "0.12.3"
        or toolchain["hatchling"] != "1.27.0"
    ):
        raise RegressionValidationError(
            "artifact toolchain is not pinned to the repository versions"
        )
    _digest(toolchain["evidenceSha256"], "artifact.provenance.toolchain.evidenceSha256")
    _digest(
        toolchain["rootPyprojectSha256"],
        "artifact.provenance.toolchain.rootPyprojectSha256",
    )
    _digest(
        toolchain["servicePyprojectSha256"],
        "artifact.provenance.toolchain.servicePyprojectSha256",
    )
    _digest(toolchain["uvLockSha256"], "artifact.provenance.toolchain.uvLockSha256")
    config_entries = _list(provenance["config"], "artifact.provenance.config")
    dependency_entries = _list(
        provenance["dependencies"], "artifact.provenance.dependencies"
    )

    def unique_entry(
        entries: list[object], name: str, context: str
    ) -> dict[str, object]:
        matches: list[dict[str, object]] = []
        for index, item in enumerate(entries):
            raw_item: object = item
            if isinstance(raw_item, dict):
                typed_item = cast(dict[str, object], raw_item)
                if typed_item.get("name") == name:
                    matches.append(_mapping(typed_item, f"{context}[{index}]"))
        if len(matches) != 1:
            raise RegressionIntegrityError(
                f"{context} must contain exactly one {name} entry"
            )
        return matches[0]

    root_entry = unique_entry(
        config_entries, ROOT_PYPROJECT_ENTRY, "artifact.provenance.config"
    )
    service_entry = unique_entry(
        config_entries, SERVICE_PYPROJECT_ENTRY, "artifact.provenance.config"
    )
    lock_entry = unique_entry(
        dependency_entries, UV_LOCK_ENTRY, "artifact.provenance.dependencies"
    )
    if root_entry["sha256"] != toolchain["rootPyprojectSha256"]:
        raise RegressionIntegrityError("root pyproject digest binding is invalid")
    if service_entry["sha256"] != toolchain["servicePyprojectSha256"]:
        raise RegressionIntegrityError("service pyproject digest binding is invalid")
    if lock_entry["sha256"] != toolchain["uvLockSha256"]:
        raise RegressionIntegrityError("uv.lock digest binding is invalid")
    evidence_payload = {
        key: cast(str, toolchain[key])
        for key in (
            "python",
            "uv",
            "hatchling",
            "rootPyprojectSha256",
            "servicePyprojectSha256",
            "uvLockSha256",
        )
    }
    if toolchain["evidenceSha256"] != toolchain_evidence_sha256(evidence_payload):
        raise RegressionIntegrityError("toolchain evidence digest is invalid")

    versions = _exact(
        payload["versions"],
        {
            "engine",
            "manifest",
            "eventOrder",
            "execution",
            "matching",
            "portfolio",
            "valuation",
            "metrics",
            "strategy",
            "policy",
            "fixture",
        },
        "artifact.versions",
    )
    for name, value in versions.items():
        _text(value, f"artifact.versions.{name}")

    results = _exact(
        payload["results"],
        {"counts", "pnl", "finalNav", "finalValuation", "metrics", "observations", "tPlusOne"},
        "artifact.results",
    )
    counts = _exact(
        results["counts"],
        {
            "events",
            "intents",
            "orders",
            "fills",
            "navObservations",
            "tPlusOneRejected",
            "nextDaySellFills",
        },
        "artifact.results.counts",
    )
    for name, value in counts.items():
        _nonnegative_int(value, f"artifact.results.counts.{name}")
    pnl = _exact(
        results["pnl"], {"realized", "unrealized", "total", "fees"}, "artifact.results.pnl"
    )
    for name, value in pnl.items():
        _decimal(value, f"artifact.results.pnl.{name}")
    _decimal(results["finalNav"], "artifact.results.finalNav")
    valuation = _exact(
        results["finalValuation"],
        {"cutoffTime", "nav", "totalPnl", "stateDigest", "inputDigest", "sampleCount"},
        "artifact.results.finalValuation",
    )
    _time(valuation["cutoffTime"], "artifact.results.finalValuation.cutoffTime")
    _decimal(valuation["nav"], "artifact.results.finalValuation.nav")
    _decimal(valuation["totalPnl"], "artifact.results.finalValuation.totalPnl")
    _digest(valuation["stateDigest"], "artifact.results.finalValuation.stateDigest")
    _digest(valuation["inputDigest"], "artifact.results.finalValuation.inputDigest")
    _nonnegative_int(valuation["sampleCount"], "artifact.results.finalValuation.sampleCount")
    metrics = _exact(results["metrics"], set(_METRIC_NAMES), "artifact.results.metrics")
    for name in _METRIC_NAMES:
        metric = _exact(metrics[name], {"status", "value"}, f"metrics.{name}")
        _text(metric["status"], f"metrics.{name}.status")
        if metric["value"] is not None:
            _decimal(metric["value"], f"metrics.{name}.value")
    _validate_observations(results["observations"], "artifact.results.observations", "nav")
    _validate_t_plus_one(results["tPlusOne"], "artifact.results.tPlusOne", inputs=False)

    _digest(payload["artifactSha256"], "artifact.artifactSha256")


def compute_artifact_sha256(payload: object) -> str:
    data = _mapping(payload, "artifact")
    without_digest = {key: value for key, value in data.items() if key != "artifactSha256"}
    return canonical_sha256(without_digest)


@dataclass(frozen=True, slots=True)
class RegressionRunArtifact:
    """Validated immutable view of one canonical regression run."""

    payload: dict[str, object]

    def __post_init__(self) -> None:
        try:
            normalized = cast(dict[str, object], canonicalize(self.payload))
        except RegressionCanonicalizationError as error:
            raise RegressionValidationError(str(error)) from error
        _validate_artifact_payload(normalized)
        if compute_artifact_sha256(normalized) != normalized["artifactSha256"]:
            raise RegressionIntegrityError("artifactSha256 does not match canonical artifact bytes")
        object.__setattr__(self, "payload", normalized)

    @classmethod
    def from_dict(cls, payload: object) -> RegressionRunArtifact:
        return cls(_mapping(payload, "artifact"))

    @classmethod
    def build(cls, payload_without_digest: dict[str, object]) -> RegressionRunArtifact:
        payload = deepcopy(payload_without_digest)
        payload["artifactSha256"] = compute_artifact_sha256(payload)
        return cls(payload)

    @staticmethod
    def compute_sha256(payload: object) -> str:
        return compute_artifact_sha256(payload)

    @property
    def artifact_sha256(self) -> str:
        return cast(str, self.payload["artifactSha256"])

    @property
    def suite_id(self) -> str:
        return cast(str, self.payload["suiteId"])

    @property
    def run_id(self) -> str:
        return cast(str, self.payload["runId"])

    def to_dict(self) -> dict[str, object]:
        return deepcopy(self.payload)

    def canonical_bytes(self) -> bytes:
        return canonical_json(self.payload).encode("utf-8")


def parse_artifact_bytes(raw: bytes) -> RegressionRunArtifact:
    from .canonical import parse_canonical_json

    return RegressionRunArtifact.from_dict(parse_canonical_json(raw, field_name="artifact"))


__all__ = [
    "RegressionCanonicalizationError",
    "RegressionIntegrityError",
    "RegressionRunArtifact",
    "RegressionValidationError",
    "compute_artifact_sha256",
    "parse_artifact_bytes",
    "safe_id",
]
