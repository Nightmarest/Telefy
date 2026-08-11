from __future__ import annotations

import os
import sys
from pathlib import Path


IS_WINDOWS = os.name == "nt"
IS_MAC = sys.platform == "darwin"

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
CONFIG_PATH = Path(
    os.environ.get("TELEFY_CONFIG", str(PROJECT_ROOT / "config.ini"))
).expanduser()
ASSETS_DIR = PROJECT_ROOT / "assets"
CACHE_DIR = PROJECT_ROOT / ".cache" / "telefy"
