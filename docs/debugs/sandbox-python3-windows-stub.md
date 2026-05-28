# Sandbox: Windows python3 Store stub alias

## Issue
`execute_python` returned exit code 9009 on Windows/git bash with stderr:
```
Python was not found; run without arguments to install from the Microsoft Store...
```

## Root cause
`shutil.which("python3")` on Windows resolves to
`C:\Users\...\WindowsApps\python3.exe`, which is a Microsoft Store stub
(redirect alias) rather than a real interpreter.  The stub exits immediately
with code 9009.

`sys.executable` was intended as fallback but was never reached because
`shutil.which` did return a path (the stub).

## Fix
Use `sys.executable` directly — it is always the interpreter currently running
the process.  On WSL2 backend it is `/home/yuqi/miniconda3/bin/python3`; on
Windows git bash it is the Miniconda `python.exe`.  No fallback is needed.

```python
# before
python_exe = shutil.which("python3") or sys.executable

# after
python_exe = sys.executable
```

## Note on bash stdin (git bash only)
`while read line; done` does not pipe stdin correctly when spawned via
`subprocess.Popen` on MSYS2/git bash — a known Windows console stdin quirk.
This does **not** affect the WSL2 production environment where `/bin/bash` is
native Linux bash and `proc.communicate(input=...)` works correctly.
