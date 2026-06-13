"""Compile every .py file under backend/ and report errors (pure compile)."""
import pathlib
import sys

root = pathlib.Path("backend")
errors = []
checked = 0

for py in sorted(root.rglob("*.py")):
    checked += 1
    try:
        compile(py.read_text(encoding="utf-8"), str(py), "exec")
    except Exception as exc:
        errors.append((str(py), str(exc)))

for path, err in errors:
    print(f"  FAIL {path}: {err}")

print(f"\nTotal: {checked} files. Syntax errors: {len(errors)}")
sys.exit(0 if not errors else 1)
