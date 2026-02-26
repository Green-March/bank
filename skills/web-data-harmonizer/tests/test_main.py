"""web-data-harmonizer: main.py (CLI) のユニットテスト。

テスト対象:
- build_parser
- cmd_harmonize
- main
"""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from main import build_parser, cmd_harmonize, main

EVIDENCE_DIR = Path(__file__).resolve().parent / "evidence"
MAIN_PY = str(Path(__file__).resolve().parents[1] / "scripts" / "main.py")


def _run_main(*args: str) -> subprocess.CompletedProcess:
    """main.py をサブプロセスとして実行。"""
    return subprocess.run(
        [sys.executable, MAIN_PY, *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


# ============================================================
# build_parser
# ============================================================
class TestBuildParser:
    def test_required_ticker(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["harmonize"])

    def test_default_source(self):
        parser = build_parser()
        args = parser.parse_args(["harmonize", "--ticker", "2780"])
        assert args.source == "all"

    def test_custom_paths(self):
        parser = build_parser()
        args = parser.parse_args([
            "harmonize", "--ticker", "2780",
            "--input", "/tmp/in.json",
            "--output", "/tmp/out.json",
        ])
        assert args.input == "/tmp/in.json"
        assert args.output == "/tmp/out.json"

    def test_no_command(self):
        parser = build_parser()
        args = parser.parse_args([])
        assert not hasattr(args, "command") or args.command is None


# ============================================================
# cmd_harmonize
# ============================================================
class TestCmdHarmonize:
    def test_normal(self, tmp_output_dir):
        input_path = str(EVIDENCE_DIR / "sample_web_research.json")
        output_path = str(tmp_output_dir / "result.json")
        parser = build_parser()
        args = parser.parse_args([
            "harmonize", "--ticker", "2780",
            "--input", input_path,
            "--output", output_path,
        ])
        ret = cmd_harmonize(args)
        assert ret == 0
        assert Path(output_path).exists()
        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["ticker"] == "2780"

    def test_stdout(self, tmp_output_dir, capsys):
        input_path = str(EVIDENCE_DIR / "sample_web_research.json")
        output_path = str(tmp_output_dir / "result.json")
        parser = build_parser()
        args = parser.parse_args([
            "harmonize", "--ticker", "2780",
            "--input", input_path,
            "--output", output_path,
        ])
        cmd_harmonize(args)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ticker"] == "2780"

    def test_dir_creation(self, tmp_path):
        input_path = str(EVIDENCE_DIR / "sample_web_research.json")
        nested = tmp_path / "a" / "b" / "c" / "result.json"
        parser = build_parser()
        args = parser.parse_args([
            "harmonize", "--ticker", "2780",
            "--input", input_path,
            "--output", str(nested),
        ])
        ret = cmd_harmonize(args)
        assert ret == 0
        assert nested.exists()

    def test_not_found(self, tmp_path, capsys):
        parser = build_parser()
        args = parser.parse_args([
            "harmonize", "--ticker", "2780",
            "--input", str(tmp_path / "nonexistent.json"),
            "--output", str(tmp_path / "out.json"),
        ])
        ret = cmd_harmonize(args)
        assert ret == 1
        captured = capsys.readouterr()
        assert captured.err != "" or "not found" in captured.err.lower() or "error" in captured.err.lower() or ret == 1

    def test_not_found_no_output_file(self, tmp_path):
        parser = build_parser()
        output_path = tmp_path / "should_not_exist.json"
        args = parser.parse_args([
            "harmonize", "--ticker", "2780",
            "--input", str(tmp_path / "nonexistent.json"),
            "--output", str(output_path),
        ])
        cmd_harmonize(args)
        assert not output_path.exists()

    def test_broken_json_input(self, tmp_path, capsys):
        broken = tmp_path / "broken.json"
        broken.write_text("{invalid json content", encoding="utf-8")
        parser = build_parser()
        args = parser.parse_args([
            "harmonize", "--ticker", "2780",
            "--input", str(broken),
            "--output", str(tmp_path / "out.json"),
        ])
        ret = cmd_harmonize(args)
        assert ret == 1
        captured = capsys.readouterr()
        assert captured.err != "" or ret == 1

    def test_custom_paths(self, tmp_output_dir):
        input_path = str(EVIDENCE_DIR / "sample_web_research.json")
        output_path = str(tmp_output_dir / "custom_out.json")
        parser = build_parser()
        args = parser.parse_args([
            "harmonize", "--ticker", "2780",
            "--input", input_path,
            "--output", output_path,
        ])
        ret = cmd_harmonize(args)
        assert ret == 0
        assert Path(output_path).exists()

    def test_source_option(self, tmp_output_dir):
        input_path = str(EVIDENCE_DIR / "sample_web_research.json")
        output_path = str(tmp_output_dir / "filtered.json")
        parser = build_parser()
        args = parser.parse_args([
            "harmonize", "--ticker", "2780",
            "--source", "yahoo",
            "--input", input_path,
            "--output", output_path,
        ])
        ret = cmd_harmonize(args)
        assert ret == 0
        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)
        meta = data["harmonization_metadata"]
        assert "yahoo" in meta["sources_used"]
        assert "kabutan" not in meta["sources_used"]

    def test_invalid_source(self, tmp_output_dir, capsys):
        input_path = str(EVIDENCE_DIR / "sample_web_research.json")
        output_path = str(tmp_output_dir / "invalid_src.json")
        parser = build_parser()
        args = parser.parse_args([
            "harmonize", "--ticker", "2780",
            "--source", "invalid_source",
            "--input", input_path,
            "--output", output_path,
        ])
        ret = cmd_harmonize(args)
        assert ret == 1
        captured = capsys.readouterr()
        assert captured.err != ""


# ============================================================
# main
# ============================================================
class TestMain:
    def test_no_args(self):
        ret = main([])
        assert ret == 1

    def test_harmonize(self, tmp_output_dir):
        input_path = str(EVIDENCE_DIR / "sample_web_research.json")
        output_path = str(tmp_output_dir / "main_out.json")
        ret = main([
            "harmonize", "--ticker", "2780",
            "--input", input_path,
            "--output", output_path,
        ])
        assert ret == 0

    def test_invalid(self):
        with pytest.raises(SystemExit):
            main(["unknown_command"])

    def test_argv(self, tmp_output_dir):
        input_path = str(EVIDENCE_DIR / "sample_web_research.json")
        output_path = str(tmp_output_dir / "argv_out.json")
        test_args = [
            "harmonize", "--ticker", "2780",
            "--input", input_path,
            "--output", output_path,
        ]
        with patch("sys.argv", ["main.py"] + test_args):
            ret = main(None)
        assert ret == 0

    def test_help(self):
        result = _run_main("--help")
        assert result.returncode == 0
        assert "usage" in result.stdout.lower() or "harmonize" in result.stdout.lower()


# ============================================================
# CLI subprocess: エラー系
# ============================================================
class TestCliErrors:
    """subprocess レベルでの stderr / return-code 検証。"""

    def test_missing_input_file_subprocess(self, tmp_path):
        result = _run_main(
            "harmonize", "--ticker", "2780",
            "--input", str(tmp_path / "does_not_exist.json"),
            "--output", str(tmp_path / "out.json"),
        )
        assert result.returncode == 1
        assert result.stderr != ""

    def test_broken_json_subprocess(self, tmp_path):
        broken = tmp_path / "bad.json"
        broken.write_text("not valid json {{{", encoding="utf-8")
        result = _run_main(
            "harmonize", "--ticker", "2780",
            "--input", str(broken),
            "--output", str(tmp_path / "out.json"),
        )
        assert result.returncode == 1
        assert result.stderr != ""

    def test_missing_ticker_subprocess(self):
        result = _run_main("harmonize")
        assert result.returncode != 0

    def test_no_subcommand_subprocess(self):
        result = _run_main()
        assert result.returncode != 0

    def test_source_option_subprocess(self, tmp_path):
        input_path = str(EVIDENCE_DIR / "sample_web_research.json")
        output_path = str(tmp_path / "filtered.json")
        result = _run_main(
            "harmonize", "--ticker", "2780",
            "--source", "kabutan",
            "--input", input_path,
            "--output", output_path,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        meta = data["harmonization_metadata"]
        assert "kabutan" in meta["sources_used"]
        assert "yahoo" not in meta["sources_used"]
        assert "yahoo" in meta["sources_skipped"]

    def test_invalid_source_subprocess(self, tmp_path):
        input_path = str(EVIDENCE_DIR / "sample_web_research.json")
        result = _run_main(
            "harmonize", "--ticker", "2780",
            "--source", "invalid_source",
            "--input", input_path,
            "--output", str(tmp_path / "out.json"),
        )
        assert result.returncode == 1
        assert result.stderr != ""
