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

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT / "schemas"
OUTPUT_DIR = (
    ROOT.parent.parent / "python" / "packages" / "ashare-contracts" / "src" / "ashare_contracts"
)

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
    data = json.loads(rules_path.read_text(encoding="utf-8"))
    rules = data.get("rules")
    if not isinstance(rules, list):
        raise RuntimeError(f"Invalid code-prefix rules in {rules_path}")
    normalized: list[tuple[str, str, str, str]] = []
    for rule in rules:
        if not isinstance(rule, dict) or any(
            not isinstance(rule.get(field), str)
            for field in ("prefix", "exchange", "board", "type")
        ):
            raise RuntimeError(f"Invalid code-prefix rule in {rules_path}")
        normalized.append((rule["prefix"], rule["exchange"], rule["board"], rule["type"]))
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


def generate() -> None:
    """Generate Python types from all JSON Schema files."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    header = "# Generated from packages/contracts/schemas/. DO NOT EDIT BY HAND.\n\n"

    # Recursively collect *.json so subdirectories (schemas/instrument/) are supported.
    # The output module name is flattened from the relative path: instrument/exchange.json
    # -> instrument_exchange.py; top-level files keep their stem.
    schema_files = sorted(SCHEMAS_DIR.rglob("*.json"))
    if not schema_files:
        print("No schema files found in", SCHEMAS_DIR, file=sys.stderr)
        sys.exit(1)

    generated_files = []
    for schema_file in schema_files:
        rel = schema_file.relative_to(SCHEMAS_DIR)
        parts = list(rel.parts[:-1]) + [rel.stem]
        module_name = "_".join(parts).replace("-", "_")
        output_file = OUTPUT_DIR / f"{module_name}.py"
        run_datamodel_codegen(schema_file, output_file)
        generated_files.append(output_file)
        print(f"  {output_file}")

    # Write __init__.py that re-exports all generated models
    init_path = OUTPUT_DIR / "__init__.py"
    module_imports: dict[str, set[str]] = {}
    for sf in schema_files:
        rel = sf.relative_to(SCHEMAS_DIR)
        parts = list(rel.parts[:-1]) + [rel.stem]
        module_name = "_".join(parts).replace("-", "_")
        gen_file = OUTPUT_DIR / f"{module_name}.py"
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

    import_lines = [
        f"from ashare_contracts.{module_name} import {cls} as {export_name}"
        for module_name, cls, export_name in exports
    ]

    all_content = header + "\n".join(import_lines) + "\n"
    if import_lines:
        all_content += "\n__all__ = [\n"
        for _, _, export_name in exports:
            all_content += f'    "{export_name}",\n'
        all_content += "]\n"
    init_path.write_text(all_content, encoding="utf-8", newline="\n")
    (OUTPUT_DIR / "py.typed").write_text("", encoding="utf-8", newline="\n")

    print(f"Generated Python types -> {OUTPUT_DIR}")


def check() -> None:
    """Verify generated files match schemas (regenerate and diff).

    Compares only the generated artifacts (schema modules, __init__.py and
    py.typed), so hand-written subpackages such as providers/ can live
    alongside them without tripping the sync check.
    """
    global OUTPUT_DIR
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_output = Path(tmpdir) / "ashare_contracts"
        old_output_dir = OUTPUT_DIR
        OUTPUT_DIR = tmp_output
        try:
            generate()
        finally:
            OUTPUT_DIR = old_output_dir

        if not old_output_dir.exists():
            print("ERROR: Generated Python output directory does not exist:", old_output_dir)
            sys.exit(1)

        mismatches: list[str] = []
        for tmp_file in sorted(tmp_output.rglob("*.py")):
            rel = tmp_file.relative_to(tmp_output)
            real_file = old_output_dir / rel
            if not real_file.exists():
                mismatches.append(f"missing: {rel}")
            elif real_file.read_text(encoding="utf-8") != tmp_file.read_text(encoding="utf-8"):
                mismatches.append(f"differing: {rel}")
        if not (old_output_dir / "py.typed").exists():
            mismatches.append("missing: py.typed")

        generated_names = {f.name for f in tmp_output.glob("*.py")}
        for real_file in sorted(old_output_dir.glob("*.py")):
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
