"""Generator tests for the local strict-bool and deleted-condition extensions.

These target only the small, schema-opt-in capabilities added to
``gen-python.py`` for P3-N01: fields marked ``x-python-strict`` become
``StrictBool``, and the RawContent deleted/deletedAt conditional gets a
generated cross-field validator. No full repository generation is run here.
"""

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


def test_snake_case_conversion() -> None:
    assert gen_python._snake_case("authorized") == "authorized"
    assert gen_python._snake_case("deleted") == "deleted"
    assert gen_python._snake_case("usageRestriction") == "usage_restriction"


def test_collect_strict_bool_fields_maps_by_model() -> None:
    schema = {
        "title": "RawContent",
        "properties": {
            "deleted": {"type": "boolean", "x-python-strict": True},
            "title": {"type": "string"},
        },
        "definitions": {
            "LicenseMetadata": {
                "properties": {
                    "authorized": {"type": "boolean", "x-python-strict": True},
                }
            }
        },
    }
    assert gen_python._collect_strict_bool_fields(schema) == {
        "RawContent": {"deleted"},
        "LicenseMetadata": {"authorized"},
    }


def test_inject_strict_bool_rewrites_bool_and_import(tmp_path: Path) -> None:
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(
        json.dumps(
            {
                "title": "RawContent",
                "properties": {"deleted": {"type": "boolean", "x-python-strict": True}},
            }
        )
    )
    generated = tmp_path / "model.py"
    generated.write_text(
        "from pydantic import BaseModel\n\nclass RawContent(BaseModel):\n    deleted: bool\n"
    )
    gen_python.inject_strict_bool(schema_file, generated)
    content = generated.read_text()
    assert "deleted: StrictBool" in content
    assert "StrictBool" in content


def test_inject_strict_bool_skips_when_no_marked_fields(tmp_path: Path) -> None:
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps({"properties": {"title": {"type": "string"}}}))
    generated = tmp_path / "model.py"
    original = "from pydantic import BaseModel\n\nclass RawContent(BaseModel):\n    title: str\n"
    generated.write_text(original)
    gen_python.inject_strict_bool(schema_file, generated)
    assert generated.read_text() == original


def test_inject_deleted_condition_adds_validator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    schema_file = content_dir / "raw-content.json"
    schema_file.write_text("{}")
    monkeypatch.setattr(gen_python, "SCHEMAS_DIR", tmp_path)

    generated = tmp_path / "content_raw_content.py"
    generated.write_text(
        "from pydantic import BaseModel\n\n"
        "class RawContent(BaseModel):\n"
        "    deleted: bool\n"
        "    deleted_at: str | None = None\n"
    )
    gen_python.inject_deleted_condition(schema_file, generated)
    content = generated.read_text()
    assert "validate_deleted_condition" in content
    assert "deleted content must have deletedAt" in content


def test_inject_deleted_condition_skips_other_schemas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schema_file = tmp_path / "other.json"
    schema_file.write_text("{}")
    monkeypatch.setattr(gen_python, "SCHEMAS_DIR", tmp_path)

    generated = tmp_path / "other_model.py"
    original = "class Other(BaseModel):\n    pass\n"
    generated.write_text(original)
    gen_python.inject_deleted_condition(schema_file, generated)
    assert generated.read_text() == original


def test_inject_strict_bool_targets_marked_model_only(tmp_path: Path) -> None:
    # Two models share a same-named boolean field; only one is marked strict.
    # The generator must match by model path, not by the first field name hit.
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(
        json.dumps(
            {
                "definitions": {
                    "ModelB": {"properties": {"flag": {"type": "boolean"}}},
                    "ModelA": {
                        "properties": {"flag": {"type": "boolean", "x-python-strict": True}}
                    },
                }
            }
        )
    )
    generated = tmp_path / "model.py"
    generated.write_text(
        "from pydantic import BaseModel\n\n"
        "class ModelB(BaseModel):\n"
        "    flag: bool\n\n"
        "class ModelA(BaseModel):\n"
        "    flag: bool\n"
    )
    gen_python.inject_strict_bool(schema_file, generated)
    content = generated.read_text()
    assert "class ModelB(BaseModel):\n    flag: bool" in content  # unmarked stays bool
    assert "class ModelA(BaseModel):\n    flag: StrictBool" in content  # marked becomes StrictBool


def test_inject_strict_bool_targets_root_property_only(tmp_path: Path) -> None:
    # A same-named boolean exists at the root (marked) and inside a nested
    # definition (unmarked); only the root property is rewritten.
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(
        json.dumps(
            {
                "title": "Model",
                "properties": {"active": {"type": "boolean", "x-python-strict": True}},
                "definitions": {"Nested": {"properties": {"active": {"type": "boolean"}}}},
            }
        )
    )
    generated = tmp_path / "model.py"
    generated.write_text(
        "from pydantic import BaseModel\n\n"
        "class Nested(BaseModel):\n"
        "    active: bool\n\n"
        "class Model(BaseModel):\n"
        "    active: bool\n"
    )
    gen_python.inject_strict_bool(schema_file, generated)
    content = generated.read_text()
    assert "class Nested(BaseModel):\n    active: bool" in content
    assert "class Model(BaseModel):\n    active: StrictBool" in content
