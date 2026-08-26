"""Focused generator regressions for BenchmarkSeriesPoint schema metadata."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("gen_python", _SCRIPTS_DIR / "gen-python.py")
assert _spec is not None and _spec.loader is not None
gen_python = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen_python)


def test_collect_strict_string_fields_excludes_decimal_parser_fields() -> None:
    schema = {
        "title": "BenchmarkSeriesPoint",
        "x-python-strict-strings": True,
        "properties": {
            "benchmarkId": {"type": "string"},
            "referenceValue": {"type": "string", "x-python-decimal": True},
            "referenceOnly": {"type": "boolean"},
        },
        "$defs": {
            "OptionalLabel": {
                "x-python-strict-strings": True,
                "properties": {"label": {"type": ["string", "null"]}},
            }
        },
    }
    assert gen_python._collect_strict_string_fields(schema) == {
        "BenchmarkSeriesPoint": {"benchmark_id": False},
        "OptionalLabel": {"label": True},
    }


def test_inject_strict_strings_rejects_pydantic_coercion(tmp_path: Path) -> None:
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(
        json.dumps(
            {
                "title": "BenchmarkSeriesPoint",
                "x-python-strict-strings": True,
                "properties": {"benchmarkId": {"type": "string"}},
            }
        )
    )
    generated = tmp_path / "model.py"
    generated.write_text(
        "from pydantic import BaseModel\n\n"
        "class BenchmarkSeriesPoint(BaseModel):\n"
        "    benchmark_id: str\n"
    )
    gen_python.inject_strict_strings(schema_file, generated)
    content = generated.read_text()
    assert '@field_validator(\n        "benchmark_id",\n        mode="before",' in content
    assert "if type(value) is not str:" in content


def test_inject_strict_strings_preserves_nullable_string(tmp_path: Path) -> None:
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(
        json.dumps(
            {
                "title": "OptionalLabel",
                "x-python-strict-strings": True,
                "properties": {"label": {"type": ["string", "null"]}},
            }
        )
    )
    generated = tmp_path / "model.py"
    generated.write_text(
        "from pydantic import BaseModel\n\nclass OptionalLabel(BaseModel):\n    label: str | None\n"
    )
    gen_python.inject_strict_strings(schema_file, generated)
    content = generated.read_text()
    assert "def validate_nullable_strict_string_inputs" in content
    assert "if value is None:\n            return value" in content
    model_spec = importlib.util.spec_from_file_location("optional_label", generated)
    assert model_spec is not None and model_spec.loader is not None
    module = importlib.util.module_from_spec(model_spec)
    model_spec.loader.exec_module(module)
    assert module.OptionalLabel.model_validate({"label": None}).label is None
    with pytest.raises((TypeError, ValueError)):
        module.OptionalLabel.model_validate({"label": b"not-a-json-string"})


def test_public_export_only_module_is_allowed_as_handwritten_support(tmp_path: Path) -> None:
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(
        json.dumps(
            {
                "$defs": {
                    "Support": {
                        "x-python-public-exports": [
                            {
                                "module": "ashare_contracts.public_helpers",
                                "symbol": "public_helper",
                            }
                        ],
                        "x-python-semantic-validator": {
                            "module": "ashare_contracts.semantic_helpers",
                            "function": "validate_support",
                        },
                    }
                }
            }
        )
    )
    assert gen_python.load_python_support_file_names([schema_file]) == frozenset(
        {"public_helpers.py", "semantic_helpers.py"}
    )
