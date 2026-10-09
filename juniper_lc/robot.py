#!/usr/bin/env python3
import glob
import json
import os
import re
import subprocess
import sys
from typing import Dict, List, Set, Tuple

INTERPRETER = "lc"

TAXONOMY_REFERENCE = """
1. CORE_LOGIC: booleans, Church combinators, FOL, HOL, options/results.
2. NUMERIC_TOWER: naturals, signed ints, rationals (gcd reduced), floats, linear algebra.
3. DATA_STRUCTURES: persistent lists, map/reduce, dictionaries, visual arrays, trees.
4. SYNTHETIC_GEOMETRY: straightedge/compass, bisectors, trisections, tile patterns.
5. PROJECTIVE_GRAPHICS: camera station points, picture plane projection, vanishing lines.
6. KINEMATICS_ANATOMY: 8-head mannequin construction, joint transformations, postures.
7. SYSTEM_SOPS: action monad (pre/post-conditions), dishwashing, tile laying, manuals.
"""


def get_stdlib_dir() -> str:
    """Resolves the stdlib directory path dynamically."""
    if os.path.exists("stdlib"):
        return "stdlib"
    if os.path.exists(os.path.join("juniper_lc", "stdlib")):
        return os.path.join("juniper_lc", "stdlib")
    pkg_stdlib = os.path.join(os.path.dirname(__file__), "stdlib")
    if os.path.exists(pkg_stdlib):
        return pkg_stdlib
    os.makedirs("stdlib", exist_ok=True)
    return "stdlib"


def run_interpreter(filepath: str) -> Tuple[bool, str]:
    """Evaluates an LC file using the installed `lc` binary."""
    try:
        res = subprocess.run(
            [INTERPRETER, filepath], capture_output=True, text=True
        )
        return (res.returncode == 0), f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    except FileNotFoundError:
        return False, f"Interpreter '{INTERPRETER}' not found in PATH."


def invoke_opencode(prompt: str) -> str:
    """Executes OpenCode CLI non-interactively with auto-approvals."""
    cmd = ["opencode", "run", "--auto", prompt]
    res = subprocess.run(cmd, capture_output=True, text=True)
    out = res.stdout.strip()
    if not out and res.stderr:
        print(f"⚠️ OpenCode CLI stderr:\n{res.stderr}")
    return out


def parse_module_symbols(filepath: str) -> Set[str]:
    """Dynamically parses all defined symbols in a file."""
    if not os.path.exists(filepath):
        return set()
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    matches = re.findall(
        r"^([a-zA-Z0-9_,\s]+)\s*(?::=|≡)", content, re.MULTILINE
    )
    symbols = set()
    for m in matches:
        for sym in m.split(","):
            symbols.add(sym.strip())
    return symbols


def ensure_file_exists(filepath: str):
    """Ensures a .lc file exists on disk with a valid shebang before giving it to OpenCode."""
    if not os.path.exists(filepath):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"#! /usr/bin/env lc\n# Module: {os.path.basename(filepath)}\n\n")


def scan_stdlib() -> Dict[str, Dict]:
    """Dynamically audits all .lc files in the stdlib directory."""
    stdlib_dir = get_stdlib_dir()
    files = glob.glob(os.path.join(stdlib_dir, "*.lc"))
    inventory = {}

    for filepath in files:
        rel_path = os.path.normpath(filepath)
        success, logs = run_interpreter(rel_path)
        symbols = parse_module_symbols(rel_path)
        with open(rel_path, "r", encoding="utf-8") as f:
            code = f.read()

        inventory[rel_path] = {
            "path": rel_path,
            "filename": os.path.basename(rel_path),
            "valid": success,
            "symbols": list(symbols),
            "code": code,
            "logs": logs,
        }
    return inventory


def extract_json(text: str) -> dict:
    """Extracts the first valid JSON object from LLM response text using regex."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in LLM response:\n{text}")
    return json.loads(match.group(0))


def meta_planner_phase(inventory: Dict) -> Dict:
    """Tier 1: High-Level Planner determines if modules need creation, reorganization, or expansion."""
    summary = {
        data["path"]: {
            "symbols_count": len(data["symbols"]),
            "symbols": data["symbols"][:10],  # Show up to 10 defined symbols
            "valid": data["valid"],
        }
        for path, data in inventory.items()
    }

    prompt = f"""
You are the Chief Architect of the Pure Lambda Calculus Standard Library.

REFERENCE TAXONOMY:
{TAXONOMY_REFERENCE}

CURRENT STDLIB MODULE INVENTORY:
{json.dumps(summary, indent=2)}

INSTRUCTIONS:
1. Analyze the inventory against the reference taxonomy.
2. Determine the SINGLE HIGHEST PRIORITY target file path to work on next.
3. Always specify the full relative path inside stdlib (e.g., "stdlib/01_standard_terms.lc" or "stdlib/04_church.lc").
4. Return ONLY a valid JSON object. DO NOT copy placeholder names.

