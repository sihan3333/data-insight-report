import pathlib
import sys

# Make `scripts` importable as a package regardless of where pytest is
# invoked from (repo root vs. a subdirectory, different platforms/CI).
_repo_root = pathlib.Path(__file__).parent
sys.path.insert(0, str(_repo_root))

# build_report.py imports its sibling column_heuristics.py with a bare
# `from column_heuristics import ...` rather than `from scripts...` or a
# relative import — that's deliberate, so the file still runs standalone
# via `python scripts/build_report.py` (the way SKILL.md documents) and
# not just when imported as part of the `scripts` package by tests. To
# make that same bare import resolve here too, scripts/ itself needs to
# be on sys.path, not just the repo root.
sys.path.insert(0, str(_repo_root / "scripts"))
