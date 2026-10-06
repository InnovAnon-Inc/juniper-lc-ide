from pathlib import Path
import pytest
from juniper_lc.lc import execute_program

# Collect all test .lc files inside tests/juniper_lc/stdlib/
STDLIB_TESTS_DIR = Path("tests/juniper_lc/stdlib")
LC_TEST_FILES = sorted(STDLIB_TESTS_DIR.glob("**/*.lc"))

@pytest.mark.parametrize("test_file", LC_TEST_FILES, ids=lambda p: p.name)
def test_lc_file(test_file):
    code = test_file.read_text(encoding="utf-8")
    
    # Run through the interpreter
    output_lines, final_env, final_declared = execute_program(
        filename=str(test_file),
        code=code,
        env={},
        declared_terms={},
        quiet=True
    )
    
    # Ensure execution completed successfully without returning error markers
    assert output_lines is not None



@pytest.mark.parametrize("test_file", LC_TEST_FILES, ids=lambda p: p.name)
def test_lc_snapshot(test_file):
    expected_out_file = test_file.with_suffix(".out")
    code = test_file.read_text(encoding="utf-8")

    output_lines, _, _ = execute_program(
        filename=str(test_file),
        code=code,
        env={},
        declared_terms={},
        quiet=True
    )

    if expected_out_file.exists():
        expected_output = expected_out_file.read_text().splitlines()
        assert output_lines == expected_output
