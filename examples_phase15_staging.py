"""Convenience entry point for Phase 15 live staging validation."""
from __future__ import annotations
import sys
from pathlib import Path
_PROJECT_SRC = Path(__file__).resolve().parent / "src"
if _PROJECT_SRC.is_dir() and str(_PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(_PROJECT_SRC))
from recovery.staging_validation import main
if __name__ == "__main__":
    main()
