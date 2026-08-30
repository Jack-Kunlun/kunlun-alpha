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
SEMANTIC_SUPPORT_SOURCE = ROOT / "scripts" / "backtest_regression_semantics.py"
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


def _iter_model_schemas(schema: JsonObject) -> tuple[tuple[str | None, JsonObject], ...]:
    """Walk root, legacy definitions and draft-07 $defs model schemas once."""
    title = schema.get("title")
    models: list[tuple[str | None, JsonObject]] = [
        (title if isinstance(title, str) else None, schema)
    ]
    for container_name in ("definitions", "$defs"):
        definitions = schema.get(container_name)
        if not isinstance(definitions, dict):
            continue
        for fallback_name, definition in definitions.items():
            if not isinstance(definition, dict):
                continue
            definition_title = definition.get("title")
            model_name = definition_title if isinstance(definition_title, str) else fallback_name
            models.append((model_name, definition))
    return tuple(models)


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


def inject_semantic_validators(schema_file: Path, generated_file: Path) -> None:
    """Inject validators declared by schema extensions, without model-name rules."""
    schema = cast(JsonObject, json.loads(schema_file.read_text(encoding="utf-8")))
    candidates: list[tuple[str, str, str]] = []
    for model_name, model_schema in _iter_model_schemas(schema):
        extension = model_schema.get("x-python-semantic-validator")
        if not isinstance(extension, dict) or model_name is None:
            continue
        module = extension.get("module")
        function = extension.get("function")
        if not isinstance(module, str) or not isinstance(function, str):
            raise RuntimeError(f"invalid x-python-semantic-validator metadata in {schema_file}")
        candidates.append((model_name, module, function))
    if not candidates:
        return

    content = generated_file.read_text(encoding="utf-8")
    content = ensure_pydantic_imports(content, ("model_validator",))
    for model_name, module, function in candidates:
        import_line = f"from {module} import {function}\n"
        if import_line not in content:
            future_import = "from __future__ import annotations\n"
            if future_import in content:
                content = content.replace(future_import, future_import + import_line, 1)
            else:
                content = import_line + content
        class_marker = f"class {model_name}("
        class_index = content.find(class_marker)
        if class_index < 0:
            raise RuntimeError(
                f"semantic validator target {model_name} was not generated from {schema_file}"
            )
        validator_name = f"_validate_{function}"
        if validator_name in content[class_index:]:
            continue
        class_end = content.find("):\n", class_index)
        if class_end < 0:
            raise RuntimeError(f"invalid generated class {model_name}")
        validator = (
            f'    @model_validator(mode="after")\n'
            f"    def {validator_name}(self):\n"
            f'        {function}(self.model_dump(by_alias=True, mode="json"))\n'
            f"        return self\n\n"
        )
        content = content[: class_end + 3] + validator + content[class_end + 3 :]
    generated_file.write_text(content, encoding="utf-8", newline="\n")


def load_public_exports(schema_files: list[Path]) -> tuple[tuple[str, str], ...]:
    """Load schema-declared hand-written symbols for the generated public API."""
    public_exports: set[tuple[str, str]] = set()
    for schema_file in schema_files:
        schema = cast(JsonObject, json.loads(schema_file.read_text(encoding="utf-8")))
        for _, model_schema in _iter_model_schemas(schema):
            raw_exports = model_schema.get("x-python-public-exports")
            if raw_exports is None:
                continue
            if not isinstance(raw_exports, list):
                raise RuntimeError(f"invalid x-python-public-exports metadata in {schema_file}")
            for raw_export in raw_exports:
                if not isinstance(raw_export, dict):
                    raise RuntimeError(f"invalid x-python-public-exports entry in {schema_file}")
                module = raw_export.get("module")
                symbol = raw_export.get("symbol")
                if not isinstance(module, str) or not isinstance(symbol, str):
                    raise RuntimeError(f"invalid x-python-public-exports entry in {schema_file}")
                public_exports.add((module, symbol))
    return tuple(sorted(public_exports))