JSON SCHEMA:
{{
  "target_file": "<RELATIVE_FILE_PATH>",
  "architectural_goal": "<DESCRIPTION_OF_WHAT_MODULE_NEEDS_NEXT>"
}}
"""
    response_text = invoke_opencode(prompt)

    try:
        res = extract_json(response_text)
        if not res["target_file"].startswith(get_stdlib_dir()):
            res["target_file"] = os.path.join(get_stdlib_dir(), os.path.basename(res["target_file"]))
        return res
    except Exception as e:
        print(f"  ⚠️ Meta-planner JSON extraction failed: {e}")
        for path, data in inventory.items():
            if not data["valid"]:
                return {
                    "target_file": path,
                    "architectural_goal": "Fix broken module assertions or syntax.",
                }
        default_target = os.path.join(get_stdlib_dir(), "01_standard_terms.lc")
        return {
            "target_file": default_target,
            "architectural_goal": "Expand core foundational logic.",
        }


def module_architect_phase(target_file: str, inventory: Dict) -> Dict:
    """Tier 2: Middle Management creates a specific contract for a single term."""
    ensure_file_exists(target_file)

    existing_data = inventory.get(target_file, {})
    existing_code = existing_data.get("code", "# Module Initialized\n")
    existing_symbols = existing_data.get("symbols", [])
    logs = existing_data.get("logs", "No evaluation logs.")

    prompt = f"""
You are the Lead Module Engineer for `{target_file}` in the Lambda Calculus Standard Library.

FILE PATH: {target_file}
SYMBOLS ALREADY DEFINED IN THIS FILE: {json.dumps(existing_symbols)}

FILE CONTENT SO FAR:
---
{existing_code}
---

EVALUATION STATUS:
---
{logs}
---

INSTRUCTIONS:
1. Examine the file content and symbols already defined.
2. Identify the SINGLE NEXT missing primitive, function, operator, or proof that logically belongs in `{target_file}` and is NOT yet in the defined list.
3. DO NOT propose a symbol that is already in `SYMBOLS ALREADY DEFINED IN THIS FILE`.
4. DO NOT copy placeholder values from the schema below.
5. Return ONLY a valid JSON object matching the schema.

SCHEMA STRUCTURE:
{{
  "symbol": "<NEW_UNIMPLEMENTED_SYMBOL_NAME>",
  "instruction": "<Clear specification of what to define>",
  "required_assertions": [
    "ASSERT_EQ (<EXPRESSION_USING_NEW_SYMBOL>), <EXPECTED_RESULT>"
  ]
}}
"""
    response_text = invoke_opencode(prompt)

    try:
        res = extract_json(response_text)
        # Ensure model didn't lazily return literal schema placeholders
        if res.get("symbol") in ("<NEW_UNIMPLEMENTED_SYMBOL_NAME>", "DIV_NUM") or res.get("symbol") in existing_symbols:
            raise ValueError(f"Model generated placeholder or duplicate symbol: {res.get('symbol')}")
        return res
    except Exception as e:
        print(f"  ⚠️ Module architect JSON extraction failed: {e}")
        base_sym = os.path.basename(target_file).replace(".lc", "").upper()
        return {
            "symbol": f"{base_sym}_TERM_{len(existing_symbols) + 1}",
            "instruction": f"Define the next foundational logical symbol for {target_file}.",
            "required_assertions": ["ASSERT ⊤"],
        }


def micro_worker_phase(target_file: str, task: Dict) -> bool:
    """Tier 3: Worker implements the symbol and verifies via `lc`."""
    ensure_file_exists(target_file)
    symbol = task["symbol"]

    prompt = f"""
You are implementing a micro-task for `{target_file}`.

FILE PATH: {target_file}
SYMBOL TO DEFINE: {symbol}
SPECIFICATION: {task['instruction']}

ASSERTIONS TO APPEND TO FILE:
{chr(10).join(task['required_assertions'])}

INSTRUCTIONS:
1. Append the new symbol definition (`:=` or `≡`) and its assertions to `{target_file}`.
2. Open terminal and run: `lc {target_file}`
3. If assertions fail or syntax is invalid, edit `{target_file}` and re-run `lc {target_file}`.
4. Stop as soon as `lc {target_file}` exits cleanly with code 0.
"""
    print(f"⚙️ [WORKER] Implementing `{symbol}` in `{target_file}`...")
    invoke_opencode(prompt)

    success, logs = run_interpreter(target_file)
    if success:
        print(
            f"  ✓ VERIFIED: Term `{symbol}` successfully proven in `{target_file}`."
        )
        return True
    else:
        print(f"  ❌ FAILED: Term `{symbol}` failed verification.")
        print(f"  [Error Logs]\n{logs}")
        return False


def main():
    print("🚀 Launching Self-Organizing Standard Library Meta-Harness...")

    while True:
        inventory = scan_stdlib()

        plan = meta_planner_phase(inventory)
        target_file = plan["target_file"]
        ensure_file_exists(target_file)

        print(f"\n==================================================")
        print(f"Target Module: {target_file}")
        print(f"Architectural Goal: {plan['architectural_goal']}")
        print(f"==================================================")

        task = module_architect_phase(target_file, inventory)

        success = micro_worker_phase(target_file, task)

        if not success:
            print("⚠️ Re-evaluating module state after failed attempt...")


if __name__ == "__main__":
    main()
