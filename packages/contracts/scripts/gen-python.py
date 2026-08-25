#!/usr/bin/env python3
"""
Generate Python Pydantic models from JSON Schema contracts.

Usage:
  python scripts/gen-python.py          # generate
  python scripts/gen-python.py --check  # verify generated == schema
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT / "schemas"
OUTPUT_DIR = (
    ROOT.parent.parent / "python" / "packages" / "ashare-contracts" / "src" / "ashare_contracts"
)

# Restricted JSON value types, used to type-narrow json.loads results without
# reaching for `Any` or suppressing the type checker.
type JsonScalar = str | int | float | bool | None
type JsonObject = dict[str, "JsonValue"]
type JsonValue = JsonScalar | list["JsonValue"] | JsonObject

_IDENTITY_SCHEMAS = {
    "funds/precious-metal-fund.json": "PreciousMetalFund",
    "market-data/bar.json": "Bar",
    "market-data/tick.json": "Tick",
    "market-data/adjustment-factor.json": "AdjustmentFactor",
    "market-data/corporate-action.json": "CorporateAction",
}


def ensure_pydantic_imports(content: str, symbols: tuple[str, ...]) -> str:
    """Add Pydantic symbols to the generated import without path dependencies."""
    match = re.search(r"^from pydantic import (?P<imports>[^\n]+)$", content, re.MULTILINE)
    if match is None:
        raise RuntimeError("Generated output changed; pydantic import was not found")
    imports = [item.strip() for item in match.group("imports").split(",")]
    for symbol in symbols:
        if symbol not in imports:
            imports.append(symbol)
    replacement = f"from pydantic import {', '.join(imports)}"
    return content[: match.start()] + replacement + content[match.end() :]


def load_code_prefix_rules() -> tuple[tuple[str, str, str, str], ...]:
    """Load and normalize the shared code-prefix table for generated models."""
    rules_path = ROOT / "instrument" / "code-prefix-rules.json"
    data = cast(JsonObject, json.loads(rules_path.read_text(encoding="utf-8")))
    rules = data.get("rules")
    if not isinstance(rules, list):
        raise RuntimeError(f"Invalid code-prefix rules in {rules_path}")
    normalized: list[tuple[str, str, str, str]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            raise RuntimeError(f"Invalid code-prefix rule in {rules_path}")
        prefix = rule.get("prefix")
        exchange = rule.get("exchange")
        board = rule.get("board")
        rule_type = rule.get("type")
        if (
            not isinstance(prefix, str)
            or not isinstance(exchange, str)
            or not isinstance(board, str)
            or not isinstance(rule_type, str)
        ):
            raise RuntimeError(f"Invalid code-prefix rule in {rules_path}")
        normalized.append((prefix, exchange, board, rule_type))
    return tuple(sorted(normalized, key=lambda item: len(item[0]), reverse=True))


def inject_instrument_identity_validator(schema_file: Path, generated_file: Path) -> None:
    """Add the cross-field Instrument identity check to the generated model.

    JSON Schema's regular expression validates the suffix shape, but the
    configured code generator does not carry an ``if``/``then`` relationship
    between ``unifiedCode``, ``code`` and ``exchange`` into Pydantic. Injecting
    this small validator from the generator keeps the runtime boundary
    reproducible without hand-editing generated artifacts or relying on an
    unstable TypeScript intersection type.
    """
    relative_schema = schema_file.relative_to(SCHEMAS_DIR).as_posix()
    if relative_schema != "instrument/instrument.json":
        return

    content = generated_file.read_text(encoding="utf-8")
    class_marker = "class Instrument(BaseModel):\n"
    if class_marker not in content:
        raise RuntimeError(
            "Instrument generator output changed; cannot inject the identity validator safely"
        )

    prefix_rules_literal = repr(load_code_prefix_rules())
    content = ensure_pydantic_imports(content, ("model_validator",))
    validator = (
        class_marker
        + '    @model_validator(mode="after")\n'
        + "    def validate_identity_consistency(self) -> Instrument:\n"
        + f"        prefix_rules = {prefix_rules_literal}\n"
        + "        expected_rule = next(\n"
        + "            (rule for rule in prefix_rules if self.code.startswith(rule[0])),\n"
        + "            None,\n"
        + "        )\n"
        + "        if expected_rule is None:\n"
        + '            raise ValueError("code is not recognized by code prefix rules")\n'
        + "        _, expected_exchange, expected_board, expected_type = expected_rule\n"
        + "        if expected_exchange != self.exchange.value:\n"
        + '            raise ValueError("exchange must match code prefix rules")\n'
        + "        if expected_board != self.board.value:\n"
        + '            raise ValueError("board must match code prefix rules")\n'
        + "        if expected_type != self.type.value:\n"
        + '            raise ValueError("type must match code prefix rules")\n'
        + '        if self.unified_code != f"{self.code}.{self.exchange.value}":\n'
        + '            raise ValueError("unifiedCode must match code and exchange")\n'
        + "        return self\n\n"
    )
    generated_file.write_text(
        content.replace(class_marker, validator, 1), encoding="utf-8", newline="\n"
    )


def inject_unified_code_identity_validator(schema_file: Path, generated_file: Path) -> None:
    """Inject shared prefix/suffix identity validation into fund/market models."""
    relative_schema = schema_file.relative_to(SCHEMAS_DIR).as_posix()
    class_name = _IDENTITY_SCHEMAS.get(relative_schema)
    if class_name is None:
        return

    content = generated_file.read_text(encoding="utf-8")
    class_marker = f"class {class_name}(BaseModel):\n"
    if class_marker not in content or "unified_code:" not in content or "exchange:" not in content:
        raise RuntimeError(
            f"Generated output changed; cannot inject identity validator for {class_name}"
        )

    content = ensure_pydantic_imports(content, ("model_validator",))
    prefix_rules_literal = repr(load_code_prefix_rules())
    validator = (
        class_marker
        + '    @model_validator(mode="after")\n'
        + f"    def validate_unified_identity(self) -> {class_name}:\n"
        + f"        prefix_rules = {prefix_rules_literal}\n"
        + '        exchange = getattr(self.exchange, "value", self.exchange)\n'
        + "        unified_code = self.unified_code\n"
        + '        if len(unified_code) != 9 or unified_code[6] != ".":\n'
        + '            raise ValueError("unifiedCode must use suffix form")\n'
        + "        code = unified_code[:6]\n"
        + "        suffix = unified_code[7:]\n"
        + "        if suffix != exchange:\n"
        + '            raise ValueError("unifiedCode/exchange identity mismatch")\n'
        + "        expected_rule = next(\n"
        + "            (rule for rule in prefix_rules if code.startswith(rule[0])),\n"
        + "            None,\n"
        + "        )\n"
        + "        if expected_rule is None:\n"
        + '            raise ValueError("code is not recognized by code prefix rules")\n'
        + "        if expected_rule[1] != exchange:\n"
        + '            raise ValueError("exchange must match code prefix rules")\n'
        + "        return self\n\n"
    )
    generated_file.write_text(
        content.replace(class_marker, validator, 1), encoding="utf-8", newline="\n"
    )


def inject_decimal_fields(schema_file: Path, generated_file: Path) -> None:
    """Use Decimal for price-sensitive fields in generated fund contracts.

    JSON Schema's ``number`` maps to ``float`` by default in
    datamodel-code-generator.  That is appropriate for transport types but
    unsafe at the Python domain boundary, so the small set of fund monetary
    fields is rewritten reproducibly here rather than by hand-editing output.
    """
    relative_schema = schema_file.relative_to(SCHEMAS_DIR).as_posix()
    replacements: dict[str, str]
    decimal_fields_by_class: dict[str, tuple[str, ...]]
    if relative_schema == "funds/fund-nav.json":
        decimal_fields_by_class = {"FundNav": ("nav", "inav")}
        replacements = {
            "nav: float = Field(..., ge=0.0)": 'nav: Decimal = Field(..., ge=Decimal("0"))',
            "inav: float | None = Field(..., ge=0.0)": (
                'inav: Decimal | None = Field(..., ge=Decimal("0"))'
            ),
        }
    elif relative_schema == "funds/precious-metal-fund.json":
        decimal_fields_by_class = {
            "RecurringFee": ("rate",),
            "PreciousMetalFund": ("management_fee_rate", "confidence"),
        }
        replacements = {
            'management_fee_rate: float = Field(..., alias="managementFeeRate", ge=0.0, le=1.0)': (
                "management_fee_rate: Decimal = Field(\n"
                '        ..., alias="managementFeeRate", ge=Decimal("0"), le=Decimal("1")\n'
                "    )"
            ),
            "confidence: float = Field(..., ge=0.0, le=1.0)": (
                'confidence: Decimal = Field(..., ge=Decimal("0"), le=Decimal("1"))'
            ),
            "rate: float = Field(..., ge=0.0, le=1.0)": (
                'rate: Decimal = Field(..., ge=Decimal("0"), le=Decimal("1"))'
            ),
        }
    elif relative_schema == "market-data/bar.json":
        decimal_fields_by_class = {"Bar": ("open", "high", "low", "close", "amount")}
        replacements = {
            f"{field}: float = Field(..., ge=0.0)": (
                f'{field}: Decimal = Field(..., ge=Decimal("0"))'
            )
            for field in ("open", "high", "low", "close", "amount")
        }
    elif relative_schema == "market-data/tick.json":
        decimal_fields_by_class = {"Tick": ("price", "amount")}
        replacements = {
            f"{field}: float = Field(..., ge=0.0)": (
                f'{field}: Decimal = Field(..., ge=Decimal("0"))'
            )
            for field in ("price", "amount")
        }
    elif relative_schema == "market-data/adjustment-factor.json":
        decimal_fields_by_class = {"AdjustmentFactor": ("factor",)}
        replacements = {
            "factor: float = Field(..., gt=0.0)": 'factor: Decimal = Field(..., gt=Decimal("0"))'
        }
    elif relative_schema == "emotion/limit-event.json":
        decimal_fields_by_class = {"LimitEvent": ("price",)}
        replacements = {
            "price: float = Field(..., ge=0.0)": ('price: Decimal = Field(..., ge=Decimal("0"))')
        }
    elif relative_schema == "market-data/corporate-action.json":
        decimal_fields_by_class = {
            "CorporateAction": ("per_share_cash", "per_share_stock", "ratio")
        }
        replacements = {
            'per_share_cash: float | None = Field(None, alias="perShareCash", ge=0.0)': (
                "per_share_cash: Decimal | None = Field("
                'None, alias="perShareCash", ge=Decimal("0"))'
            ),
            'per_share_stock: float | None = Field(None, alias="perShareStock", ge=0.0)': (
                "per_share_stock: Decimal | None = Field("
                'None, alias="perShareStock", ge=Decimal("0"))'
            ),
            "ratio: float | None = Field(None, ge=0.0)": (
                'ratio: Decimal | None = Field(None, ge=Decimal("0"))'
            ),
        }
    else:
        return

    content = generated_file.read_text(encoding="utf-8")
    if "from decimal import Decimal" not in content:
        content = content.replace(
            "from __future__ import annotations\n",
            "from __future__ import annotations\n\nfrom decimal import Decimal\n",
            1,
        )
    for old, new in replacements.items():
        if old not in content:
            raise RuntimeError(f"Generated output changed; cannot inject Decimal field: {old}")
        content = content.replace(old, new, 1)

    content = ensure_pydantic_imports(content, ("field_validator",))
    for class_name, fields in decimal_fields_by_class.items():
        class_marker = f"class {class_name}(BaseModel):\n"
        if class_marker not in content:
            raise RuntimeError(
                f"Generated output changed; cannot inject Decimal validator for {class_name}"
            )
        field_arguments = ", ".join(f'"{field}"' for field in fields)
        validator = (
            class_marker
            + f'    @field_validator({field_arguments}, mode="before")\n'
            + "    @classmethod\n"
            + "    def reject_binary_float(cls, value: object) -> object:\n"
            + "        if isinstance(value, float):\n"
            + '            raise TypeError("float is not an accepted decimal boundary value")\n'
            + "        return value\n\n"
        )
        content = content.replace(class_marker, validator, 1)
    generated_file.write_text(content, encoding="utf-8", newline="\n")


def _snake_case(name: str) -> str:
    """camelCase -> snake_case (matches datamodel-code-generator --snake-case-field)."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _collect_strict_bool_fields(schema: JsonObject) -> dict[str, set[str]]:
    """Map model class name -> strict boolean field names marked ``x-python-strict``.

    The mapping is keyed by the generated Pydantic class (the schema ``title``
    for the root object, or the definition name), so two models sharing a field
    name are never confused.
    """
    result: dict[str, set[str]] = {}

    def add_model(model_name: str, props: JsonObject) -> None:
        for name, prop in props.items():
            if (
                isinstance(prop, dict)
                and prop.get("x-python-strict") is True
                and prop.get("type") == "boolean"
            ):
                result.setdefault(model_name, set()).add(_snake_case(name))

    props = schema.get("properties")
    if isinstance(props, dict):
        title = schema.get("title")
        if isinstance(title, str):
            add_model(title, props)

    definitions = schema.get("definitions")
    if isinstance(definitions, dict):
        for def_name, def_schema in definitions.items():
            if isinstance(def_schema, dict):
                def_props = def_schema.get("properties")
                if isinstance(def_props, dict):
                    add_model(def_name, def_props)

    return result