def load_python_support_file_names(schema_files: list[Path]) -> frozenset[str]:
    """Return hand-written ashare-contract modules allowed beside generated DTOs."""
    modules = {module for module, _ in load_public_exports(schema_files)}
    for schema_file in schema_files:
        schema = cast(JsonObject, json.loads(schema_file.read_text(encoding="utf-8")))
        for _, model_schema in _iter_model_schemas(schema):
            extension = model_schema.get("x-python-semantic-validator")
            if not isinstance(extension, dict):
                continue
            module = extension.get("module")
            if isinstance(module, str):
                modules.add(module)
    return frozenset(
        module.rsplit(".", maxsplit=1)[-1] + ".py"
        for module in modules
        if module.startswith("ashare_contracts.")
    )


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
    market_index_clause = ""
    if relative_schema == "market-data/bar.json":
        market_index_clause = (
            '        is_exchange_index = (exchange == "SH" and code.startswith("000")) or (\n'
            '            exchange == "SZ" and code.startswith("399")\n'
            "        )\n"
            "        if is_exchange_index:\n"
            "            return self\n"
        )
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
        + market_index_clause
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


def _collect_decimal_metadata(schema: JsonObject) -> dict[str, dict[str, tuple[str, int | None]]]:
    """Collect schema-declared strict decimal fields by generated model."""
    result: dict[str, dict[str, tuple[str, int | None]]] = {}

    def add_model(model_name: str, props: JsonObject) -> None:
        for name, prop in props.items():
            if not isinstance(prop, dict) or prop.get("x-python-decimal") is not True:
                continue
            pattern = prop.get("pattern")
            max_length = prop.get("maxLength")
            if not isinstance(pattern, str) or (
                max_length is not None and not isinstance(max_length, int)
            ):
                raise RuntimeError(
                    "x-python-decimal requires a string pattern and integer maxLength"
                )
            result.setdefault(model_name, {})[_snake_case(name)] = (pattern, max_length)

    title = schema.get("title")
    props = schema.get("properties")
    if isinstance(title, str) and isinstance(props, dict):
        add_model(title, props)
    definitions = schema.get("definitions")
    if isinstance(definitions, dict):
        for model_name, definition in definitions.items():
            definition_props = (
                definition.get("properties") if isinstance(definition, dict) else None
            )
            if isinstance(definition_props, dict):
                add_model(model_name, definition_props)
    return result


