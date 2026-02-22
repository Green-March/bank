"""disclosure-expansion スキルの基本テスト"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


def test_main_help():
    """main.py --help が正常終了すること"""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "main.py"), "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "disclosure-expansion" in result.stdout


def test_validate_subcommand_help():
    """validate サブコマンドの --help が正常終了すること"""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "main.py"), "validate", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "--ticker" in result.stdout


def test_status_subcommand_help():
    """status サブコマンドの --help が正常終了すること"""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "main.py"), "status", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "--ticker" in result.stdout


def test_reconcile_subcommand_help():
    """reconcile サブコマンドの --help が正常終了すること"""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "main.py"), "reconcile", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "--ticker" in result.stdout
    assert "--tolerance" in result.stdout


def test_run_subcommand_help():
    """run サブコマンドの --help が正常終了すること"""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "main.py"), "run", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "--ticker" in result.stdout
    assert "--edinet-code" in result.stdout
    assert "--dry-run" in result.stdout
    assert "--retry" in result.stdout
    assert "--on-fail" in result.stdout
    assert "--step" in result.stdout


def test_reconcile_help():
    """reconcile.py --help が正常終了すること"""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "reconcile.py"), "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "--ticker" in result.stdout
    assert "--tolerance" in result.stdout


# --- run サブコマンドのユニットテスト ---

from main import (
    parse_timeframe,
    expand_vars,
    topo_sort,
    resolve_step_skip,
    run_quality_gates,
    load_pipeline,
)


def test_parse_timeframe():
    """timeframe パース"""
    start, end = parse_timeframe("2021-01-01..2026-02-16")
    assert start == "2021-01-01"
    assert end == "2026-02-16"


def test_parse_timeframe_invalid():
    """不正な timeframe でエラー"""
    with pytest.raises(ValueError):
        parse_timeframe("2021-01-01")


def test_expand_vars():
    """変数展開"""
    template = "data/{ticker}/parsed/{ticker}_{edinet_code}.json"
    result = expand_vars(template, {"ticker": "2780", "edinet_code": "E03416"})
    assert result == "data/2780/parsed/2780_E03416.json"


def test_topo_sort_linear():
    """線形依存のトポロジカルソート"""
    steps = [
        {"id": "c", "depends_on": ["b"]},
        {"id": "a", "depends_on": []},
        {"id": "b", "depends_on": ["a"]},
    ]
    result = topo_sort(steps)
    ids = [s["id"] for s in result]
    assert ids == ["a", "b", "c"]


def test_topo_sort_diamond():
    """ダイアモンド依存のトポロジカルソート"""
    steps = [
        {"id": "d", "depends_on": ["b", "c"]},
        {"id": "b", "depends_on": ["a"]},
        {"id": "c", "depends_on": ["a"]},
        {"id": "a", "depends_on": []},
    ]
    result = topo_sort(steps)
    ids = [s["id"] for s in result]
    assert ids.index("a") < ids.index("b")
    assert ids.index("a") < ids.index("c")
    assert ids.index("b") < ids.index("d")
    assert ids.index("c") < ids.index("d")


def test_topo_sort_pipeline_dag():
    """実際のパイプラインDAGのトポロジカルソート"""
    steps = [
        {"id": "t0_schema", "depends_on": []},
        {"id": "t1r1_doc_list", "depends_on": ["t0_schema"]},
        {"id": "t2_pdf_collect", "depends_on": ["t1r1_doc_list"]},
        {"id": "t3_text_extract", "depends_on": ["t2_pdf_collect"]},
        {"id": "t5_structure", "depends_on": ["t3_text_extract"]},
        {"id": "t4_jquants", "depends_on": ["t0_schema"]},
        {"id": "t6_reconciliation", "depends_on": ["t4_jquants", "t5_structure"]},
    ]
    result = topo_sort(steps)
    ids = [s["id"] for s in result]
    # t0 must come first
    assert ids[0] == "t0_schema"
    # t6 must come last
    assert ids[-1] == "t6_reconciliation"
    # t4 depends only on t0, so can appear early
    assert ids.index("t0_schema") < ids.index("t4_jquants")
    assert ids.index("t4_jquants") < ids.index("t6_reconciliation")
    # EDINET chain order
    assert ids.index("t1r1_doc_list") < ids.index("t2_pdf_collect")
    assert ids.index("t2_pdf_collect") < ids.index("t3_text_extract")
    assert ids.index("t3_text_extract") < ids.index("t5_structure")
    assert ids.index("t5_structure") < ids.index("t6_reconciliation")


def test_resolve_step_skip():
    """ステップスキップ判定"""
    assert resolve_step_skip("t4_jquants", True, False) is not None
    assert resolve_step_skip("t6_reconciliation", False, True) is not None
    assert resolve_step_skip("t6_reconciliation", True, False) is not None  # T6 needs T4
    assert resolve_step_skip("t0_schema", False, False) is None
    assert resolve_step_skip("t1r1_doc_list", True, True) is None


def test_run_quality_gates_schema(tmp_path):
    """品質ゲート: スキーマバリデーション"""
    schema = {
        "properties": {
            "source": {}, "endpoint_or_doc_id": {},
            "fetched_at": {}, "period_end": {},
        }
    }
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(schema))

    gates = [{
        "id": "QG-T0",
        "step": "t0_schema",
        "check": "jsonschema_validate",
        "severity": "error",
        "params": {
            "schema_path": str(schema_file),
            "required_keys": ["source", "endpoint_or_doc_id", "fetched_at", "period_end"],
        },
    }]
    results = run_quality_gates("t0_schema", gates, {}, str(tmp_path))
    assert len(results) == 1
    assert results[0]["status"] == "PASS"


def test_run_quality_gates_schema_missing_key(tmp_path):
    """品質ゲート: 必須キー不足"""
    schema = {"properties": {"source": {}}}
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(schema))

    gates = [{
        "id": "QG-T0",
        "step": "t0_schema",
        "check": "jsonschema_validate",
        "severity": "error",
        "params": {
            "schema_path": str(schema_file),
            "required_keys": ["source", "endpoint_or_doc_id", "fetched_at", "period_end"],
        },
    }]
    results = run_quality_gates("t0_schema", gates, {}, str(tmp_path))
    assert results[0]["status"] == "FAIL"


def test_run_dry_run(tmp_path):
    """run --dry-run が正常終了し、ログを出力すること"""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "main.py"), "run",
         "--ticker", "9999", "--edinet-code", "E99999",
         "--timeframe", "2025-01-01..2025-12-31",
         "--dry-run",
         "--log-dir", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "DRY RUN" in result.stdout
    # Check log file was created
    log_files = list(tmp_path.glob("run_*.json"))
    assert len(log_files) == 1
    log = json.loads(log_files[0].read_text())
    assert log["dry_run"] is True
    assert len(log["steps"]) > 0
    assert all(s["status"] == "DRY_RUN" for s in log["steps"])


def test_load_pipeline():
    """pipeline.yaml が読み込み可能で必須フィールドを含むこと"""
    pipeline = load_pipeline()
    steps = pipeline.get("pipeline", {}).get("steps", [])
    assert len(steps) > 0
    step_ids = {s["id"] for s in steps}
    assert "t0_schema" in step_ids
    assert "t6_reconciliation" in step_ids


# --- S3R1: 回帰テスト ---

from main import load_gates, _resolve_json_spec, _resolve_nested


def test_no_unsupported_check_types():
    """quality_gates.yaml に未対応の check type が存在しないこと"""
    supported = {
        "jsonschema_validate", "manifest_check", "count_match",
        "record_check", "field_check", "custom_script",
        "reconciliation_check", "manual",
    }
    gates = load_gates()
    for gate in gates:
        check = gate.get("check", "")
        assert check in supported, (
            f"Unsupported check type '{check}' in gate {gate['id']}"
        )


def test_gate_error_fail_marks_step_failed(tmp_path):
    """severity=error の gate が FAIL した場合、step が FAILED になること"""
    # Create a schema file missing required keys
    schema = {"properties": {"source": {}}}
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(schema))

    gates = [{
        "id": "QG-TEST",
        "step": "test_step",
        "check": "jsonschema_validate",
        "severity": "error",
        "params": {
            "schema_path": str(schema_file),
            "required_keys": ["source", "endpoint_or_doc_id", "fetched_at", "period_end"],
        },
    }]
    results = run_quality_gates("test_step", gates, {}, str(tmp_path))
    assert results[0]["status"] == "FAIL"
    assert results[0]["severity"] == "error"


def test_gate_warning_does_not_fail_step(tmp_path):
    """severity=warning の gate が FAIL しても step は FAILED にならないこと"""
    schema = {"properties": {"source": {}}}
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(schema))

    gates = [{
        "id": "QG-WARN",
        "step": "test_step",
        "check": "jsonschema_validate",
        "severity": "warning",
        "params": {
            "schema_path": str(schema_file),
            "required_keys": ["source", "missing_key"],
        },
    }]
    results = run_quality_gates("test_step", gates, {}, str(tmp_path))
    assert results[0]["status"] == "FAIL"
    assert results[0]["severity"] == "warning"


def test_unknown_check_type_returns_fail():
    """未知の check type は FAIL を返すこと（SKIPではない）"""
    gates = [{
        "id": "QG-UNKNOWN",
        "step": "test_step",
        "check": "nonexistent_check",
        "severity": "error",
        "params": {},
    }]
    results = run_quality_gates("test_step", gates, {}, ".")
    assert results[0]["status"] == "FAIL"
    assert "Unknown check type" in results[0]["detail"]


def test_count_match_pass(tmp_path):
    """count_match: 値が一致する場合 PASS"""
    f1 = tmp_path / "a.json"
    f2 = tmp_path / "b.json"
    f1.write_text(json.dumps({"document_count": 12}))
    f2.write_text(json.dumps({"matched_doc_count": 12}))

    gates = [{
        "id": "QG-CM",
        "step": "s",
        "check": "count_match",
        "severity": "error",
        "params": {
            "actual": f"{f1}::document_count",
            "expected": f"{f2}::matched_doc_count",
        },
    }]
    results = run_quality_gates("s", gates, {}, str(tmp_path))
    assert results[0]["status"] == "PASS"


def test_count_match_fail(tmp_path):
    """count_match: 値が不一致の場合 FAIL"""
    f1 = tmp_path / "a.json"
    f2 = tmp_path / "b.json"
    f1.write_text(json.dumps({"document_count": 10}))
    f2.write_text(json.dumps({"matched_doc_count": 12}))

    gates = [{
        "id": "QG-CM",
        "step": "s",
        "check": "count_match",
        "severity": "error",
        "params": {
            "actual": f"{f1}::document_count",
            "expected": f"{f2}::matched_doc_count",
        },
    }]
    results = run_quality_gates("s", gates, {}, str(tmp_path))
    assert results[0]["status"] == "FAIL"


def test_field_check_pass(tmp_path):
    """field_check: フィルタ後のレコードに非null値がある場合 PASS"""
    data = {
        "records": [
            {"type_of_current_period": "FY", "actuals": {"operating_cf": 100}},
            {"type_of_current_period": "Q2", "actuals": {"operating_cf": None}},
        ]
    }
    f = tmp_path / "data.json"
    f.write_text(json.dumps(data))

    gates = [{
        "id": "QG-FC",
        "step": "s",
        "check": "field_check",
        "severity": "warning",
        "params": {
            "data_path": str(f),
            "records_key": "records",
            "filter": "type_of_current_period == 'FY'",
            "assert_field_path": "actuals.operating_cf",
            "assert_field_not_null": True,
        },
    }]
    results = run_quality_gates("s", gates, {}, str(tmp_path))
    assert results[0]["status"] == "PASS"


def test_field_check_fail(tmp_path):
    """field_check: フィルタ後のレコードに非null値がない場合 FAIL"""
    data = {
        "records": [
            {"type_of_current_period": "FY", "actuals": {"operating_cf": None}},
        ]
    }
    f = tmp_path / "data.json"
    f.write_text(json.dumps(data))

    gates = [{
        "id": "QG-FC",
        "step": "s",
        "check": "field_check",
        "severity": "warning",
        "params": {
            "data_path": str(f),
            "records_key": "records",
            "filter": "type_of_current_period == 'FY'",
            "assert_field_path": "actuals.operating_cf",
            "assert_field_not_null": True,
        },
    }]
    results = run_quality_gates("s", gates, {}, str(tmp_path))
    assert results[0]["status"] == "FAIL"


def test_custom_script_pass():
    """custom_script: 正常終了スクリプトは PASS"""
    gates = [{
        "id": "QG-CS",
        "step": "s",
        "check": "custom_script",
        "severity": "error",
        "params": {"script": "print('OK')"},
    }]
    results = run_quality_gates("s", gates, {}, ".")
    assert results[0]["status"] == "PASS"


def test_custom_script_fail():
    """custom_script: AssertionError で FAIL"""
    gates = [{
        "id": "QG-CS",
        "step": "s",
        "check": "custom_script",
        "severity": "error",
        "params": {"script": "raise AssertionError('test failure')"},
    }]
    results = run_quality_gates("s", gates, {}, ".")
    assert results[0]["status"] == "FAIL"
    assert "test failure" in results[0]["detail"]


def test_resolve_nested():
    """_resolve_nested でドットパス解決"""
    obj = {"actuals": {"operating_cf": 42, "revenue": None}}
    assert _resolve_nested(obj, "actuals.operating_cf") == 42
    assert _resolve_nested(obj, "actuals.revenue") is None
    assert _resolve_nested(obj, "actuals.missing") is None
    assert _resolve_nested(obj, "nonexistent.path") is None


def test_resolve_json_spec(tmp_path):
    """_resolve_json_spec でファイルパス::キー解決"""
    f = tmp_path / "test.json"
    f.write_text(json.dumps({"summary": {"count": 5}}))
    val, err = _resolve_json_spec(f"{f}::summary.count")
    assert val == 5
    assert err is None


def test_resolve_json_spec_missing_file():
    """_resolve_json_spec: 存在しないファイル"""
    val, err = _resolve_json_spec("/nonexistent/file.json::key")
    assert val is None
    assert "not found" in err.lower()


def test_run_gate_error_exit_code(tmp_path):
    """run で error gate が失敗すると exit=1 になること（E2E回帰テスト）"""
    # Create a minimal pipeline with one step that succeeds
    # but has a gate that fails
    pipeline = {
        "pipeline": {
            "steps": [
                {
                    "id": "step1",
                    "description": "test step",
                    "command": "echo ok",
                    "depends_on": [],
                    "gates": None,
                }
            ],
            "default_vars": {},
        }
    }
    # Create a gate that will fail
    gates = {
        "gates": [
            {
                "id": "QG-FAIL",
                "step": "step1",
                "check": "custom_script",
                "severity": "error",
                "params": {"script": "import sys; sys.exit(1)"},
            }
        ]
    }

    pipe_file = tmp_path / "references" / "pipeline.yaml"
    gate_file = tmp_path / "references" / "quality_gates.yaml"
    pipe_file.parent.mkdir(parents=True, exist_ok=True)

    import yaml
    pipe_file.write_text(yaml.dump(pipeline))
    gate_file.write_text(yaml.dump(gates))

    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"

    env = os.environ.copy()
    env["EDINET_API_KEY"] = "dummy"
    env["JQUANTS_REFRESH_TOKEN"] = "dummy"
    result = subprocess.run(
        [sys.executable, "-c",
         f"""
