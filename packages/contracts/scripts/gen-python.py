#!/usr/bin/env python3
"""
Generate Python Pydantic models from JSON Schema contracts.

Usage:
  python scripts/gen-python.py          # generate
  python scripts/gen-python.py --check  # verify generated == schema
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT / "schemas"
OUTPUT_DIR = ROOT.parent.parent / "python" / "packages" / "ashare-contracts" / "src" / "ashare_contracts"


def run_datamodel_codegen(schema_file: Path, output_file: Path) -> None:
    """Run datamodel-code-generator on a single schema file."""
    cmd = [
        sys.executable,
        "-m",
        "datamodel_code_generator",
        "--input",
        str(schema_file),
        "--input-file-type",
        "jsonschema",
        "--output",
        str(output_file),
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
        print(f"Error generating {schema_file}:", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)


def generate() -> None:
    """Generate Python types from all JSON Schema files."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    header = "# Generated from packages/contracts/schemas/. DO NOT EDIT BY HAND.\n\n"

    schema_files = sorted(SCHEMAS_DIR.glob("*.json"))
    if not schema_files:
        print("No schema files found in", SCHEMAS_DIR, file=sys.stderr)
        sys.exit(1)

    generated_files = []
    for schema_file in schema_files:
        module_name = schema_file.stem.replace("-", "_")
        output_file = OUTPUT_DIR / f"{module_name}.py"
        run_datamodel_codegen(schema_file, output_file)
        generated_files.append(output_file)
        print(f"  {output_file}")

    # Write __init__.py that re-exports all generated models
    init_path = OUTPUT_DIR / "__init__.py"
    module_imports: dict[str, set[str]] = {}
    for sf in schema_files:
        module_name = sf.stem.replace("-", "_")
        gen_file = OUTPUT_DIR / f"{module_name}.py"
        if gen_file.exists():
            content = gen_file.read_text(encoding="utf-8")
            import re
            classes = re.findall(r"^class (\w+)", content, re.MULTILINE)
            if classes:
                module_imports[module_name] = set(classes)

    import_lines = []
    for module_name in sorted(module_imports):
        for cls in sorted(module_imports[module_name]):
            import_lines.append(f"from ashare_contracts.{module_name} import {cls} as {cls}")

    all_content = header + "\n".join(import_lines) + "\n"
    if import_lines:
        all_content += "\n__all__ = [\n"
        for module_name in sorted(module_imports):
            for cls in sorted(module_imports[module_name]):
                all_content += f'    "{cls}",\n'
        all_content += "]\n"
    init_path.write_text(all_content, encoding="utf-8")

    print(f"Generated Python types -> {OUTPUT_DIR}")


def check() -> None:
    """Verify generated files match schemas (regenerate and diff)."""
    global OUTPUT_DIR
    import tempfile
    import filecmp

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_output = Path(tmpdir) / "ashare_contracts"
        old_output_dir = OUTPUT_DIR
        OUTPUT_DIR = tmp_output
        try:
            generate()
        finally:
            OUTPUT_DIR = old_output_dir

        # Compare
        if not old_output_dir.exists():
            print("ERROR: Generated Python output directory does not exist:", old_output_dir)
            sys.exit(1)

        dircmp = filecmp.dircmp(str(tmp_output), str(old_output_dir))
        if dircmp.diff_files or dircmp.left_only or dircmp.right_only:
            print("ERROR: Generated Python types are out of sync with JSON Schema.")
            print("Run `pnpm gen:python` from packages/contracts/ to regenerate.")
            if dircmp.diff_files:
                print("  Differing files:", dircmp.diff_files)
            if dircmp.left_only:
                print("  New files:", dircmp.left_only)
            if dircmp.right_only:
                print("  Missing files:", dircmp.right_only)
            sys.exit(1)

        print("Python types are in sync with JSON Schema.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Python types from JSON Schema")
    parser.add_argument("--check", action="store_true", help="Verify generated files are up-to-date")
    args = parser.parse_args()

    if args.check:
        check()
    else:
        generate()


if __name__ == "__main__":
    main()
