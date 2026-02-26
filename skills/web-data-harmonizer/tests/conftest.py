import json
import sys
from pathlib import Path

import pytest

_scripts_dir = str(Path(__file__).resolve().parents[1] / "scripts")
if _scripts_dir not in sys.path:
    sys.path.append(_scripts_dir)

EVIDENCE_DIR = Path(__file__).resolve().parent / "evidence"


@pytest.fixture
def sample_web_research():
    """web-researcher 出力形式のサンプルデータを読み込む。"""
    path = EVIDENCE_DIR / "sample_web_research.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def tmp_output_dir(tmp_path):
    """テスト用一時出力ディレクトリ。"""
    out = tmp_path / "output"
    out.mkdir()
    return out