def inject_strict_bool(schema_file: Path, generated_file: Path) -> None:
    """Use ``StrictBool`` for boolean fields marked ``x-python-strict``.

    JSON Schema ``type: boolean`` maps to a permissive Pydantic ``bool`` that
    coerces ``1``/``0``/``"true"``/``"false"``. For authorization and deletion
    flags that coercion is unsafe, so the schema opts those fields into strict
    booleans via a local extension, reproduced here without hand-editing output
    or making the whole repository strict. The replacement is scoped to the
    generated class that owns the field, so a same-named boolean in another
    model is never touched.
    """
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    strict_by_model = _collect_strict_bool_fields(schema)
    if not strict_by_model:
        return

    content = generated_file.read_text(encoding="utf-8")
    for model_name, fields in sorted(strict_by_model.items()):
        class_marker = f"class {model_name}(BaseModel):\n"
        start = content.find(class_marker)
        if start == -1:
            raise RuntimeError(
                f"Generated output changed; cannot find class {model_name} for StrictBool"
            )
        next_class = content.find("\nclass ", start + len(class_marker))
        end = next_class if next_class != -1 else len(content)
        block = content[start:end]
        for field_name in sorted(fields):
            old = f"    {field_name}: bool\n"
            new = f"    {field_name}: StrictBool\n"
            if old not in block:
                raise RuntimeError(
                    "Generated output changed; cannot inject StrictBool for "
                    f"{model_name}.{field_name}"
                )
            block = block.replace(old, new, 1)
        content = content[:start] + block + content[end:]
    content = ensure_pydantic_imports(content, ("StrictBool",))
    generated_file.write_text(content, encoding="utf-8", newline="\n")


