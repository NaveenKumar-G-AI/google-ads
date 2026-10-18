"""Convenience entry point for Phase 15 setup/credential preflight."""
from __future__ import annotations
import sys
from pathlib import Path
_SRC = Path(__file__).resolve().parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from recovery.staging_preflight import main
if __name__ == "__main__":
    raise SystemExit(main())
