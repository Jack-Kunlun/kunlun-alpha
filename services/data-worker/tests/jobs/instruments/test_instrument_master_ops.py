"""Operational boundary tests for the private instrument-master provider."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from data_worker.jobs.instruments import runtime


def test_provider_migration_runtime_requires_its_dedicated_dsn(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = runtime.migrate_main(
        [],
        environ={
            "KUNLUN_POSTGRES_DSN": "postgresql://shared-secret",
        },
        connection_factory=lambda _dsn, _schema: object(),
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "instrument master sync failed"
    assert "shared-secret" not in captured.out + captured.err


def test_provider_migration_uses_dedicated_dsn_and_provider_migration_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _Connection:
        closed = False

        def close(self) -> None:
            self.closed = True

    connection = _Connection()
    calls: list[object] = []

    def fake_migration(supplied_connection: object) -> None:
        calls.append(supplied_connection)

    monkeypatch.setattr(runtime, "apply_instrument_master_provider_migration", fake_migration)
    exit_code = runtime.migrate_main(
        [],
        environ={
            "INSTRUMENT_MASTER_MIGRATOR_DSN": "postgresql://dedicated-migrator",
            "KUNLUN_POSTGRES_DSN": "postgresql://shared-must-not-be-used",
        },
        connection_factory=lambda dsn, schema: (
            dsn == "postgresql://dedicated-migrator"
            and schema == "kunlun_instrument_provider"
            and connection
        ),
    )

    assert exit_code == 0
    assert calls == [connection]
    assert connection.closed
    assert capsys.readouterr().out == ""


def test_provider_migration_closes_connection_after_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _Connection:
        closed = False

        def close(self) -> None:
            self.closed = True

    connection = _Connection()

    def failing_migration(_: object) -> None:
        raise RuntimeError("provider details must not escape")

    monkeypatch.setattr(runtime, "apply_instrument_master_provider_migration", failing_migration)
    exit_code = runtime.migrate_main(
        [],
        environ={"INSTRUMENT_MASTER_MIGRATOR_DSN": "postgresql://secret"},
        connection_factory=lambda _dsn, _schema: connection,
    )

    assert exit_code == 1
    assert connection.closed
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "instrument master sync failed"
    assert "provider details" not in captured.err


def test_role_bootstrap_is_explicit_and_secret_free() -> None:
    bootstrap = Path("infra/docker/migrations/instrument-master-roles.sql")
    assert bootstrap.exists()
    body = bootstrap.read_text(encoding="utf-8")
    for role in (
        "kunlun_im_owner",
        "kunlun_im_migrator",
        "kunlun_im_runtime",
        "kunlun_im_reader",
    ):
        assert role in body
    assert "\\getenv" in body
    assert "PASSWORD=" not in body
    assert "ALTER DEFAULT PRIVILEGES" in body
    assert "REVOKE ALL ON TABLES FROM PUBLIC" in body
    assert "REVOKE ALL ON FUNCTIONS FROM PUBLIC" in body
    assert 'test -n "$INSTRUMENT_MASTER_MIGRATOR_PASSWORD"' in body
    assert 'test -n "$INSTRUMENT_MASTER_RUNTIME_PASSWORD"' in body
    assert "\\error" not in body
    assert "\\quit" not in body
    assert body.count("\\echo '") == 4
    assert body.count("SELECT 1 / 0;") == 4
    assert "BEGIN;" in body
    assert "COMMIT;" in body
    assert "WITH INHERIT FALSE, SET TRUE, ADMIN FALSE" in body
    normalized = " ".join(body.split())
    assert "REVOKE ALL ON SCHEMA kunlun FROM kunlun_im_migrator;" in normalized
    assert (
        "REVOKE ALL ON TABLE kunlun.data_worker_schema_migrations FROM kunlun_im_migrator;"
        in normalized
    )
    assert "GRANT USAGE ON SCHEMA kunlun TO kunlun_im_migrator;" in body
    assert (
        "GRANT SELECT ON TABLE kunlun.data_worker_schema_migrations TO kunlun_im_migrator;"
        in normalized
    )


@pytest.mark.parametrize(
    ("migrator_value", "runtime_value", "expected_message", "unexpected_message"),
    (
        (None, "runtime-probe-secret", "MIGRATOR_PASSWORD is required", "RUNTIME_PASSWORD"),
        ("", "runtime-probe-secret", "MIGRATOR_PASSWORD must be non-empty", "RUNTIME_PASSWORD"),
        ("migrator-probe-secret", None, "RUNTIME_PASSWORD is required", "MIGRATOR_PASSWORD"),
        ("migrator-probe-secret", "", "RUNTIME_PASSWORD must be non-empty", "MIGRATOR_PASSWORD"),
    ),
)
def test_role_bootstrap_psql_meta_rejects_missing_or_empty_passwords_without_sql(
    migrator_value: str | None,
    runtime_value: str | None,
    expected_message: str,
    unexpected_message: str,
) -> None:
    """Exercise psql's actual meta-command preflight when a DSN is available."""

    psql = shutil.which("psql")
    dsn = os.environ.get("KUNLUN_TEST_PSQL_DSN") or os.environ.get("KUNLUN_TEST_POSTGRES_DSN")
    if psql is None or not dsn:
        pytest.skip("psql and KUNLUN_TEST_PSQL_DSN are required for the executable probe")

    bootstrap = Path("infra/docker/migrations/instrument-master-roles.sql")
    body = bootstrap.read_text(encoding="utf-8")
    preflight, _ddl = body.split("\nDO $bootstrap$\n", maxsplit=1)
    preflight += "\n"
    probe_env = os.environ.copy()
    probe_env.pop("INSTRUMENT_MASTER_MIGRATOR_PASSWORD", None)
    probe_env.pop("INSTRUMENT_MASTER_RUNTIME_PASSWORD", None)
    if migrator_value is not None:
        probe_env["INSTRUMENT_MASTER_MIGRATOR_PASSWORD"] = migrator_value
    if runtime_value is not None:
        probe_env["INSTRUMENT_MASTER_RUNTIME_PASSWORD"] = runtime_value
    completed = subprocess.run(
        [psql, "--no-psqlrc", "--dbname", dsn],
        input=preflight,
        text=True,
        capture_output=True,
        env=probe_env,
        check=False,
    )

    captured = completed.stdout + completed.stderr
    assert completed.returncode != 0
    assert expected_message in captured
    assert unexpected_message not in captured
    assert "BEGIN" not in captured
    assert "DO $bootstrap$" not in captured
    assert "COMMIT" not in captured
    for value in (migrator_value, runtime_value):
        if value:
            assert value not in captured