import sys, os
sys.path.insert(0, '{scripts_dir}')
os.chdir('{tmp_path}')
import main as m
m.PIPELINE_DEF = m.Path('{pipe_file}')
m.QUALITY_GATES = m.Path('{gate_file}')
sys.argv = ['main.py', 'run', '--ticker', '9999', '--edinet-code', 'E99999',
            '--timeframe', '2025-01-01..2025-12-31',
            '--log-dir', '{tmp_path}']
m.main()
"""],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 1, f"Expected exit=1 but got {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    log_files = list(tmp_path.glob("run_*.json"))
    assert len(log_files) == 1
    log = json.loads(log_files[0].read_text())
    assert log["summary"]["failed"] == 1
    assert log["steps"][0]["status"] == "FAILED"


def test_run_on_fail_skip_continues(tmp_path):
    """on-fail=skip で gate 失敗後、下流ステップがスキップされること"""
    pipeline = {
        "pipeline": {
            "steps": [
                {
                    "id": "step1",
                    "description": "failing step",
                    "command": "echo ok",
                    "depends_on": [],
                },
                {
                    "id": "step2",
                    "description": "downstream step",
                    "command": "echo downstream",
                    "depends_on": ["step1"],
                },
            ],
            "default_vars": {},
        }
    }
    gates = {
        "gates": [
            {
                "id": "QG-FAIL",
                "step": "step1",
                "check": "custom_script",
                "severity": "error",
                "params": {"script": "import sys; sys.exit(1)"},
            }
        ]
    }

    pipe_file = tmp_path / "references" / "pipeline.yaml"
    gate_file = tmp_path / "references" / "quality_gates.yaml"
    pipe_file.parent.mkdir(parents=True, exist_ok=True)

    import yaml
    pipe_file.write_text(yaml.dump(pipeline))
    gate_file.write_text(yaml.dump(gates))

    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"

    env = os.environ.copy()
    env["EDINET_API_KEY"] = "dummy"
    env["JQUANTS_REFRESH_TOKEN"] = "dummy"
    result = subprocess.run(
        [sys.executable, "-c",
         f"""
import sys, os
sys.path.insert(0, '{scripts_dir}')
os.chdir('{tmp_path}')
import main as m
m.PIPELINE_DEF = m.Path('{pipe_file}')
m.QUALITY_GATES = m.Path('{gate_file}')
sys.argv = ['main.py', 'run', '--ticker', '9999', '--edinet-code', 'E99999',
            '--timeframe', '2025-01-01..2025-12-31',
            '--on-fail', 'skip',
            '--log-dir', '{tmp_path}']
m.main()
"""],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 1, f"Expected exit=1 but got {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    log_files = list(tmp_path.glob("run_*.json"))
    assert len(log_files) == 1, f"Expected 1 log file, got {len(log_files)}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    log = json.loads(log_files[0].read_text())
    statuses = {s["step_id"]: s["status"] for s in log["steps"]}
    assert statuses["step1"] == "FAILED"
    assert statuses["step2"] == "SKIPPED"
