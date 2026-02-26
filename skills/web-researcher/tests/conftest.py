"""web-researcher テスト用フィクスチャ"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

_wr_root = str(Path(__file__).resolve().parents[1])
_scripts_dir = str(Path(__file__).resolve().parents[1] / "scripts")
for _p in (_wr_root, _scripts_dir):
    if _p not in sys.path:
        sys.path.append(_p)

# --- Fixtures ---

@pytest.fixture
def default_config():
    """default_config.yaml を読み込む。"""
    config_path = Path(__file__).resolve().parents[1] / "references" / "default_config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture
def mock_httpx_client():
    """httpx.Client のモック。"""
    with patch("scripts.collector_base.httpx.Client") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)
        yield mock_client


@pytest.fixture
def tmp_data_dir(tmp_path):
    """一時データディレクトリ。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def mock_robots_allow():
    """robots.txt が許可するモック。"""
    with patch("scripts.collector_base.urllib.robotparser.RobotFileParser") as mock_cls:
        mock_rp = MagicMock()
        mock_rp.can_fetch.return_value = True
        mock_cls.return_value = mock_rp
        yield mock_rp


@pytest.fixture
def mock_robots_deny():
    """robots.txt が拒否するモック。"""
    with patch("scripts.collector_base.urllib.robotparser.RobotFileParser") as mock_cls:
        mock_rp = MagicMock()
        mock_rp.can_fetch.return_value = False
        mock_cls.return_value = mock_rp
        yield mock_rp
