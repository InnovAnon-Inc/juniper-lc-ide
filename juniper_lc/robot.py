#!/usr/bin/env python3
import glob
import json
import os
import re
import subprocess
import sys
from typing import Dict, List, Set, Tuple

INTERPRETER = "lc_2.py"
STDLIB_DIR = "stdlib"

# Benchmark Reference Framework fed to the Planner
TAXONOMY_REFERENCE = """
1. CORE_LOGIC: booleans, Church combinators, FOL, HOL, options/results.
2. NUMERIC_TOWER: naturals, signed ints, rationals (gcd reduced), floats, linear algebra.
3. DATA_STRUCTURES: persistent lists, map/reduce, dictionaries, visual arrays, trees.
4. SYNTHETIC_GEOMETRY: straightedge/compass, bisectors, trisections, tile patterns.
5. PROJECTIVE_GRAPHICS: camera station points, picture plane projection, vanishing lines.
6. KINEMATICS_ANATOMY: 8-head mannequin construction, joint transformations, postures.
7. SYSTEM_SOPS: action monad (pre/post-conditions), dishwashing, tile laying, manuals.
"""


def run_interpreter(filepath: str) -> Tuple[bool, str]:
    """Evaluates an LC file using lc_2.py."""
    res = subprocess.run(
        [sys.executable, INTERPRETER, filepath], capture_output=True, text=True
    )
    return (res.returncode == 0), f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"


def invoke_opencode(prompt: str) -> str:
    """Executes OpenCode CLI non-interactively."""
    cmd = ["opencode", "run", "--prompt", prompt]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.stdout.strip()


def parse_module_symbols(filepath: str) -> Set[str]:
    """Dynamically parses all defined symbols in a file."""
    if not os.path.exists(filepath):
        return set()
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    # Find targets defined via := or ≡
    matches = re.findall(r"^([a-zA-Z0-9_,\s]+)\s*(?::=|≡)", content, re.MULTILINE)
    symbols = set()
    for m in matches:
        for sym in m.split(","):
            symbols.add(sym.strip())
    return symbols


def scan_stdlib() -> Dict[str, Dict]:
    """Dynamically audits all .lc files in the stdlib directory."""
    if not os.path.exists(STDLIB_DIR):
        os.makedirs(STDLIB_DIR)

    files = glob.glob(os.path.join(STDLIB_DIR, "*.lc"))
    inventory = {}

    for filepath in files:
        success, logs = run_interpreter(filepath)
        symbols = parse_module_symbols(filepath)
        with open(filepath, "r", encoding="utf-8") as f:
            code = f.read()

        inventory[os.path.basename(filepath)] = {
            "path": filepath,
            "valid": success,
            "symbols": list(symbols),
            "code": code,
            "logs": logs,
        }
    return inventory


def meta_planner_phase(inventory: Dict) -> Dict:
    """Tier 1: High-Level Planner determines if modules need creation, reorganization, or expansion."""
    summary = {
        k: {"symbols_count": len(v["symbols"]), "valid": v["valid"]}
        for k, v in inventory.items()
    }

    prompt = f"""
You are the Chief Architect of the Pure Lambda Calculus Standard Library.

REFERENCE TAXONOMY:
{TAXONOMY_REFERENCE}

CURRENT STDLIB MODULE INVENTORY:
{json.dumps(summary, indent=2)}

INSTRUCTIONS:
Analyze the inventory against the reference taxonomy. Determine the SINGLE HIGHEST PRIORITY target file to work on next.
If a new file is required, specify its filename.
Return EXACTLY a JSON object (no markdown, no extra text):

{{
  "target_file": "04_church.lc",
  "architectural_goal": "Implement division and modulo arithmetic for Church numerals."
}}
"""
    response = invoke_opencode(prompt)
    clean_json = response.strip().strip("`").replace("json\n", "")
    return json.loads(clean_json)


def module_architect_phase(target_file: str, inventory: Dict) -> Dict:
    """Tier 2: Middle Management creates a specific contract for a single term."""
    filepath = os.path.join(STDLIB_DIR, target_file)
    existing_code = (
        inventory.get(target_file, {}).get("code", "# Module Initialized\n")
    )
    logs = inventory.get(target_file, {}).get("logs", "No evaluation logs.")

    prompt = f"""
You are the Lead Module Engineer for `{target_file}` in the Lambda Calculus Standard Library.

FILE CONTENT:
---
{existing_code}
---

EVALUATION STATUS:
---
{logs}
---

INSTRUCTIONS:
Identify the SINGLE NEXT term, function, or proof needed in this file.
Generate an implementation contract for a single symbol.
Return EXACTLY a JSON object:

{{
  "symbol": "DIV_NUM",
  "instruction": "Define DIV_NUM for Church numerals using repeated subtraction.",
  "required_assertions": [
    "ASSERT_EQ (DIV_NUM 6 2), 3",
    "ASSERT_EQ (DIV_NUM 7 3), 2"
  ]
}}
"""
    response = invoke_opencode(prompt)
    clean_json = response.strip().strip("`").replace("json\n", "")
    return json.loads(clean_json)


def micro_worker_phase(target_file: str, task: Dict) -> bool:
    """Tier 3: Worker implements the symbol and verifies via lc_2.py."""
    filepath = os.path.join(STDLIB_DIR, target_file)
    symbol = task["symbol"]

    prompt = f"""
You are implementing a micro-task for `{filepath}`.

SYMBOL TO DEFINE: {symbol}
SPECIFICATION: {task['instruction']}

ASSERTIONS TO APPEND:
{chr(10).join(task['required_assertions'])}

INSTRUCTIONS:
1. Append the definition (`:=` or `≡`) and assertions to `{filepath}`.
2. Run `python3 {INTERPRETER} {filepath}` in terminal.
3. If assertions fail or recursion limit is exceeded, adjust implementation and re-run.
4. Stop as soon as `python3 {INTERPRETER} {filepath}` exits cleanly with code 0.
"""
    print(f"⚙️ [WORKER] Implementing `{symbol}` in `{target_file}`...")
    invoke_opencode(prompt)

    # Tier 4: Automated Verification Gate
    success, logs = run_interpreter(filepath)
    if success:
        print(f"  ✓ VERIFIED: Term `{symbol}` successfully proven in `{target_file}`.")
        return True
    else:
        print(f"  ❌ FAILED: Term `{symbol}` failed verification.")
        print(f"  [Error Logs]\n{logs}")
        return False


def main():
    print("🚀 Launching Self-Organizing Standard Library Meta-Harness...")

    while True:
        # 1. Audit stdlib directory dynamically
        inventory = scan_stdlib()

        # 2. Meta-Planner selects the focal module
        plan = meta_planner_phase(inventory)
        target_file = plan["target_file"]
        print(f"\n==================================================")
        print(f"Target Module: {target_file}")
        print(f"Architectural Goal: {plan['architectural_goal']}")
        print(f"==================================================")

        # 3. Middle Management generates a single symbol task
        task = module_architect_phase(target_file, inventory)

        # 4. Worker implements and verifies
        success = micro_worker_phase(target_file, task)

        if not success:
            print("⚠️ Re-evaluating module state after failed attempt...")


if __name__ == "__main__":
    main()
