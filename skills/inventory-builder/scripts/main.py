from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _repo_root() -> Path:
    # scripts/main.py -> scripts/ -> inventory-builder/ -> skills/ -> bank/
    # parents[0]=scripts, [1]=inventory-builder, [2]=skills, [3]=bank(repo root)
    return Path(__file__).resolve().parents[3]


def _data_root() -> Path:
    import os

    configured = os.environ.get("DATA_PATH")
    if not configured:
        return _repo_root() / "data"
    p = Path(configured).expanduser()
    return p if p.is_absolute() else (_repo_root() / p).resolve()


def _load_builder():
    """builder モジュールを遅延ロードし、未配備時は明示エラーを返す。"""
    try:
        if __name__ == "__main__":
            script_dir = Path(__file__).resolve().parent
            if str(script_dir) not in sys.path:
                sys.path.insert(0, str(script_dir))
            from builder import build_inventory
        else:
            from .builder import build_inventory
        return build_inventory
    except ImportError:
        builder_path = Path(__file__).resolve().parent / "builder.py"
        raise ImportError(
            f"builder.py が見つかりません: {builder_path}\n"
            "builder.py を配置してから再実行してください。"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inventory builder — generate inventory.md from collected/parsed data"
    )
    parser.add_argument(
        "--ticker", required=True, help="Security code (e.g., 2780)"
    )
    parser.add_argument(
        "--fye-month",
        required=True,
        type=int,
        choices=range(1, 13),
        metavar="{1..12}",
        help="Fiscal year end month (1-12, e.g., 3 for March)",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="Data root directory (default: auto-detect)",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=None,
        help="Output path for inventory.md (default: data/{ticker}/inventory.md)",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    data_root = args.data_root or _data_root()

    try:
        build_inventory = _load_builder()
    except ImportError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1

    ticker_dir = data_root / args.ticker
    if not ticker_dir.is_dir():
        print(
            f"エラー: データディレクトリが存在しません: {ticker_dir}",
            file=sys.stderr,
        )
        return 1

    try:
        output = build_inventory(
            args.ticker, args.fye_month, data_root, args.output_path
        )
        print(f"inventory.md を生成しました: {output}")
        return 0
    except Exception as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