def inject_strict_int(schema_file: Path, generated_file: Path) -> None:
    """Use StrictInt for integer fields marked x-python-strict."""
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    strict_by_model: dict[str, set[str]] = {}

    def add_model(model_name: str, props: JsonObject) -> None:
        for name, prop in props.items():
            if not isinstance(prop, dict) or prop.get("x-python-strict") is not True:
                continue
            prop_type = prop.get("type")
            if prop_type == "integer" or (isinstance(prop_type, list) and "integer" in prop_type):
                strict_by_model.setdefault(model_name, set()).add(_snake_case(name))

    props = schema.get("properties")
    title = schema.get("title")
    if isinstance(props, dict) and isinstance(title, str):
        add_model(title, props)
    definitions = schema.get("definitions")
    if isinstance(definitions, dict):
        for def_name, definition in definitions.items():
            if isinstance(definition, dict) and isinstance(definition.get("properties"), dict):
                add_model(def_name, definition["properties"])
    if not strict_by_model:
        return

    content = generated_file.read_text(encoding="utf-8")
    for model_name, fields in sorted(strict_by_model.items()):
        class_marker = f"class {model_name}(BaseModel):\n"
        start = content.find(class_marker)
        if start == -1:
            raise RuntimeError(
                f"Generated output changed; cannot find class {model_name} for StrictInt"
            )
        next_class = content.find("\nclass ", start + len(class_marker))
        end = next_class if next_class != -1 else len(content)
        block = content[start:end]
        for field_name in sorted(fields):
            pattern = re.compile(rf"(^    {re.escape(field_name)}: )int( \| None)?", re.MULTILINE)
            block, count = pattern.subn(r"\1StrictInt\2", block, count=1)
            if count != 1:
                raise RuntimeError(
                    "Generated output changed; cannot inject StrictInt for "
                    f"{model_name}.{field_name}"
                )
        content = content[:start] + block + content[end:]
    content = ensure_pydantic_imports(content, ("StrictInt",))
    generated_file.write_text(content, encoding="utf-8", newline="\n")