def inject_decimal_metadata(schema_file: Path, generated_file: Path) -> None:
    """Parse schema-declared canonical decimal strings into Python ``Decimal``."""
    schema = cast(JsonObject, json.loads(schema_file.read_text(encoding="utf-8")))
    decimal_by_model = _collect_decimal_metadata(schema)
    if not decimal_by_model:
        return

    content = generated_file.read_text(encoding="utf-8")
    if "import re\n" not in content:
        content = content.replace(
            "from __future__ import annotations\n",
            "from __future__ import annotations\n\nimport re\n",
            1,
        )
    if "from decimal import Decimal\n" not in content:
        content = content.replace(
            "from __future__ import annotations\n",
            "from __future__ import annotations\n\nfrom decimal import Decimal\n",
            1,
        )
    content = ensure_pydantic_imports(content, ("field_validator",))

    for model_name, fields in sorted(decimal_by_model.items()):
        class_marker = f"class {model_name}(BaseModel):\n"
        class_index = content.find(class_marker)
        if class_index < 0:
            raise RuntimeError(f"decimal metadata target {model_name} was not generated")
        next_class = content.find("\nclass ", class_index + len(class_marker))
        class_end = next_class if next_class != -1 else len(content)
        block = content[class_index:class_end]
        validators: list[str] = []
        for field_name, (pattern, max_length) in sorted(fields.items()):
            field_pattern = re.compile(
                rf"^(    {re.escape(field_name)}: )(?P<annotation>[^=\n]+)"
                rf" = Field\((?P<arguments>.*?)(?:\n    \)|\)$)",
                re.MULTILINE | re.DOTALL,
            )
            match = field_pattern.search(block)
            if match is None:
                raise RuntimeError(
                    f"decimal metadata field {model_name}.{field_name} was not generated"
                )
            arguments = re.sub(
                r",\s*(?:min_length|max_length|pattern)=(?:"
                r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|[0-9]+)",
                "",
                match.group("arguments"),
            )
            replacement = f"{match.group(1)}Decimal = Field({arguments})"
            block = block[: match.start()] + replacement + block[match.end() :]
            max_length_check = (
                f"        if len(value) > {max_length}:\n"
                f'            raise ValueError("decimal string exceeds maxLength {max_length}")\n'
                if max_length is not None
                else ""
            )
            validators.append(
                f'    @field_validator("{field_name}", mode="before")\n'
                "    @classmethod\n"
                f"    def parse_{field_name}(cls, value: object) -> object:\n"
                f"        if type(value) is not str or re.fullmatch({pattern!r}, value) is None:\n"
                f"            raise ValueError(\n"
                f'                "{_snake_case(field_name)} must be a canonical positive "\n'
                '                "fixed-point decimal string"\n'
                "            )\n"
                f"{max_length_check}"
                "        return Decimal(value)\n\n"
            )
        block = block.replace(class_marker, class_marker + "".join(validators), 1)
        content = content[:class_index] + block + content[class_end:]

    generated_file.write_text(content, encoding="utf-8", newline="\n")