def test_compose_keeps_provider_operations_behind_explicit_profiles() -> None:
    compose = Path("infra/docker/docker-compose.apps.yml").read_text(encoding="utf-8")
    pyproject = Path("services/data-worker/pyproject.toml").read_text(encoding="utf-8")
    for service in ("role-bootstrap:", "provider-migrate:", "instrument-master-sync:"):
        assert service in compose
    assert 'profiles: ["instrument-master"]' in compose
    role_bootstrap = compose.split("  role-bootstrap:\n", maxsplit=1)[1].split(
        "  provider-migrate:\n", maxsplit=1
    )[0]
    assert "data-worker-migrate:" in role_bootstrap
    assert "condition: service_completed_successfully" in role_bootstrap
    provider_migrate = compose.split("  provider-migrate:\n", maxsplit=1)[1].split(
        "  instrument-master-sync:\n", maxsplit=1
    )[0]
    assert "role-bootstrap:" in provider_migrate
    assert "data-worker-migrate:" in provider_migrate
    assert (
        'instrument-master-provider-migrate = "data_worker.jobs.instruments.runtime:migrate_main"'
        in pyproject
    )


def test_compose_role_bootstrap_mounts_the_sql_regular_file() -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker CLI is required for compose config resolution")

    repository_root = Path(__file__).resolve().parents[5]
    compose_dir = repository_root / "infra" / "docker"
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "--profile",
            "instrument-master",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.apps.yml",
            "config",
            "--format",
            "json",
        ],
        cwd=compose_dir,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    resolved = json.loads(completed.stdout)
    mounts = resolved["services"]["role-bootstrap"]["volumes"]
    bootstrap_mount = next(
        mount for mount in mounts if mount["target"] == "/bootstrap/instrument-master-roles.sql"
    )
    expected_source = compose_dir / "migrations" / "instrument-master-roles.sql"
    assert bootstrap_mount["source"] == str(expected_source.resolve())
    assert expected_source.is_file()
    assert not expected_source.is_dir()