def inject_strict_rfc3339(schema_file: Path, generated_file: Path) -> None:
    """Reject coercive datetime input before Pydantic can truncate or normalize it."""
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    if schema.get("x-python-strict-rfc3339") is not True:
        return
    fields_by_model: dict[str, set[str]] = {}

    def add_model(model_name: str, props: JsonObject) -> None:
        for name, prop in props.items():
            if isinstance(prop, dict) and prop.get("format") == "date-time":
                fields_by_model.setdefault(model_name, set()).add(_snake_case(name))

    title = schema.get("title")
    properties = schema.get("properties")
    if isinstance(title, str) and isinstance(properties, dict):
        add_model(title, properties)
    definitions = schema.get("definitions")
    if isinstance(definitions, dict):
        for model_name, definition in definitions.items():
            if isinstance(definition, dict) and isinstance(definition.get("properties"), dict):
                add_model(model_name, definition["properties"])
    if not fields_by_model:
        raise RuntimeError(f"x-python-strict-rfc3339 has no date-time fields in {schema_file}")

    content = generated_file.read_text(encoding="utf-8")
    if "import re\n" not in content:
        content = content.replace(
            "from __future__ import annotations\n",
            "from __future__ import annotations\n\nimport re\n",
            1,
        )
    content = ensure_pydantic_imports(content, ("field_validator",))
    pattern = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})"
    for model_name, fields in sorted(fields_by_model.items()):
        class_marker = f"class {model_name}(BaseModel):\n"
        if class_marker not in content:
            raise RuntimeError(
                f"Generated output changed; cannot inject strict RFC3339 validator for {model_name}"
            )
        field_arguments = ", ".join(f'"{field}"' for field in sorted(fields))
        validator = (
            class_marker
            + f'    @field_validator({field_arguments}, mode="before")\n'
            + "    @classmethod\n"
            + "    def validate_strict_rfc3339(cls, value: object) -> object:\n"
            + "        if value is None:\n"
            + "            return value\n"
            + f"        if type(value) is not str or re.fullmatch({pattern!r}, value) is None:\n"
            + "            raise ValueError(\n"
            + '                "datetime must be a strict RFC3339 string with at most six "\n'
            + '                "fractional digits"\n'
            + "            )\n"
            + "        return value\n\n"
        )
        content = content.replace(class_marker, validator, 1)
    generated_file.write_text(content, encoding="utf-8", newline="\n")


