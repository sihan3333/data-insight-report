import pathlib
import sys

# Make `scripts` importable as a package regardless of where pytest is
# invoked from (repo root vs. a subdirectory, different platforms/CI).
sys.path.insert(0, str(pathlib.Path(__file__).parent))
