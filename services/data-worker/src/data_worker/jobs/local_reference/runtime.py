"""One-shot composition root for the local terminal reference catalog."""

from __future__ import annotations

import os
from pathlib import Path

from .catalog import build_local_reference_plan, load_local_reference_catalog
from .writer import LocalReferenceMaterializationResult, PostgresLocalReferenceWriter

_DEFAULT_CATALOG_PATH = Path("/workspace/data/reference/local-terminal-instruments-v1.json")


def run_materialization(
    *,
    dsn: str,
    catalog_path: Path,
) -> LocalReferenceMaterializationResult:
    if not dsn.strip():
        raise RuntimeError("KUNLUN_POSTGRES_DSN is required")
    plan = build_local_reference_plan(load_local_reference_catalog(catalog_path))
    writer = PostgresLocalReferenceWriter(dsn)
    try:
        return writer.write(plan)
    finally:
        writer.close()


def main() -> None:
    result = run_materialization(
        dsn=os.environ.get("KUNLUN_POSTGRES_DSN", ""),
        catalog_path=Path(
            os.environ.get("LOCAL_TERMINAL_REFERENCE_FILE", str(_DEFAULT_CATALOG_PATH))
        ),
    )
    print(
        "Materialized local terminal reference revisions "
        f"inserted={result.inserted} existing={result.existing}"
    )


if __name__ == "__main__":
    main()