def inject_deleted_condition(schema_file: Path, generated_file: Path) -> None:
    """Inject schema ``deleted`` conditionals into every applicable DTO.

    datamodel-code-generator does not translate draft-07 ``if``/``then``/``else``
    into a Pydantic cross-field validator. The schema remains the source of
    truth; this generic adapter keeps generated DTO validation aligned for any
    model that declares the deletion tuple, including KOL content, claims and
    position claims.
    """
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    properties = schema.get("properties")
    title = schema.get("title")
    if not isinstance(properties, dict) or not isinstance(title, str):
        return
    if not {"deleted", "deletedAt"}.issubset(properties):
        return
    has_reason = "deletionReason" in properties
    has_available = "availableTime" in properties

    content = generated_file.read_text(encoding="utf-8")
    class_marker = f"class {title}(BaseModel):\n"
    if class_marker not in content:
        raise RuntimeError(
            f"Generated output changed; cannot inject deletion validator for {title} safely"
        )
    content = ensure_pydantic_imports(content, ("model_validator", "ValidationError"))
    if "from pydantic_core import InitErrorDetails" not in content:
        content = content.replace(
            "from pydantic import ",
            "from pydantic_core import InitErrorDetails\nfrom pydantic import ",
            1,
        )
    error_class = title
    condition = "self.deleted_at is None"
    if has_reason:
        condition = "self.deleted_at is None or self.deletion_reason is None"
    invalid_deleted_message = "deleted record must have deletedAt and deletionReason"
    invalid_not_deleted = "non-deleted record must not have deletion metadata"
    lines = [
        class_marker,
        '    @model_validator(mode="after")\n',
        f"    def validate_deleted_condition(self) -> {title}:\n",
        f"        if self.deleted and ({condition}):\n",
        "            raise ValidationError.from_exception_data(\n",
        f'                "{error_class}",\n',
        "                [\n",
        "                    InitErrorDetails(\n",
        '                        type="value_error",\n',
        f'                        loc=("{"deletionReason" if has_reason else "deletedAt"}",),\n',
        "                        input=None,\n",
        "                        ctx={\n",
        f'                            "error": ValueError("{invalid_deleted_message}")\n',
        "                        },\n",
        "                    )\n",
        "                ],\n",
        "            )\n",
        "        if not self.deleted and (\n",
        "            self.deleted_at is not None\n",
    ]
    if has_reason:
        lines.append("            or self.deletion_reason is not None\n")
    lines.extend(
        [
            "        ):\n",
            "            raise ValidationError.from_exception_data(\n",
            f'                "{error_class}",\n',
            "                [\n",
            "                    InitErrorDetails(\n",
            '                        type="value_error",\n',
            '                        loc=("deletedAt",),\n',
            "                        input=self.deleted_at,\n",
            "                        ctx={\n",
            f'                            "error": ValueError("{invalid_not_deleted}")\n',
            "                        },\n",
            "                    )\n",
            "                ],\n",
            "            )\n",
        ]
    )
    if has_available:
        lines.extend(
            [
                "        if (\n",
                "            self.deleted\n",
                "            and self.deleted_at is not None\n",
                "            and self.deleted_at < self.available_time\n",
                "        ):\n",
                "            raise ValidationError.from_exception_data(\n",
                f'                "{error_class}",\n',
                "                [\n",
                "                    InitErrorDetails(\n",
                '                        type="value_error",\n',
                '                        loc=("deletedAt",),\n',
                "                        input=self.deleted_at,\n",
                "                        ctx={\n",
                '                            "error": ValueError(\n'
                '                                "deletedAt must be >= availableTime"\n'
                "                            )\n",
                "                        },\n",
                "                    )\n",
                "                ],\n",
                "            )\n",
            ]
        )
    lines.extend(["        return self\n\n"])
    validator = "".join(lines)
    generated_file.write_text(
        content.replace(class_marker, validator, 1), encoding="utf-8", newline="\n"
    )


