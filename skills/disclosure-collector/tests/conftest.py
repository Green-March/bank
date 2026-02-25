"""disclosure-collector テスト用パス設定"""

import sys
from pathlib import Path

_scripts_dir = str(Path(__file__).resolve().parents[1] / "scripts")
if _scripts_dir not in sys.path:
    sys.path.append(_scripts_dir)
