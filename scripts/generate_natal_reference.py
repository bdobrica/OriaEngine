"""Record upstream swetest output, independent of the Oria adapter.

Build libswe/swetest from the locked pyswisseph source archive first.
Usage: uv run python scripts/generate_natal_reference.py /path/to/swetest
"""

import os
import subprocess
import sys
from pathlib import Path

args = [
    "-b1.1.2000",
    "-utc12:00:00",
    "-p0123456789",
    "-emos",
    "-edir/nonexistent/oria-ephemeris",
    "-house0,51.5,p",
    "-fPls",
    "-g,",
    "-head",
]
env = {k: v for k, v in os.environ.items() if k != "SE_EPHE_PATH"}
result = subprocess.run([sys.argv[1], *args], check=True, capture_output=True, text=True, env=env)
path = Path(__file__).resolve().parents[1] / "tests/contract/fixtures/natal-swetest.csv"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(result.stdout)