def inject_available_time_validator(schema_file: Path, generated_file: Path) -> None:
    """Inject a schema-declared maximum-time invariant into the generated DTO.

    The extension is intentionally generic: any schema can declare a target
    field and dotted paths whose maximum must equal that field. This keeps
    cross-field time semantics in the schema rather than coupling the
    generator to a particular KOL filename.
    """
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    metadata = schema.get("x-python-available-time")
    if not isinstance(metadata, dict):
        return
    title = schema.get("title")
    field = metadata.get("field")
    maximum_of = metadata.get("maximumOf")
    if (
        not isinstance(title, str)
        or not isinstance(field, str)
        or not isinstance(maximum_of, list)
        or not maximum_of
        or not all(isinstance(item, str) for item in maximum_of)
    ):
        raise RuntimeError(f"invalid x-python-available-time metadata in {schema_file}")

    content = generated_file.read_text(encoding="utf-8")
    class_marker = f"class {title}(BaseModel):\n"
    if class_marker not in content:
        raise RuntimeError(
            f"Generated output changed; cannot inject available-time validator for {title} safely"
        )
    method_marker = "def validate_available_time_invariant(self)"
    if method_marker in content:
        return

    def attribute_path(path: str) -> str:
        parts = path.split(".")
        if any(not part for part in parts):
            raise RuntimeError(f"invalid available-time path {path!r} in {schema_file}")
        return "self." + ".".join(_snake_case(part) for part in parts)

    target = f"self.{_snake_case(field)}"
    expected = "max(" + ", ".join(attribute_path(item) for item in maximum_of) + ")"
    content = ensure_pydantic_imports(content, ("model_validator",))
    validator = (
        class_marker
        + '    @model_validator(mode="after")\n'
        + f"    def validate_available_time_invariant(self) -> {title}:\n"
        + f"        expected_available_time = {expected}\n"
        + f"        if {target} != expected_available_time:\n"
        + "            raise ValueError(\n"
        + '                "availableTime must equal the declared maximum input time"\n'
        + "            )\n"
        + "        return self\n\n"
    )
    generated_file.write_text(
        content.replace(class_marker, validator, 1), encoding="utf-8", newline="\n"
    )


