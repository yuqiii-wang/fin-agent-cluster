import ast
import pathlib
import sys

errs = 0
files = list(pathlib.Path("backend").rglob("*.py"))
failed = []
for p in files:
    try:
        text = p.read_text(encoding="utf-8")
        compile(text, str(p), "exec")
    except (SyntaxError, UnicodeDecodeError) as e:
        errs += 1
        failed.append((str(p), str(e)))

print(f"Parsed {len(files)} files. Errors: {errs}")
for f, e in failed:
    print(f"  FAIL {f}: {e}")

sys.exit(0 if errs == 0 else 1)
