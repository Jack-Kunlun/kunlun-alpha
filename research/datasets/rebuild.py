from __future__ import annotations

import argparse
import importlib
import json
import os
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

from feature_core import DatasetExporter, DatasetManifest, FeatureHistoryRepository

_MODULE_PATH = r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
_FACTORY = re.compile(rf"^{_MODULE_PATH}:[A-Za-z_][A-Za-z0-9_]*$")
_PROFILE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
_PROFILES_ENV = "KUNLUN_DATASET_REPOSITORY_PROFILES"


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate repository profile: {key}")
        result[key] = value
    return result


def _configured_profiles() -> dict[str, str]:
    raw = os.environ.get(_PROFILES_ENV)
    if raw is None:
        return {}
    try:
        parsed = cast(
            object,
            json.loads(raw, object_pairs_hook=_unique_object),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{_PROFILES_ENV} must be a JSON object") from exc
    if type(parsed) is not dict:
        raise ValueError(f"{_PROFILES_ENV} must be a JSON object")
    profiles: dict[str, str] = {}
    for name, factory_path in cast(dict[object, object], parsed).items():
        if (
            type(name) is not str
            or _PROFILE.fullmatch(name) is None
            or type(factory_path) is not str
            or _FACTORY.fullmatch(factory_path) is None
        ):
            raise ValueError(f"{_PROFILES_ENV} contains an invalid allowlist entry")
        profiles[name] = factory_path
    return profiles


def _repository(profile: str) -> FeatureHistoryRepository:
    if _PROFILE.fullmatch(profile) is None:
        raise ValueError("repository profile must be a non-executable identifier")
    factory_path = _configured_profiles().get(profile)
    if factory_path is None:
        raise ValueError("repository profile is not configured in the local allowlist")
    module_name, function_name = factory_path.split(":", maxsplit=1)
    factory = getattr(importlib.import_module(module_name), function_name, None)
    if not callable(factory):
        raise TypeError("repository factory is not callable")
    repository = cast(Callable[[], object], factory)()
    if type(repository) is not FeatureHistoryRepository:
        raise TypeError("repository factory must return FeatureHistoryRepository")
    return repository


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild and hash-check a Kunlun research dataset",
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repository-profile", required=True)
    args = parser.parse_args(argv)
    manifest = DatasetManifest.from_json(args.manifest.read_text(encoding="utf-8"))
    if (
        args.manifest.as_posix() != manifest.rebuild_command[7]
        or args.output.as_posix() != manifest.rebuild_command[9]
        or args.repository_profile != manifest.rebuild_command[11]
    ):
        raise ValueError("CLI arguments do not match the manifest rebuild command")
    rebuilt = DatasetExporter(_repository(args.repository_profile)).rebuild(
        manifest,
        args.output,
    )
    print(rebuilt.manifest_checksum)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