def inject_schema_validation(schema_file: Path, generated_file: Path) -> None:
    """Inject generic schema-declared equality/forbidden-value validators."""
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    rules = schema.get("x-python-validation")
    title = schema.get("title")
    if not isinstance(rules, list) or not isinstance(title, str) or not rules:
        return
    parsed: list[tuple[str, str, object, str, str, object, str]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            raise RuntimeError(f"invalid x-python-validation rule in {schema_file}")
        when = rule.get("when")
        forbid = rule.get("forbid")
        message = rule.get("message", "schema validation failed")
        if (
            not isinstance(when, dict)
            or not isinstance(forbid, dict)
            or not isinstance(when.get("field"), str)
            or not isinstance(forbid.get("field"), str)
            or "equals" not in when
            or "equals" not in forbid
            or not isinstance(message, str)
        ):
            raise RuntimeError(f"invalid x-python-validation rule in {schema_file}")
        parsed.append(
            (
                _snake_case(when["field"]),
                _snake_case(forbid["field"]),
                when["equals"],
                message,
                title,
                forbid["equals"],
                schema_file.name,
            )
        )
    content = generated_file.read_text(encoding="utf-8")
    class_marker = f"class {title}(BaseModel):\n"
    if class_marker not in content:
        raise RuntimeError(f"Generated output changed; cannot inject schema validation for {title}")
    method_marker = "def validate_schema_declared_rules(self)"
    if method_marker in content:
        return
    lines = [
        class_marker,
        '    @model_validator(mode="after")\n',
        f"    def validate_schema_declared_rules(self) -> {title}:\n",
    ]
    for when_field, forbid_field, when_value, message, _, forbid_value, _ in parsed:
        lines.extend(
            [
                "        if (\n",
                f'            getattr(self.{when_field}, "value", self.{when_field}) == '
                f"{when_value!r}\n",
                f'            and getattr(self.{forbid_field}, "value", self.{forbid_field}) == '
                f"{forbid_value!r}\n",
                "        ):\n",
                f"            raise ValueError({message!r})\n",
            ]
        )
    lines.append("        return self\n\n")
    content = ensure_pydantic_imports(content, ("model_validator",))
    generated_file.write_text(
        content.replace(class_marker, "".join(lines), 1), encoding="utf-8", newline="\n"
    )


def run_datamodel_codegen(schema_file: Path, output_file: Path) -> None:
    """Run datamodel-code-generator on a single schema file.

    Writes to a temp file first, then copies only when the content actually
    changed. This keeps the generator idempotent and avoids touching files
    that are already up to date (important on Windows where a generated file
    may be temporarily locked by an editor or indexer).
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="gen-python-"))
    tmp_file = tmp_dir / f"{output_file.stem}.py"
    cmd = [
        sys.executable,
        "-m",
        "datamodel_code_generator",
        "--input",
        str(schema_file),
        "--input-file-type",
        "jsonschema",
        "--output",
        str(tmp_file),
        "--output-model-type",
        "pydantic_v2.BaseModel",
        "--target-python-version",
        "3.12",
        "--snake-case-field",
        "--use-field-description",
        "--field-constraints",
        "--collapse-root-models",
        "--disable-timestamp",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        print(f"Error generating {schema_file}:", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)

    format_result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--quiet", str(tmp_file)],
        capture_output=True,
        text=True,
    )
    if format_result.returncode != 0:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        print(f"Error formatting generated model {output_file}:", file=sys.stderr)
        print(format_result.stderr, file=sys.stderr)
        sys.exit(1)

    inject_instrument_identity_validator(schema_file, tmp_file)
    inject_unified_code_identity_validator(schema_file, tmp_file)
    inject_decimal_fields(schema_file, tmp_file)
    inject_strict_bool(schema_file, tmp_file)
    inject_strict_int(schema_file, tmp_file)
    inject_strict_rfc3339(schema_file, tmp_file)
    inject_deleted_condition(schema_file, tmp_file)
    inject_available_time_validator(schema_file, tmp_file)
    inject_schema_validation(schema_file, tmp_file)
    format_result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--quiet", str(tmp_file)],
        capture_output=True,
        text=True,
    )
    if format_result.returncode != 0:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        print(f"Error formatting generated model {output_file}:", file=sys.stderr)
        print(format_result.stderr, file=sys.stderr)
        sys.exit(1)

    import_result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "I", "--fix", str(tmp_file)],
        capture_output=True,
        text=True,
    )
    if import_result.returncode != 0:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        print(f"Error sorting generated imports for {output_file}:", file=sys.stderr)
        print(import_result.stderr, file=sys.stderr)
        sys.exit(1)

    normalized = tmp_file.read_text(encoding="utf-8").replace("\r\n", "\n")
    if not (output_file.exists() and output_file.read_text(encoding="utf-8") == normalized):
        output_file.write_text(normalized, encoding="utf-8", newline="\n")
    # Ignore cleanup errors: on Windows the sandbox may intercept deletes
    # (safe-delete recycle bin unavailable), which must not fail generation.
    shutil.rmtree(tmp_dir, ignore_errors=True)


def generate(output_dir: Path = OUTPUT_DIR) -> None:
    """Generate Python types from all JSON Schema files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    header = "# Generated from packages/contracts/schemas/. DO NOT EDIT BY HAND.\n\n"

    # Recursively collect *.json so subdirectories (schemas/instrument/) are supported.
    # The output module name is flattened from the relative path: instrument/exchange.json
    # -> instrument_exchange.py; top-level files keep their stem.
    schema_files = sorted(SCHEMAS_DIR.rglob("*.json"))
    if not schema_files:
        print("No schema files found in", SCHEMAS_DIR, file=sys.stderr)
        sys.exit(1)

    generated_files: list[Path] = []
    for schema_file in schema_files:
        rel = schema_file.relative_to(SCHEMAS_DIR)
        parts = list(rel.parts[:-1]) + [rel.stem]
        module_name = "_".join(parts).replace("-", "_")
        output_file = output_dir / f"{module_name}.py"
        run_datamodel_codegen(schema_file, output_file)
        generated_files.append(output_file)
        print(f"  {output_file}")

    # Write __init__.py that re-exports all generated models
    init_path = output_dir / "__init__.py"
    module_imports: dict[str, set[str]] = {}
    for sf in schema_files:
        rel = sf.relative_to(SCHEMAS_DIR)
        parts = list(rel.parts[:-1]) + [rel.stem]
        module_name = "_".join(parts).replace("-", "_")
        gen_file = output_dir / f"{module_name}.py"
        if gen_file.exists():
            content = gen_file.read_text(encoding="utf-8")
            import re

            classes = re.findall(r"^class (\w+)", content, re.MULTILINE)
            if classes:
                module_imports[module_name] = set(classes)

    # Build the flattened re-export list. Different modules may define classes
    # with the same name (e.g. several schemas inline an `Exchange` enum); the
    # second and later occurrences get a stable numeric suffix (`Exchange_1`).
    exports: list[tuple[str, str, str]] = []
    seen: dict[str, int] = {}
    for module_name in sorted(module_imports):
        for cls in sorted(module_imports[module_name]):
            if cls in seen:
                seen[cls] += 1
                export_name = f"{cls}_{seen[cls]}"
            else:
                seen[cls] = 0
                export_name = cls
            exports.append((module_name, cls, export_name))

    import_lines: list[str] = []
    for module_name, cls, export_name in exports:
        import_line = f"from ashare_contracts.{module_name} import {cls} as {export_name}"
        if len(import_line) > 100:
            import_line = (
                f"from ashare_contracts.{module_name} import (\n    {cls} as {export_name},\n)"
            )
        import_lines.append(import_line)

    all_content = header + "\n".join(import_lines) + "\n"
    if import_lines:
        all_content += "\n__all__ = [\n"
        for _, _, export_name in exports:
            all_content += f'    "{export_name}",\n'
        all_content += "]\n"
    init_path.write_text(all_content, encoding="utf-8", newline="\n")
    (output_dir / "py.typed").write_text("", encoding="utf-8", newline="\n")

    print(f"Generated Python types -> {output_dir}")


def check() -> None:
    """Verify generated files match schemas (regenerate and diff).

    Compares only the generated artifacts (schema modules, __init__.py and
    py.typed), so hand-written subpackages such as providers/ can live
    alongside them without tripping the sync check.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_output = Path(tmpdir) / "ashare_contracts"
        generate(tmp_output)

        if not OUTPUT_DIR.exists():
            print("ERROR: Generated Python output directory does not exist:", OUTPUT_DIR)
            sys.exit(1)

        mismatches: list[str] = []
        for tmp_file in sorted(tmp_output.rglob("*.py")):
            rel = tmp_file.relative_to(tmp_output)
            real_file = OUTPUT_DIR / rel
            if not real_file.exists():
                mismatches.append(f"missing: {rel}")
            elif real_file.read_text(encoding="utf-8") != tmp_file.read_text(encoding="utf-8"):
                mismatches.append(f"differing: {rel}")
        if not (OUTPUT_DIR / "py.typed").exists():
            mismatches.append("missing: py.typed")

        generated_names = {f.name for f in tmp_output.glob("*.py")}
        for real_file in sorted(OUTPUT_DIR.glob("*.py")):
            if real_file.name not in generated_names and real_file.name != "__init__.py":
                mismatches.append(f"stale: {real_file.name}")

        if mismatches:
            print("ERROR: Generated Python types are out of sync with JSON Schema.")
            print("Run `pnpm gen:python` from packages/contracts/ to regenerate.")
            for message in mismatches:
                print("  " + message)
            sys.exit(1)

        print("Python types are in sync with JSON Schema.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Python types from JSON Schema")
    parser.add_argument(
        "--check", action="store_true", help="Verify generated files are up-to-date"
    )
    args = parser.parse_args()

    if args.check:
        check()
    else:
        generate()


if __name__ == "__main__":
    main()
