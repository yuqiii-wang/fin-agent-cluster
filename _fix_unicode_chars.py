"""Scan all .py files and replace non-ASCII chars commonly used in docstrings with ASCII equivalents."""
import pathlib
import sys

# Character replacement table for commonly used Unicode chars in docstrings.
REPLACEMENTS = {
    "\u2014": "--",   # — em dash
    "\u2013": "-",    # – en dash
    "\u2010": "-",    # ‐ hyphen
    "\u2192": "->",   # → rightwards arrow
    "\u2190": "<-",   # ← leftwards arrow
    "\u21d2": "=>",   # ⇒ rightwards double arrow
    "\u2260": "!=",   # ≠ not equal to
    "\u2264": "<=",   # ≤ less-than or equal to
    "\u2265": ">=",   # ≥ greater-than or equal to
    "\u00a0": " ",    # non-breaking space
    "\u2018": "'",    # ‘ left single quote
    "\u2019": "'",    # ’ right single quote
    "\u201c": '"',    # “ left double quote
    "\u201d": '"',    # ” right double quote
    "\u2026": "...",  # … horizontal ellipsis
    "\u00b5": "u",    # µ micro sign
}

root = pathlib.Path("backend")
total = 0
files = 0
for py in sorted(root.rglob("*.py")):
    try:
        content = py.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        print(f"  SKIP (encoding) {py}")
        continue
    new_content = content
    for ch, rep in REPLACEMENTS.items():
        if ch in new_content:
            new_content = new_content.replace(ch, rep)
    if new_content != content:
        py.write_text(new_content, encoding="utf-8")
        files += 1
        total += sum(content.count(ch) for ch in REPLACEMENTS if ch in content)
        print(f"  fixed {py}")

print(f"\nFixed {files} files, {total} total char replacements")
sys.exit(0)
