from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


def test_financial_reporter_generates_markdown_and_html() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "main.py"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        metrics_path = tmp_path / "metrics.json"
        output_md = tmp_path / "out.md"
        output_html = tmp_path / "out.html"

        payload = {
            "ticker": "7203",
            "company_name": "Sample Co.",
            "generated_at": "2026-02-11T00:00:00+00:00",
            "metrics_series": [
                {
                    "fiscal_year": 2024,
                    "revenue": 100,
                    "operating_income": 10,
                    "net_income": 7,
                    "roe_percent": 8.1,
                    "roa_percent": 3.2,
                    "operating_margin_percent": 10.0,
                    "equity_ratio_percent": 35.0,
                    "free_cash_flow": 4.5,
                }
            ],
        }
        metrics_path.write_text(json.dumps(payload), encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--ticker",
                "7203",
                "--metrics",
                str(metrics_path),
                "--output-md",
                str(output_md),
                "--output-html",
                str(output_html),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert output_md.exists()
        assert output_html.exists()
        assert "7203 Sample Co. Analysis Report" in output_md.read_text(encoding="utf-8")
        assert "<table>" in output_html.read_text(encoding="utf-8")
