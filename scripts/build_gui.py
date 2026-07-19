from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import build_gui


if __name__ == "__main__":
    raise SystemExit(build_gui())
