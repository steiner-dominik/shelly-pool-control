import os
import pathlib
import sys
import tempfile

# Make `app` importable when pytest runs from the repository root.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# Test environment must be set before any app module is imported.
_tmp = tempfile.mkdtemp(prefix="pool-test-")
os.environ.setdefault("POOL_DATA_DIR", _tmp)
os.environ.setdefault("POOL_SIMULATE", "1")
os.environ.setdefault("POOL_VERSION", "test")
