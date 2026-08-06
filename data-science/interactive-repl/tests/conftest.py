import sys, pathlib

# Make scripts/ importable as top-level modules (import _common, import python_worker, ...)
# when running tests via pytest from the skill root or the repo root.
SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
