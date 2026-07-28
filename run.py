"""Convenience script to run the lead prospecting pipeline.

Usage:
    python run.py --dry-run
    python run.py --promote
    python run.py --scheduler
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=False)

if __name__ == "__main__":
    from src.__main__ import main
    main()
