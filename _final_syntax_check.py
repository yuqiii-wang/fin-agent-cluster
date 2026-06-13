"""Compile every .py file under backend/ and report errors."""
import pathlib
import py_compile
import sys
import tempfile

root = pathlib.Path("backend")
errors = []
checked = 0

for py in sorted(root.rglob("*.py")):
    checked += 1
    try:
        with tempfile.NamedTemporaryFile(delete=True) as f:
            py_compile.compile(str(py), cfile=f.name, doraise=True)
    except Exception as exc:
        errors.append((str(py), str(exc)))

for path, err in errors:
    print(f"  FAIL {path}: {err}")

print(f"\nTotal: {checked} files. Syntax errors: {len(errors)}")
sys.exit(0 if not errors else 1)
