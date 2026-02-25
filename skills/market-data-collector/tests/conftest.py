"""market-data-collector テスト用パス設定"""

import sys
from pathlib import Path

_mdc_root = str(Path(__file__).resolve().parents[1])
_scripts_dir = str(Path(__file__).resolve().parents[1] / "scripts")
for _p in (_mdc_root, _scripts_dir):
    if _p not in sys.path:
        sys.path.append(_p)
