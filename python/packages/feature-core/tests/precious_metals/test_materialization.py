from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

from feature_core import (
    BatchInputLineage,
    BatchInputReference,
    BatchInputRow,
    BatchRunMetadata,
    DatasetExporter,
    DatasetExportRequest,
    DatasetManifest,
    DatasetPartitionRole,
    DatasetPartitionSpec,
    DatasetSourceSpec,
    FeatureHistoryRecord,
    FeatureHistoryRepository,
    FeatureValueType,
    InMemoryFeatureHistoryBackend,
    InputOrigin,
    MaterializedFeatureRow,
    RegistrySnapshotRef,
    SourceKind,
)
from feature_core.batch.models import canonical_checksum
from feature_core.online import OnlineEventSource, OnlineFeatureEvent
from feature_core.precious_metals import (
    BatchPreciousMetalsAdapter,
    OnlinePreciousMetalsAdapter,
    PreciousMetalsPolicy,
    calculate_feature,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
DECISION = datetime(2026, 8, 24, 15, 0, tzinfo=SHANGHAI)
FUND_ID = "518880.SH"


def _digest(value: str) -> str:
    return f"sha256:{sha256(value.encode()).hexdigest()}"


def _payload(record_type: str, data: dict[str, object], identity: str) -> dict[str, object]:
    event_time = DECISION - timedelta(minutes=10)
    return {
        "recordType": record_type,
        "data": data,
        "eventTime": data.get("eventTime", event_time.isoformat()),
        "availableTime": data.get("availableTime", (event_time + timedelta(minutes=2)).isoformat()),
        "ingestTime": data.get("ingestTime", (event_time + timedelta(minutes=1)).isoformat()),
        "source": data.get("source", "fixture.synthetic"),
        "rawObjectId": data.get("rawObjectId", f"raw:{identity}"),
        "payloadDigest": _digest(identity),
        "processingTime": data.get(
            "processingTime", (event_time + timedelta(minutes=3)).isoformat()
        ),
    }


def _fund_data() -> dict[str, object]:
    return {
        "unifiedCode": FUND_ID,
        "exchange": "SH",
        "assetType": "ETF",
        "fundAssetClass": "PRECIOUS_METALS",
        "underlyingCommodity": "GOLD",
        "tradingCurrency": "CNY",
        "navCurrency": "CNY",
        "benchmarkOrTrackingIndex": "display-only",
        "benchmarkSeriesId": "benchmark:v1:sge:au9999-close-cny",
        "managementFeeRate": "0.005",
        "validFrom": "2026-01-01",
        "validTo": None,
        "source": "fixture.synthetic.fund",
        "publishTime": (DECISION - timedelta(minutes=10)).isoformat(),
        "ingestTime": (DECISION - timedelta(minutes=8)).isoformat(),
        "availableTime": (DECISION - timedelta(minutes=8)).isoformat(),
        "processingTime": (DECISION - timedelta(minutes=7)).isoformat(),
        "rawObjectId": "fund-v1",
        "confidence": "0.95",
        "reviewStatus": "REVIEWED",
    }


def _nav_data() -> dict[str, object]:
    timestamp = (DECISION - timedelta(minutes=10)).isoformat()
    return {
        "unifiedCode": FUND_ID,
        "date": DECISION.date().isoformat(),
        "nav": "10.00",
        "inav": "10.00",
        "eventTime": timestamp,
        "publishTime": timestamp,
        "ingestTime": (DECISION - timedelta(minutes=8)).isoformat(),
        "availableTime": (DECISION - timedelta(minutes=8)).isoformat(),
        "processingTime": (DECISION - timedelta(minutes=7)).isoformat(),
        "rawObjectId": "nav-v1",
        "source": "fixture.synthetic.nav",
    }


def _rows() -> tuple[BatchInputRow, ...]:
    event_time = DECISION - timedelta(minutes=10)
    common = (
        ("fund", "domain.precious_metal_fund", _fund_data()),
        ("nav", "domain.fund_nav", _nav_data()),
    )
    return tuple(
        BatchInputRow(
            row_id=f"row-{record_type}",
            entity_id=FUND_ID,
            event_time=event_time,
            available_time=event_time + timedelta(minutes=2),
            lineage=BatchInputLineage(
                reference=BatchInputReference(
                    origin=InputOrigin.SOURCE_CONTRACT,
                    name=contract_name,
                    version="v1",
                ),
                source_revision=f"revision:{record_type}",
            ),
            payload=_payload(record_type, data, record_type),
        )
        for record_type, contract_name, data in common
    )


def _events(rows: tuple[BatchInputRow, ...]) -> tuple[OnlineFeatureEvent, ...]:
    return tuple(
        OnlineFeatureEvent(
            event_id=row.row_id,
            entity_id=row.entity_id,
            source=OnlineEventSource.DOMAIN,
            contract_name=row.contract_name,
            contract_version=row.contract_version,
            source_revision=row.source_revision or "missing",
            event_time=row.event_time,
            available_time=row.available_time,
            ingest_time=datetime.fromisoformat(str(row.payload["ingestTime"])),
            payload=row.payload,
        )
        for row in rows
    )


def test_batch_and_online_adapters_share_one_calculator_result() -> None:
    rows = _rows()
    policy = PreciousMetalsPolicy(
        benchmarks=(),
    )
    batch = BatchPreciousMetalsAdapter(policy).calculate(
        "precious_metals_fund.premium_discount_bps", rows, DECISION
    )
    online = OnlinePreciousMetalsAdapter(policy).calculate(
        "precious_metals_fund.premium_discount_bps", _events(rows), DECISION
    )
    direct = calculate_feature(
        "precious_metals_fund.premium_discount_bps",
        BatchPreciousMetalsAdapter(policy).context(rows, DECISION),
        policy,
    )
    assert batch.canonical_payload == online.canonical_payload == direct.canonical_payload


def _history_record(
    event_time: datetime,
    nonce: str,
    *,
    available_time: datetime | None = None,
    decision_time: datetime | None = None,
) -> FeatureHistoryRecord:
    resolved_available_time = available_time or (event_time + timedelta(minutes=1))
    resolved_decision_time = decision_time or (event_time + timedelta(hours=1))
    ref = RegistrySnapshotRef(
        namespace_id="precious_metals.funds",
        head_fingerprint=_digest("registry-head"),
        feature_name="precious_metals_fund.premium_discount_bps",
        feature_version="v1",
        feature_fingerprint=_digest("feature"),
        algorithm_version="v1",
    )
    row = MaterializedFeatureRow(
        feature_name=ref.feature_name,
        feature_version=ref.feature_version,
        feature_fingerprint=ref.feature_fingerprint,
        algorithm_version=ref.algorithm_version,
        partition_key=event_time.date().isoformat(),
        entity_id=FUND_ID,
        event_time=event_time,
        available_time=resolved_available_time,
        decision_time=resolved_decision_time,
        value="200.000000",
        input_row_ids=(f"row-{nonce}",),
        input_lineage=(),
        input_checksum=_digest(f"input-{nonce}"),
        source_kind=SourceKind.PARQUET,
        source_snapshot_version="precious-metals-fixture-v1",
    )
    run = BatchRunMetadata(
        run_id=f"run-{nonce}",
        partition_key=row.partition_key,
        partition_start=event_time,
        partition_end=event_time + timedelta(days=1),
        registry_ref=ref,
        source_kind=SourceKind.PARQUET,
        source_snapshot_version="precious-metals-fixture-v1",
        decision_time=row.decision_time,
        data_cutoff_time=row.available_time,
        calculator_implementation_fingerprint=_digest("calculator-v1"),
        determinism_verified=True,
        input_manifest_checksum=_digest("manifest-input"),
        input_count=1,
        output_count=1,
        input_checksum=row.input_checksum,
        output_checksum=_digest(f"output-{nonce}"),
    )
    return FeatureHistoryRecord.from_batch_materialization(
        row=row,
        run=run,
        processing_time=resolved_available_time + timedelta(minutes=1),
        value_type=FeatureValueType.DECIMAL,
        revision_nonce=nonce,
    )


def test_dataset_exporter_manifest_rebuild_and_future_cutoff_are_deterministic(
    tmp_path: Path,
) -> None:
    base = datetime(2026, 8, 1, 9, 0, tzinfo=SHANGHAI)
    records = (
        _history_record(base, "train"),
        _history_record(base + timedelta(days=2), "eval"),
        _history_record(
            base,
            "future-revision",
            available_time=base + timedelta(days=10),
            decision_time=base + timedelta(days=11),
        ),
    )
    backend = InMemoryFeatureHistoryBackend()
    FeatureHistoryRepository(backend).append(records)
    repository = FeatureHistoryRepository(backend)
    fingerprint = _digest("feature")

    def source(start: datetime, end: datetime, as_of: datetime) -> DatasetSourceSpec:
        return DatasetSourceSpec(
            namespace_id="precious_metals.funds",
            feature_name="precious_metals_fund.premium_discount_bps",
            feature_version="v1",
            feature_fingerprint=fingerprint,
            entity_ids=(FUND_ID,),
            event_start=start,
            event_end=end,
            as_of=as_of,
        )

    request = DatasetExportRequest(
        dataset_name="precious-metals-fixture",
        dataset_version="1.0.0",
        created_at=base + timedelta(days=5),
        partitions=(
            DatasetPartitionSpec(
                partition_id="train",
                role=DatasetPartitionRole.TRAIN,
                sources=(
                    source(
                        base - timedelta(days=1), base + timedelta(days=1), base + timedelta(days=5)
                    ),
                ),
            ),
            DatasetPartitionSpec(
                partition_id="evaluation",
                role=DatasetPartitionRole.EVALUATION,
                sources=(
                    source(
                        base + timedelta(days=1), base + timedelta(days=4), base + timedelta(days=5)
                    ),
                ),
            ),
        ),
        rebuild_command=(
            "uv",
            "run",
            "--package",
            "feature-core",
            "python",
            "research/datasets/rebuild.py",
            "--manifest",
            "dataset-manifest.json",
            "--output",
            "research/datasets/rebuilt",
            "--repository-profile",
            "feature-history",
        ),
    )
    exporter = DatasetExporter(repository)
    first = exporter.export(request, tmp_path / "first")
    rebuilt = exporter.rebuild(first, tmp_path / "rebuilt")
    exporter.verify(tmp_path / "rebuilt" / request.dataset_name / request.dataset_version)
    assert first.manifest_checksum == rebuilt.manifest_checksum
    assert first.manifest_checksum == canonical_checksum(first)
    assert [item.file_checksum for item in first.partitions] == [
        item.file_checksum for item in rebuilt.partitions
    ]
    assert sum(item.row_count for item in first.partitions) == 2
    for artifact in first.partitions:
        first_path = (
            tmp_path
            / "first"
            / request.dataset_name
            / request.dataset_version
            / artifact.relative_path
        )
        rebuilt_path = (
            tmp_path
            / "rebuilt"
            / request.dataset_name
            / request.dataset_version
            / artifact.relative_path
        )
        assert first_path.read_bytes() == rebuilt_path.read_bytes()
    assert first.created_at.tzinfo == SHANGHAI


def test_committed_dataset_manifest_uses_public_schema_and_real_digests() -> None:
    path = (
        Path(__file__).parents[3]
            / "backtest-core/tests/fixtures/precious-metals/dataset/dataset-manifest.json"
    )
    manifest = DatasetManifest.from_json(path.read_text(encoding="utf-8"))
    assert manifest.schema_version == "1.0.0"
    assert len(manifest.partitions) == 2
    assert all(item.row_count > 0 for item in manifest.partitions)
    assert all(item.file_checksum.startswith("sha256:") for item in manifest.partitions)