def _snake_case(name: str) -> str:
    """camelCase -> snake_case (matches datamodel-code-generator --snake-case-field)."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _collect_strict_string_fields(schema: JsonObject) -> dict[str, dict[str, bool]]:
    """Map strict JSON string fields to whether their schema also permits null."""
    result: dict[str, dict[str, bool]] = {}

    def add_model(model_name: str, model_schema: JsonObject) -> None:
        properties = model_schema.get("properties")
        if not isinstance(properties, dict):
            return
        strict_all = model_schema.get("x-python-strict-strings") is True
        for name, prop in properties.items():
            if not isinstance(prop, dict):
                continue
            prop_type = prop.get("type")
            is_string = prop_type == "string" or (
                isinstance(prop_type, list) and "string" in prop_type
            )
            if (
                is_string
                and (strict_all or prop.get("x-python-strict") is True)
                and prop.get("x-python-decimal") is not True
            ):
                nullable = isinstance(prop_type, list) and "null" in prop_type
                result.setdefault(model_name, {})[_snake_case(name)] = nullable

    for model_name, model_schema in _iter_model_schemas(schema):
        if model_name is not None:
            add_model(model_name, model_schema)
    return result


def inject_strict_strings(schema_file: Path, generated_file: Path) -> None:
    """Reject Pydantic coercion for schema-declared JSON string boundaries."""
    schema = cast(JsonObject, json.loads(schema_file.read_text(encoding="utf-8")))
    strict_by_model = _collect_strict_string_fields(schema)
    if not strict_by_model:
        return

    content = generated_file.read_text(encoding="utf-8")
    content = ensure_pydantic_imports(content, ("field_validator",))
    for model_name, fields in sorted(strict_by_model.items()):
        class_marker = f"class {model_name}(BaseModel):\n"
        if class_marker not in content:
            raise RuntimeError(
                f"strict-string metadata target {model_name} was not generated from {schema_file}"
            )
        validator_parts = [class_marker]
        for nullable in (False, True):
            selected = sorted(
                field for field, allows_null in fields.items() if allows_null is nullable
            )
            if not selected:
                continue
            field_arguments = "".join(f'        "{field}",\n' for field in selected)
            method_name = (
                "validate_nullable_strict_string_inputs"
                if nullable
                else "validate_strict_string_inputs"
            )
            nullable_guard = (
                "        if value is None:\n            return value\n" if nullable else ""
            )
            validator_parts.extend(
                [
                    "    @field_validator(\n",
                    field_arguments,
                    '        mode="before",\n',
                    "    )\n",
                    "    @classmethod\n",
                    f"    def {method_name}(cls, value: object) -> object:\n",
                    nullable_guard,
                    "        if type(value) is not str:\n",
                    '            raise TypeError("value must be a JSON string")\n',
                    "        return value\n\n",
                ]
            )
        validator = "".join(validator_parts)
        content = content.replace(class_marker, validator, 1)
    generated_file.write_text(content, encoding="utf-8", newline="\n")


def _collect_strict_bool_fields(schema: JsonObject) -> dict[str, set[str]]:
    """Map model class name -> strict boolean field names marked ``x-python-strict``.

    The mapping is keyed by the generated Pydantic class (the schema ``title``
    for the root object, or the definition name), so two models sharing a field
    name are never confused.
    """
    result: dict[str, set[str]] = {}

    def add_model(model_name: str, props: JsonObject) -> None:
        for name, prop in props.items():
            if not isinstance(prop, dict) or prop.get("x-python-strict") is not True:
                continue
            prop_type = prop.get("type")
            if prop_type == "boolean" or (isinstance(prop_type, list) and "boolean" in prop_type):
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


def _collect_strict_literal_true_fields(schema: JsonObject) -> dict[str, set[str]]:
    """Map model class names to strict booleans whose schema value is ``true``."""
    result: dict[str, set[str]] = {}

    def add_model(model_name: str, props: JsonObject) -> None:
        for name, prop in props.items():
            if (
                isinstance(prop, dict)
                and prop.get("x-python-strict") is True
                and prop.get("type") == "boolean"
                and prop.get("const") is True
            ):
                result.setdefault(model_name, set()).add(_snake_case(name))

    props = schema.get("properties")
    title = schema.get("title")
    if isinstance(title, str) and isinstance(props, dict):
        add_model(title, props)
    definitions = schema.get("definitions")
    if isinstance(definitions, dict):
        for model_name, definition in definitions.items():
            definition_props = (
                definition.get("properties") if isinstance(definition, dict) else None
            )
            if isinstance(definition_props, dict):
                add_model(model_name, definition_props)
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
    schema = cast(JsonObject, json.loads(schema_file.read_text(encoding="utf-8")))
    strict_by_model = _collect_strict_bool_fields(schema)
    literal_true_by_model = _collect_strict_literal_true_fields(schema)
    if not strict_by_model:
        return

    content = generated_file.read_text(encoding="utf-8")
    replaced_strict_bool = False
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
            pattern = re.compile(
                rf"(^    {re.escape(field_name)}: )bool( \| None)?",
                re.MULTILINE,
            )
            block, count = pattern.subn(r"\1StrictBool\2", block, count=1)
            if count == 1:
                replaced_strict_bool = True
            elif field_name in literal_true_by_model.get(model_name, set()) and re.search(
                rf"^    {re.escape(field_name)}: Literal\[True\]",
                block,
                re.MULTILINE,
            ):
                continue
            else:
                raise RuntimeError(
                    "Generated output changed; cannot inject StrictBool for "
                    f"{model_name}.{field_name}"
                )
        content = content[:start] + block + content[end:]
    if replaced_strict_bool:
        content = ensure_pydantic_imports(content, ("StrictBool",))
    for model_name, fields in sorted(literal_true_by_model.items()):
        class_marker = f"class {model_name}(BaseModel):\n"
        if class_marker not in content:
            raise RuntimeError(f"Generated output changed; cannot find class {model_name}")
        if f"def validate_strict_literal_true_{_snake_case(model_name)}" in content:
            continue
        field_arguments = ", ".join(f'"{field}"' for field in sorted(fields))
        validator = (
            class_marker
            + f'    @field_validator({field_arguments}, mode="before")\n'
            + "    @classmethod\n"
            + f"    def validate_strict_literal_true_{_snake_case(model_name)}(\n"
            + "        cls, value: object\n"
            + "    ) -> object:\n"
            + "        if type(value) is not bool:\n"
            + '            raise TypeError("value must be a JSON boolean")\n'
            + "        return value\n\n"
        )
        content = content.replace(class_marker, validator, 1)
    if literal_true_by_model:
        content = ensure_pydantic_imports(content, ("field_validator",))
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
    """Reject non-RFC3339 datetime input before Pydantic can normalize it."""
    schema = cast(JsonObject, json.loads(schema_file.read_text(encoding="utf-8")))
    if schema.get("x-python-strict-rfc3339") is not True:
        return
    strict_calendar = schema.get("x-python-strict-rfc3339-calendar") is True
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
    if strict_calendar and "from datetime import datetime\n" not in content:
        content = content.replace(
            "from __future__ import annotations\n",
            "from __future__ import annotations\n\nfrom datetime import datetime\n",
            1,
        )
    content = ensure_pydantic_imports(content, ("field_validator",))
    if strict_calendar:
        pattern = (
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:"
            r"[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?"
            r"(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
        )
        calendar_validation = (
            "        try:\n"
            '            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))\n'
            "        except ValueError as exc:\n"
            "            raise ValueError(\n"
            '                "datetime must be a valid calendar timestamp"\n'
            "            ) from exc\n"
            "        if parsed.tzinfo is None or parsed.utcoffset() is None:\n"
            '            raise ValueError("datetime must include a valid timezone offset")\n'
        )
    else:
        pattern = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})"
        calendar_validation = ""
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
            + calendar_validation
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
    invalid_deleted_message = (
        "deleted record must have deletedAt and deletionReason"
        if has_reason
        else "deleted record must have deletedAt"
    )
    invalid_not_deleted = (
        "non-deleted record must not have deletedAt or deletionReason"
        if has_reason
        else "non-deleted record must not have deletedAt"
    )
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


def inject_strategy_contract_validators(schema_file: Path, generated_file: Path) -> None:
    """Keep generated strategy DTOs immutable and enforce cross-field semantics."""
    relative_schema = schema_file.relative_to(SCHEMAS_DIR).as_posix()
    if relative_schema not in {
        "strategy/signal.json",
        "strategy/strategy-descriptor.json",
    }:
        return

    content = generated_file.read_text(encoding="utf-8")
    content = content.replace(
        '        extra="forbid",\n',
        '        extra="forbid",\n        frozen=True,\n',
    )
    content = ensure_pydantic_imports(content, ("ConfigDict", "model_validator"))
    content = re.sub(
        r"(class [A-Za-z_][A-Za-z0-9_]*\(RootModel\[[^\n]+\]\):\n)",
        r"\1    model_config = ConfigDict(frozen=True)\n\n",
        content,
    )

    if relative_schema == "strategy/signal.json":
        class_marker = "class Signal(BaseModel):\n"
        if class_marker not in content:
            raise RuntimeError("Generated Signal output changed; validator injection aborted")
        content, replaced = re.subn(
            r"    evidence_ids: list\[([^\n]+)\]",
            r"    evidence_ids: tuple[\1, ...]",
            content,
            count=1,
        )
        if replaced != 1:
            raise RuntimeError("Generated Signal evidenceIds annotation changed")
        validator = (
            class_marker
            + '    @model_validator(mode="after")\n'
            + "    def validate_strategy_signal(self) -> Signal:\n"
            + "        if self.data_cutoff_time > self.decision_time:\n"
            + '            raise ValueError("dataCutoffTime must not exceed decisionTime")\n'
            + "        evidence_values = tuple(item.root for item in self.evidence_ids)\n"
            + "        if evidence_values != tuple(sorted(evidence_values)):\n"
            + '            raise ValueError("evidenceIds must be deterministically sorted")\n'
            + "        if len(set(evidence_values)) != len(evidence_values):\n"
            + '            raise ValueError("evidenceIds must not contain duplicates")\n'
            + "        score = Decimal(self.score)\n"
            + "        confidence = Decimal(self.confidence)\n"
            + '        if not score.is_finite() or score < Decimal("-1") or score > Decimal("1"):\n'
            + '            raise ValueError("score must be finite and between -1 and 1")\n'
            + "        if (\n"
            + "            not confidence.is_finite()\n"
            + '            or confidence < Decimal("0")\n'
            + '            or confidence > Decimal("1")\n'
            + "        ):\n"
            + '            raise ValueError("confidence must be finite and between 0 and 1")\n'
            + '        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))\n'
            + "        return self\n\n"
        )
        if "from decimal import Decimal\n" not in content:
            content = content.replace(
                "from __future__ import annotations\n",
                "from __future__ import annotations\n\nfrom decimal import Decimal\n",
                1,
            )
        content = content.replace(class_marker, validator, 1)
    else:
        class_marker = "class StrategyDescriptor(BaseModel):\n"
        if class_marker not in content:
            raise RuntimeError(
                "Generated StrategyDescriptor output changed; validator injection aborted"
            )
        if "from decimal import Decimal\n" not in content:
            content = content.replace(
                "from __future__ import annotations\n",
                "from __future__ import annotations\n\nfrom decimal import Decimal\n",
                1,
            )
        for field_name in ("required_features", "lifecycle_hooks"):
            content, replaced = re.subn(
                rf"    {field_name}: (?:list|set)\[([^\n]+)\]",
                rf"    {field_name}: tuple[\1, ...]",
                content,
                count=1,
            )
            if replaced != 1:
                raise RuntimeError(f"Generated StrategyDescriptor {field_name} annotation changed")
        content, replaced = re.subn(
            r"(    parameter_specs: )list\[(.*?)\]( = Field\()",
            r"\1tuple[\2, ...]\3",
            content,
            count=1,
            flags=re.DOTALL,
        )
        if replaced != 1:
            raise RuntimeError("Generated StrategyDescriptor parameter_specs annotation changed")
        validator = (
            class_marker
            + '    @model_validator(mode="after")\n'
            + "    def validate_strategy_descriptor(self) -> StrategyDescriptor:\n"
            + "        required_features = tuple(self.required_features)\n"
            + "        required_feature_values = tuple(\n"
            + "            item.root for item in required_features\n"
            + "        )\n"
            + "        if required_feature_values != tuple(sorted(required_feature_values)):\n"
            + '            raise ValueError("requiredFeatures must be deterministically sorted")\n'
            + "        if len(set(required_feature_values)) != len(required_feature_values):\n"
            + '            raise ValueError("requiredFeatures must not contain duplicates")\n'
            + "        parameter_specs = tuple(self.parameter_specs)\n"
            + "        names = tuple(spec.name for spec in parameter_specs)\n"
            + "        if names != tuple(sorted(names)):\n"
            + '            raise ValueError("parameterSpecs must be deterministically sorted")\n'
            + "        if len(set(names)) != len(names):\n"
            + '            raise ValueError("parameterSpecs must not contain duplicate names")\n'
            + "        hooks = tuple(self.lifecycle_hooks)\n"
            + '        if hooks != ("initialize", "onDecision", "finalize"):\n'
            + "            raise ValueError(\n"
            + '                "lifecycleHooks must be initialize/onDecision/finalize"\n'
            + "            )\n"
            + "        for spec in parameter_specs:\n"
            + "            if isinstance(spec, IntegerParameterSpec):\n"
            + "                default = spec.default_value\n"
            + "                minimum = spec.minimum\n"
            + "                maximum = spec.maximum\n"
            + "                values = (default, minimum, maximum)\n"
            + "                if any(\n"
            + "                    value is not None and type(value) is not int\n"
            + "                    for value in values\n"
            + "                ):\n"
            + "                    raise ValueError(\n"
            + '                        f"{spec.name} INTEGER values must be exact integers"\n'
            + "                    )\n"
            + "                if minimum is not None and maximum is not None "
            + "and minimum > maximum:\n"
            + "                    raise ValueError(\n"
            + '                        f"{spec.name} minimum must not exceed maximum"\n'
            + "                    )\n"
            + "                if default is not None and minimum is not None "
            + "and default < minimum:\n"
            + '                    raise ValueError(f"{spec.name} default is below minimum")\n'
            + "                if default is not None and maximum is not None "
            + "and default > maximum:\n"
            + '                    raise ValueError(f"{spec.name} default exceeds maximum")\n'
            + "            elif isinstance(spec, DecimalParameterSpec):\n"
            + "                default = (\n"
            + "                    Decimal(spec.default_value)\n"
            + "                    if spec.default_value is not None\n"
            + "                    else None\n"
            + "                )\n"
            + "                minimum = (\n"
            + "                    Decimal(spec.minimum) if spec.minimum is not None else None\n"
            + "                )\n"
            + "                maximum = (\n"
            + "                    Decimal(spec.maximum) if spec.maximum is not None else None\n"
            + "                )\n"
            + "                values = tuple(\n"
            + "                    value\n"
            + "                    for value in (default, minimum, maximum)\n"
            + "                    if value is not None\n"
            + "                )\n"
            + "                if any(not value.is_finite() for value in values):\n"
            + '                    raise ValueError(f"{spec.name} DECIMAL values must be finite")\n'
            + "                if minimum is not None and maximum is not None "
            + "and minimum > maximum:\n"
            + "                    raise ValueError(\n"
            + '                        f"{spec.name} minimum must not exceed maximum"\n'
            + "                    )\n"
            + "                if default is not None and minimum is not None "
            + "and default < minimum:\n"
            + '                    raise ValueError(f"{spec.name} default is below minimum")\n'
            + "                if default is not None and maximum is not None "
            + "and default > maximum:\n"
            + '                    raise ValueError(f"{spec.name} default exceeds maximum")\n'
            + '        object.__setattr__(self, "required_features", required_features)\n'
            + '        object.__setattr__(self, "parameter_specs", parameter_specs)\n'
            + '        object.__setattr__(self, "lifecycle_hooks", hooks)\n'
            + "        return self\n\n"
        )
        content = content.replace(class_marker, validator, 1)

    generated_file.write_text(content, encoding="utf-8", newline="\n")


def prepare_python_codegen_schema(schema_file: Path, tmp_dir: Path) -> Path:
    """Remove schema branches enforced by trusted Python semantic validators."""
    schema = cast(JsonObject, json.loads(schema_file.read_text(encoding="utf-8")))
    changed = False
    for _, model_schema in _iter_model_schemas(schema):
        if model_schema.get("x-python-strip-semantic-branches") is not True:
            continue
        model_schema.pop("allOf", None)
        changed = True
    if not changed:
        return schema_file
    prepared_file = tmp_dir / schema_file.name
    prepared_file.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return prepared_file


def inject_strenum_member_conflicts(schema_file: Path, generated_file: Path) -> None:
    """Rename generated StrEnum members that shadow inherited ``str`` methods."""
    relative_schema = schema_file.relative_to(SCHEMAS_DIR).as_posix()
    if relative_schema != "seat/seat-profile.json":
        return
    content = generated_file.read_text(encoding="utf-8")
    member = '    split = "SPLIT"\n'
    if member not in content:
        raise RuntimeError("Seat profile enum output changed; split member was not found")
    generated_file.write_text(
        content.replace(member, '    split_ = "SPLIT"\n', 1),
        encoding="utf-8",
        newline="\n",
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
    input_schema = prepare_python_codegen_schema(schema_file, tmp_dir)
    cmd = [
        sys.executable,
        "-m",
        "datamodel_code_generator",
        "--input",
        str(input_schema),
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
    inject_strict_strings(schema_file, tmp_file)
    inject_decimal_metadata(schema_file, tmp_file)
    inject_decimal_fields(schema_file, tmp_file)
    inject_strict_bool(schema_file, tmp_file)
    inject_strict_int(schema_file, tmp_file)
    inject_strict_rfc3339(schema_file, tmp_file)
    inject_deleted_condition(schema_file, tmp_file)
    inject_available_time_validator(schema_file, tmp_file)
    inject_schema_validation(schema_file, tmp_file)
    inject_semantic_validators(schema_file, tmp_file)
    inject_strategy_contract_validators(schema_file, tmp_file)
    inject_strenum_member_conflicts(schema_file, tmp_file)
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

    import_command = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        "--select",
        "I",
        "--fix",
    ]
    schema_metadata = cast(JsonObject, json.loads(schema_file.read_text(encoding="utf-8")))
    if schema_metadata.get("x-python-import-known-first-party") is True:
        import_command.extend(["--config", 'lint.isort.known-first-party=["ashare_contracts"]'])
    import_command.append(str(tmp_file))
    import_result = subprocess.run(
        import_command,
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
    public_exports = load_public_exports(schema_files)

    generated_files: list[Path] = []
    for schema_file in schema_files:
        rel = schema_file.relative_to(SCHEMAS_DIR)
        parts = list(rel.parts[:-1]) + [rel.stem]
        module_name = "_".join(parts).replace("-", "_")
        output_file = output_dir / f"{module_name}.py"
        run_datamodel_codegen(schema_file, output_file)
        generated_files.append(output_file)
        print(f"  {output_file}")

    semantic_support_output = output_dir / "backtest_regression_semantics.py"
    if not SEMANTIC_SUPPORT_SOURCE.exists():
        raise RuntimeError(f"missing semantic support source: {SEMANTIC_SUPPORT_SOURCE}")
    shutil.copyfile(SEMANTIC_SUPPORT_SOURCE, semantic_support_output)

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

    semantic_import = (
        "from ashare_contracts.backtest_regression_semantics import "
        "validate_backtest_regression_comparison"
    )
    public_import_lines = [f"from {module} import {symbol}" for module, symbol in public_exports]
    all_import_lines = sorted([*import_lines, *public_import_lines, semantic_import])
    all_content = header + "\n".join(all_import_lines) + "\n"
    if import_lines:
        all_content += "\n__all__ = [\n"
        for _, _, export_name in exports:
            all_content += f'    "{export_name}",\n'
        for _, symbol in public_exports:
            all_content += f'    "{symbol}",\n'
        all_content += '    "validate_backtest_regression_comparison",\n'
        all_content += "]\n"
    init_path.write_text(all_content, encoding="utf-8", newline="\n")
    import_result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "I", "--fix", str(init_path)],
        capture_output=True,
        text=True,
    )
    if import_result.returncode != 0:
        raise RuntimeError(
            f"Error sorting generated imports for {init_path}: {import_result.stderr}"
        )
    (output_dir / "py.typed").write_text("", encoding="utf-8", newline="\n")

    print(f"Generated Python types -> {output_dir}")


def check() -> None:
    """Verify generated files match schemas (regenerate and diff).

    Compares only the generated artifacts (schema modules, __init__.py and
    py.typed), so hand-written subpackages such as providers/ can live
    alongside them without tripping the sync check.  Schema-declared semantic
    validator modules are also hand-written support files and are allowed to
    remain beside the generated DTOs.
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
        semantic_support_names = load_python_support_file_names(sorted(SCHEMAS_DIR.rglob("*.json")))
        for real_file in sorted(OUTPUT_DIR.glob("*.py")):
            if (
                real_file.name not in generated_names
                and real_file.name not in semantic_support_names
                and real_file.name != "__init__.py"
            ):
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
