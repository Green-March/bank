#!/usr/bin/env python3
"""
disclosure-expansion: エンドツーエンド開示データ拡張スキル

EDINET四半期/半期報告書とJ-Quants決算データを収集・構造化・突合し、
銘柄の開示データを時系列で拡張する。

サブコマンド:
  validate  — 入力・環境変数・スキーマの事前検証
  status    — 既存データの収集状況確認
  reconcile — T6突合QAの実行（reconcile.py のラッパー）
  run       — パイプラインDAG依存順実行

Usage:
    python3 skills/disclosure-expansion/scripts/main.py validate \
        --ticker 2780 --edinet-code E03416
    python3 skills/disclosure-expansion/scripts/main.py status --ticker 2780
    python3 skills/disclosure-expansion/scripts/main.py reconcile \
        --ticker 2780
    python3 skills/disclosure-expansion/scripts/main.py run \
        --ticker 2780 --edinet-code E03416 \
        --timeframe "2021-01-01..2026-02-16"
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    print(
        "ERROR: pyyaml is required for disclosure-expansion.\n"
        "Install with: pip install pyyaml",
        file=sys.stderr,
    )
    sys.exit(1)

SKILL_DIR = Path(__file__).resolve().parent.parent
PIPELINE_DEF = SKILL_DIR / "references" / "pipeline.yaml"
QUALITY_GATES = SKILL_DIR / "references" / "quality_gates.yaml"
RECONCILE_SCRIPT = SKILL_DIR / "scripts" / "reconcile.py"


def parse_timeframe(timeframe: str) -> tuple[str, str]:
    """Parse 'YYYY-MM-DD..YYYY-MM-DD' into (start_date, end_date)."""
    parts = timeframe.split("..")
    if len(parts) != 2:
        raise ValueError(f"Invalid timeframe format: {timeframe}. Expected YYYY-MM-DD..YYYY-MM-DD")
    return parts[0].strip(), parts[1].strip()


def check_environment(skip_jquants: bool = False) -> list[str]:
    """Validate required environment variables. Returns list of errors."""
    errors = []
    if not os.environ.get("EDINET_API_KEY") and not os.environ.get("EDINET_SUBSCRIPTION_KEY"):
        errors.append("EDINET_API_KEY (or EDINET_SUBSCRIPTION_KEY) is not set")
    if not skip_jquants:
        if not os.environ.get("JQUANTS_REFRESH_TOKEN"):
            errors.append("JQUANTS_REFRESH_TOKEN is not set (use --skip-jquants to skip T4)")
    return errors


SCHEMA_TEMPLATE = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "bank-common-metadata-v1",
    "title": "BANK Common Data Metadata",
    "description": "T2/T3/T5タスク共通のデータ来歴（provenance）メタデータスキーマ。",
    "type": "object",
    "required": ["source", "endpoint_or_doc_id", "fetched_at", "period_end"],
    "properties": {
        "source": {
            "type": "string",
            "enum": ["edinet", "jquants", "jpx", "pdf", "manual"],
            "description": "データ取得元識別子",
        },
        "endpoint_or_doc_id": {
            "type": "string",
            "minLength": 1,
            "description": "データ特定子（APIエンドポイント/docID/ファイル名）",
        },
        "fetched_at": {
            "type": "string",
            "format": "date-time",
            "description": "データ取得時刻 (ISO 8601)",
        },
        "period_end": {
            "type": "string",
            "format": "date",
            "description": "対象期末日 (YYYY-MM-DD)",
        },
        "ticker": {
            "type": "string",
            "pattern": "^[0-9]{4}$",
            "description": "(任意) 銘柄コード4桁",
        },
        "period_start": {
            "type": ["string", "null"],
            "format": "date",
            "description": "(任意) 対象期首日",
        },
        "raw_file_path": {
            "type": ["string", "null"],
            "description": "(任意) 生データのローカル保存パス",
        },
    },
    "additionalProperties": True,
}


def check_schema(ticker: str, data_path: str, auto_create: bool = False) -> bool:
    """QG-T0: Validate T0 common metadata schema exists and has required keys.

    If auto_create=True and schema does not exist, generate from built-in template.
    """
    schema_path = Path(data_path) / ticker / "schema" / "common-metadata.schema.json"
    if not schema_path.exists():
        if auto_create:
            schema_path.parent.mkdir(parents=True, exist_ok=True)
            schema_path.write_text(json.dumps(SCHEMA_TEMPLATE, ensure_ascii=False, indent=2))
            print(f"  CREATED: T0 schema generated at {schema_path}")
        else:
            print(f"  WARN: T0 schema not found at {schema_path}")
            return False
    try:
        schema = json.loads(schema_path.read_text())
        required = ["source", "endpoint_or_doc_id", "fetched_at", "period_end"]
        props = schema.get("properties", {})
        missing = [k for k in required if k not in props]
        if missing:
            print(f"  FAIL: T0 schema missing keys: {missing}")
            return False
        print(f"  PASS: T0 schema OK ({schema_path})")
        return True
    except (json.JSONDecodeError, KeyError) as e:
        print(f"  FAIL: T0 schema parse error: {e}")
        return False


def load_pipeline() -> dict:
    """Load pipeline definition from references/pipeline.yaml."""
    if not PIPELINE_DEF.exists():
        raise FileNotFoundError(f"Pipeline definition not found: {PIPELINE_DEF}")
    return yaml.safe_load(PIPELINE_DEF.read_text())


def load_gates() -> list[dict]:
    """Load quality gates from references/quality_gates.yaml."""
    if not QUALITY_GATES.exists():
        return []
    data = yaml.safe_load(QUALITY_GATES.read_text())
    return data.get("gates", [])


def topo_sort(steps: list[dict]) -> list[dict]:
    """Topological sort of pipeline steps based on depends_on."""
    step_map = {s["id"]: s for s in steps}
    visited: set[str] = set()
    order: list[str] = []

    def visit(step_id: str):
        if step_id in visited:
            return
        visited.add(step_id)
        step = step_map[step_id]
        for dep in step.get("depends_on", []) or []:
            if dep in step_map:
                visit(dep)
        order.append(step_id)

    for s in steps:
        visit(s["id"])
    return [step_map[sid] for sid in order]


def expand_vars(template: str, variables: dict) -> str:
    """Expand {var} placeholders in a command template."""
    result = template
    for key, val in variables.items():
        result = result.replace("{" + key + "}", str(val))
    return result


def resolve_step_skip(step_id: str, skip_jquants: bool, skip_qa: bool) -> str | None:
    """Return skip reason if a step should be skipped, else None."""
    if skip_jquants and step_id == "t4_jquants":
        return "skip_jquants=true"
    if skip_qa and step_id == "t6_reconciliation":
        return "skip_qa=true"
    # If skipping jquants, also skip reconciliation (needs T4 data)
    if skip_jquants and step_id == "t6_reconciliation":
        return "skip_jquants=true (T6 requires T4)"
    return None


def _resolve_json_spec(spec: str) -> tuple:
    """Resolve 'path::key' spec to (value, error_string).

    Supports nested keys via dot notation (e.g., 'file.json::summary.count').
    """
    parts = spec.split("::")
    file_path = Path(parts[0])
    key = parts[1] if len(parts) > 1 else None
    if not file_path.exists():
        return None, f"File not found: {file_path}"
    data = json.loads(file_path.read_text())
    if key:
        val = data
        for k in key.split("."):
            if isinstance(val, dict):
                val = val.get(k)
            else:
                return None, f"Cannot traverse key '{k}' in non-dict"
        return val, None
    return data, None


def _resolve_nested(obj: dict, dotpath: str):
    """Resolve a dot-separated path like 'actuals.operating_cf' in a dict."""
    val = obj
    for part in dotpath.split("."):
        if isinstance(val, dict):
            val = val.get(part)
        else:
            return None
    return val


def run_quality_gates(step_id: str, gates: list[dict], variables: dict,
                      data_path: str) -> list[dict]:
    """Run quality gates for a given step. Returns list of gate results."""
    results = []
    for gate in gates:
        if gate.get("step") != step_id and gate.get("step") != "all":
            continue

        gate_id = gate["id"]
        check_type = gate.get("check", "")
        severity = gate.get("severity", "error")
        params = gate.get("params", {})
        result = {"gate_id": gate_id, "severity": severity}

        try:
            if check_type == "jsonschema_validate":
                schema_rel = expand_vars(params.get("schema_path", ""), variables)
                schema_path = Path(schema_rel)
                if schema_path.exists():
                    schema = json.loads(schema_path.read_text())
                    req_keys = params.get("required_keys", [])
                    props = schema.get("properties", {})
                    missing = [k for k in req_keys if k not in props]
                    if missing:
                        result["status"] = "FAIL"
                        result["detail"] = f"Missing keys: {missing}"
                    else:
                        result["status"] = "PASS"
                else:
                    result["status"] = "FAIL"
                    result["detail"] = f"Schema not found: {schema_path}"

            elif check_type == "manifest_check":
                manifest_rel = expand_vars(params.get("manifest_path", ""), variables)
                manifest_path = Path(manifest_rel)
                if manifest_path.exists():
                    manifest = json.loads(manifest_path.read_text())
                    ds = manifest.get("download_summary", {})
                    if ds.get("failed", 0) == 0:
                        result["status"] = "PASS"
                    else:
                        result["status"] = "FAIL"
                        result["detail"] = f"failed={ds.get('failed')}"
                else:
                    result["status"] = "SKIP"
                    result["detail"] = f"Manifest not found: {manifest_path}"

            elif check_type == "count_match":
                actual_spec = expand_vars(params.get("actual", ""), variables)
                expected_spec = expand_vars(params.get("expected", ""), variables)
                actual_val, err1 = _resolve_json_spec(actual_spec)
                expected_val, err2 = _resolve_json_spec(expected_spec)
                if err1 or err2:
                    result["status"] = "SKIP"
                    result["detail"] = err1 or err2
                elif actual_val == expected_val:
                    result["status"] = "PASS"
                else:
                    result["status"] = "FAIL"
                    result["detail"] = f"actual={actual_val} != expected={expected_val}"

            elif check_type == "record_check":
                data_rel = expand_vars(params.get("data_path", ""), variables)
                data_file = Path(data_rel)
                if data_file.exists():
                    data = json.loads(data_file.read_text())
                    recs = data if isinstance(data, list) else data.get(
                        params.get("records_key", "records"), [])
                    if len(recs) > 0:
                        result["status"] = "PASS"
                    else:
                        result["status"] = "FAIL"
                        result["detail"] = "record_count == 0"
                else:
                    result["status"] = "SKIP"
                    result["detail"] = f"Data not found: {data_file}"

            elif check_type == "field_check":
                data_rel = expand_vars(params.get("data_path", ""), variables)
                data_file = Path(data_rel)
                if data_file.exists():
                    data = json.loads(data_file.read_text())
                    recs = data if isinstance(data, list) else data.get(
                        params.get("records_key", "records"), [])
                    # Apply filter (e.g., "type_of_current_period == 'FY'")
                    filter_str = params.get("filter", "")
                    if filter_str and "==" in filter_str:
                        f_parts = filter_str.split("==")
                        f_key = f_parts[0].strip()
                        f_val = f_parts[1].strip().strip("'\"")
                        recs = [r for r in recs if str(r.get(f_key)) == f_val]
                    # Check field
                    field_path = params.get("assert_field_path", "")
                    not_null = params.get("assert_field_not_null", False)
                    if not_null and field_path:
                        found = any(
                            _resolve_nested(r, field_path) is not None
                            for r in recs
                        )
                        if found:
                            result["status"] = "PASS"
                        else:
                            result["status"] = "FAIL"
                            result["detail"] = f"No record with non-null {field_path}"
                    else:
                        result["status"] = "PASS"
                else:
                    result["status"] = "SKIP"
                    result["detail"] = f"Data not found: {data_file}"

            elif check_type == "custom_script":
                script = params.get("script", "")
                script = expand_vars(script, variables)
                proc = subprocess.run(
                    [sys.executable, "-c", script],
                    capture_output=True, text=True,
                )
                if proc.returncode == 0:
                    result["status"] = "PASS"
                else:
                    err_msg = proc.stderr.strip().split("\n")[-1] if proc.stderr.strip() else "script failed"
                    result["status"] = "FAIL"
                    result["detail"] = err_msg

            elif check_type == "reconciliation_check":
                data_rel = expand_vars(params.get("data_path", ""), variables)
                data_file = Path(data_rel)
                if data_file.exists():
                    data = json.loads(data_file.read_text())
                    s = data.get("summary", {})
                    if s.get("invalid_comparison", 0) == 0:
                        result["status"] = "PASS"
                    else:
                        result["status"] = "FAIL"
                        result["detail"] = f"invalid_comparison={s.get('invalid_comparison')}"
                else:
                    result["status"] = "SKIP"
                    result["detail"] = f"Data not found: {data_file}"

            elif check_type == "manual":
                result["status"] = "SKIP"
                result["detail"] = "Manual check required"

            else:
                result["status"] = "FAIL"
                result["detail"] = f"Unknown check type: {check_type}"

        except Exception as e:
            result["status"] = "ERROR"
            result["detail"] = str(e)

        results.append(result)
    return results


def cmd_run(args):
    """Execute the pipeline in DAG dependency order."""
    data_path = os.environ.get("DATA_PATH", "./data")
    start_date, end_date = parse_timeframe(args.timeframe)
    ticker = args.ticker
    edinet_code = args.edinet_code

    variables = {
        "ticker": ticker,
        "edinet_code": edinet_code,
        "start_date": start_date,
        "end_date": end_date,
        "security_code": args.security_code or f"{ticker}0",
        "report_keyword": args.report_keyword,
    }

    # Setup log directory
    log_dir = Path(args.log_dir) if args.log_dir else Path(f"projects/{ticker}/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"run_{run_ts}.json"

    print(f"=== disclosure-expansion: run ===")
    print(f"ticker: {ticker}")
    print(f"edinet_code: {edinet_code}")
    print(f"timeframe: {start_date} .. {end_date}")
    print(f"security_code: {variables['security_code']}")
    print(f"log: {log_file}")
    if args.dry_run:
        print("mode: DRY RUN (commands will not be executed)")
    print()

    # Validate environment first
    env_errors = check_environment(args.skip_jquants)
    if env_errors and not args.dry_run:
        print("Environment validation FAILED:", file=sys.stderr)
        for e in env_errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    # Load pipeline and gates
    pipeline = load_pipeline()
    steps = pipeline.get("pipeline", {}).get("steps", [])
    gates = load_gates()

    # Apply default vars from pipeline
    default_vars = pipeline.get("pipeline", {}).get("default_vars", {})
    for k, v in default_vars.items():
        if k not in variables:
            variables[k] = expand_vars(str(v), variables)

    # Topological sort
    sorted_steps = topo_sort(steps)

    # Filter steps if --step is specified
    if args.step:
        target_ids = set(args.step)
        # Include all dependencies of requested steps
        step_map = {s["id"]: s for s in steps}
        needed: set[str] = set()

        def collect_deps(sid: str):
            if sid in needed:
                return
            needed.add(sid)
            for dep in (step_map.get(sid, {}).get("depends_on") or []):
                collect_deps(dep)

        for sid in target_ids:
            collect_deps(sid)
        sorted_steps = [s for s in sorted_steps if s["id"] in needed]

    # Execute pipeline
    run_log: dict = {
        "run_started": datetime.now().isoformat(),
        "variables": variables,
        "dry_run": args.dry_run,
        "steps": [],
    }

    failed_steps: set[str] = set()
    skipped_steps: set[str] = set()

    for step in sorted_steps:
        step_id = step["id"]
        description = step.get("description", step_id)
        depends_on = step.get("depends_on") or []

        step_log: dict = {
            "step_id": step_id,
            "description": description,
        }

        # Check if dependencies failed
        blocked_by = [d for d in depends_on if d in failed_steps or d in skipped_steps]
        if blocked_by:
            print(f"[SKIP] {step_id}: blocked by {blocked_by}")
            step_log["status"] = "SKIPPED"
            step_log["reason"] = f"blocked by {blocked_by}"
            skipped_steps.add(step_id)
            run_log["steps"].append(step_log)
            continue

        # Check skip flags
        skip_reason = resolve_step_skip(step_id, args.skip_jquants, args.skip_qa)
        if skip_reason:
            print(f"[SKIP] {step_id}: {skip_reason}")
            step_log["status"] = "SKIPPED"
            step_log["reason"] = skip_reason
            skipped_steps.add(step_id)
            run_log["steps"].append(step_log)
            continue

        # Built-in handler for t0_schema (avoid inline Python indentation issues)
        if step_id == "t0_schema":
            print(f"[RUN]  {step_id}: {description}")
            ok = check_schema(ticker, data_path, auto_create=True)
            if ok:
                step_log["status"] = "SUCCESS"
                step_log["attempts"] = 1
                print(f"       -> SUCCESS")
            else:
                step_log["status"] = "FAILED"
                step_log["attempts"] = 1
                print(f"       -> FAILED")
                failed_steps.add(step_id)
                if args.on_fail == "abort":
                    print(f"       ABORT: pipeline halted at {step_id}")
                    run_log["steps"].append(step_log)
                    break
            run_log["steps"].append(step_log)
            continue

        # Built-in handler for t5_structure (validate T3 output exists)
        if step_id == "t5_structure":
            print(f"[RUN]  {step_id}: {description}")
            financials = Path(data_path) / ticker / "processed" / "financials.json"
            if financials.exists():
                try:
                    fdata = json.loads(financials.read_text())
                    n = fdata.get("document_count", 0)
                    print(f"       T5: financials.json OK — {n} documents structured")
                    step_log["status"] = "SUCCESS"
                    step_log["attempts"] = 1
                    print(f"       -> SUCCESS")
                except (json.JSONDecodeError, KeyError) as e:
                    step_log["status"] = "FAILED"
                    step_log["attempts"] = 1
                    print(f"       T5: financials.json parse error: {e}")
                    print(f"       -> FAILED")
                    failed_steps.add(step_id)
                    if args.on_fail == "abort":
                        print(f"       ABORT: pipeline halted at {step_id}")
                        run_log["steps"].append(step_log)
                        break
            else:
                step_log["status"] = "FAILED"
                step_log["attempts"] = 1
                print(f"       T5: financials.json not found (T3 must run first)")
                print(f"       -> FAILED")
                failed_steps.add(step_id)
                if args.on_fail == "abort":
                    print(f"       ABORT: pipeline halted at {step_id}")
                    run_log["steps"].append(step_log)
                    break
            run_log["steps"].append(step_log)
            continue

        # Expand command
        raw_cmd = step.get("command", "").strip()
        cmd = expand_vars(raw_cmd, variables)

        print(f"[RUN]  {step_id}: {description}")

        if args.dry_run:
            print(f"       cmd: {cmd}")
            step_log["status"] = "DRY_RUN"
            step_log["command"] = cmd
            run_log["steps"].append(step_log)
            continue

        # Execute with retry
        step_log["command"] = cmd
        attempt = 0
        max_retries = args.retry
        success = False

        while attempt <= max_retries:
            attempt += 1
            if attempt > 1:
                print(f"       retry {attempt - 1}/{max_retries}...")

            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
            )

            if result.returncode == 0:
                success = True
                step_log["status"] = "SUCCESS"
                step_log["attempts"] = attempt
                if result.stdout.strip():
                    # Keep last 20 lines of stdout
                    lines = result.stdout.strip().split("\n")
                    step_log["stdout_tail"] = "\n".join(lines[-20:])
                print(f"       -> SUCCESS (attempt {attempt})")
                break
            else:
                if attempt > max_retries:
                    step_log["status"] = "FAILED"
                    step_log["attempts"] = attempt
                    step_log["returncode"] = result.returncode
                    if result.stderr.strip():
                        lines = result.stderr.strip().split("\n")
                        step_log["stderr_tail"] = "\n".join(lines[-20:])

        if not success:
            print(f"       -> FAILED (rc={result.returncode})")
            failed_steps.add(step_id)
            run_log["steps"].append(step_log)
            if args.on_fail == "abort":
                print(f"       ABORT: pipeline halted at {step_id}")
                break
            else:
                print(f"       SKIP: continuing pipeline (downstream will be skipped)")
                continue
        else:
            # Run quality gates for this step
            gate_results = run_quality_gates(step_id, gates, variables, data_path)
            if gate_results:
                step_log["gates"] = gate_results
                gate_failed = False
                for gr in gate_results:
                    gs = gr["status"]
                    gid = gr["gate_id"]
                    if gs in ("FAIL", "ERROR") and gr["severity"] == "error":
                        print(f"       GATE {gid}: FAIL ({gr.get('detail', '')})")
                        gate_failed = True
                    elif gs in ("FAIL", "ERROR"):
                        print(f"       GATE {gid}: WARN ({gr.get('detail', '')})")
                    elif gs == "PASS":
                        print(f"       GATE {gid}: PASS")

                if gate_failed:
                    step_log["status"] = "FAILED"
                    step_log["failure_reason"] = "quality_gate_error"
                    failed_steps.add(step_id)
                    run_log["steps"].append(step_log)
                    if args.on_fail == "abort":
                        print(f"       ABORT: pipeline halted at {step_id} (gate failure)")
                        break
                    else:
                        print(f"       SKIP: gate failure, downstream will be skipped")
                        continue

        run_log["steps"].append(step_log)

    # Summary
    run_log["run_finished"] = datetime.now().isoformat()
    succeeded = sum(1 for s in run_log["steps"] if s.get("status") == "SUCCESS")
    failed = sum(1 for s in run_log["steps"] if s.get("status") == "FAILED")
    skipped = sum(1 for s in run_log["steps"] if s.get("status") == "SKIPPED")
    dry = sum(1 for s in run_log["steps"] if s.get("status") == "DRY_RUN")

    run_log["summary"] = {
        "total": len(run_log["steps"]),
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
        "dry_run": dry,
    }

    print()
    print(f"=== Pipeline complete ===")
    print(f"  succeeded: {succeeded}, failed: {failed}, skipped: {skipped}"
          + (f", dry_run: {dry}" if dry else ""))

    # Write log
    log_file.write_text(json.dumps(run_log, ensure_ascii=False, indent=2))
    print(f"  log: {log_file}")

    if failed > 0:
        sys.exit(1)


def cmd_validate(args):
    """Validate inputs and environment without executing."""
    print("=== disclosure-expansion: validate ===")
    print(f"ticker: {args.ticker}")
    print(f"edinet_code: {args.edinet_code}")
    print()

    errors = []

    # Environment
    env_errors = check_environment(args.skip_jquants)
    errors.extend(env_errors)

    # Timeframe
    try:
        start_date, end_date = parse_timeframe(args.timeframe)
        print(f"  timeframe: {start_date} to {end_date}")
    except ValueError as e:
        errors.append(str(e))

    # Schema
    data_path = os.environ.get("DATA_PATH", "./data")
    check_schema(args.ticker, data_path)

    # Pipeline definition
    if PIPELINE_DEF.exists():
        print(f"  PASS: Pipeline definition found ({PIPELINE_DEF})")
    else:
        errors.append(f"Pipeline definition not found: {PIPELINE_DEF}")

    # Quality gates
    if QUALITY_GATES.exists():
        print(f"  PASS: Quality gates found ({QUALITY_GATES})")
    else:
        errors.append(f"Quality gates not found: {QUALITY_GATES}")

    # Check existing data
    ticker_dir = Path(data_path) / args.ticker
    if ticker_dir.exists():
        structured = ticker_dir / "processed" / "shihanki_structured.json"
        jquants = ticker_dir / "processed" / "jquants_fins_statements.json"
        if structured.exists():
            print(f"  PASS: T5 structured data found ({structured})")
        if jquants.exists():
            print(f"  PASS: T4 J-Quants data found ({jquants})")

    print()
    if errors:
        print("Validation FAILED:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("Validation PASSED")


def cmd_status(args):
    """Show current data status for a ticker."""
    print("=== disclosure-expansion: status ===")
    print(f"ticker: {args.ticker}")
    print()

    data_path = os.environ.get("DATA_PATH", "./data")
    ticker_dir = Path(data_path) / args.ticker

    if not ticker_dir.exists():
        print(f"  No data directory found: {ticker_dir}")
        return

    checks = [
        ("T0 Schema", ticker_dir / "schema" / "common-metadata.schema.json"),
        ("T1R1 Doc list", ticker_dir / "raw" / "edinet" / "kessan_tanshin"),
        ("T2 PDFs", ticker_dir / "raw" / "edinet" / "shihanki_hokokusho" / "manifest.json"),
        ("T3 Text", ticker_dir / "processed" / "kessan_tanshin_text.json"),
        ("T4 J-Quants", ticker_dir / "processed" / "jquants_fins_statements.json"),
        ("T5 Structured", ticker_dir / "processed" / "shihanki_structured.json"),
        ("T6 QA", ticker_dir / "qa" / "source_reconciliation.json"),
    ]

    for label, path in checks:
        if path.exists():
            if path.is_dir():
                count = len(list(path.glob("*")))
                print(f"  [OK] {label}: {path} ({count} files)")
            else:
                size = path.stat().st_size
                size_str = f"{size / 1024:.1f}KB" if size < 1048576 else f"{size / 1048576:.1f}MB"
                print(f"  [OK] {label}: {path} ({size_str})")
        else:
            print(f"  [--] {label}: not found")


def cmd_reconcile(args):
    """Execute T6 reconciliation QA via reconcile.py."""
    data_path = os.environ.get("DATA_PATH", "./data")
    ticker_dir = Path(data_path) / args.ticker

    edinet_data = ticker_dir / "processed" / "shihanki_structured.json"
    jquants_data = ticker_dir / "processed" / "jquants_fins_statements.json"
    output = ticker_dir / "qa" / "source_reconciliation.json"

    for path, label in [(edinet_data, "T5 structured"), (jquants_data, "T4 J-Quants")]:
        if not path.exists():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            sys.exit(1)

    cmd = [
        sys.executable, str(RECONCILE_SCRIPT),
        "--ticker", args.ticker,
        "--edinet-data", str(edinet_data),
        "--jquants-data", str(jquants_data),
        "--output", str(output),
        "--tolerance", str(args.tolerance),
    ]
    result = subprocess.run(cmd)
    sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(
        description="disclosure-expansion: エンドツーエンド開示データ拡張スキル\n"
                    "validate / status / reconcile / run サブコマンドを提供。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # validate
    val_parser = subparsers.add_parser("validate", help="Validate inputs and environment")
    val_parser.add_argument("--ticker", required=True, help="銘柄コード (4桁)")
    val_parser.add_argument("--edinet-code", required=True, help="EDINETコード")
    val_parser.add_argument("--timeframe", default=None,
                            help="収集対象期間 (YYYY-MM-DD..YYYY-MM-DD)")
    val_parser.add_argument("--skip-jquants", action="store_true")
    val_parser.set_defaults(func=cmd_validate)

    # status
    status_parser = subparsers.add_parser("status", help="Show current data status")
    status_parser.add_argument("--ticker", required=True, help="銘柄コード (4桁)")
    status_parser.set_defaults(func=cmd_status)

    # reconcile
    recon_parser = subparsers.add_parser("reconcile",
                                         help="Execute T6 reconciliation QA")
    recon_parser.add_argument("--ticker", required=True, help="銘柄コード (4桁)")
    recon_parser.add_argument("--tolerance", type=float, default=0.0001,
                              help="Tolerance (default: 0.01%%)")
    recon_parser.set_defaults(func=cmd_reconcile)

    # run
    run_parser = subparsers.add_parser("run",
                                        help="Execute pipeline in DAG dependency order")
    run_parser.add_argument("--ticker", required=True, help="銘柄コード (4桁)")
    run_parser.add_argument("--edinet-code", required=True, help="EDINETコード")
    run_parser.add_argument("--timeframe", default=None,
                             help="収集対象期間 (YYYY-MM-DD..YYYY-MM-DD)")
    run_parser.add_argument("--security-code", default=None,
                             help="証券コード5桁 (default: {ticker}0)")
    run_parser.add_argument("--report-keyword", default="報告書",
                             help="EDINET文書フィルタ (default: 報告書)")
    run_parser.add_argument("--skip-jquants", action="store_true",
                             help="T4 (J-Quants) をスキップ")
    run_parser.add_argument("--skip-qa", action="store_true",
                             help="T6 (突合QA) をスキップ")
    run_parser.add_argument("--dry-run", action="store_true",
                             help="コマンドを表示するが実行しない")
    run_parser.add_argument("--retry", type=int, default=1,
                             help="失敗時リトライ回数 (default: 1)")
    run_parser.add_argument("--on-fail", choices=["abort", "skip"], default="abort",
                             help="失敗時の動作 (default: abort)")
    run_parser.add_argument("--step", action="append",
                             help="実行するステップID (複数指定可、依存も自動追加)")
    run_parser.add_argument("--log-dir", default=None,
                             help="ログ出力先 (default: projects/{ticker}/logs)")
    run_parser.set_defaults(func=cmd_run)

    args = parser.parse_args()

    # Default timeframe: 5 years ago to today
    if hasattr(args, "timeframe") and args.timeframe is None:
        five_years_ago = date.today().replace(year=date.today().year - 5)
        args.timeframe = f"{five_years_ago.isoformat()}..{date.today().isoformat()}"

    args.func(args)


if __name__ == "__main__":
    main()
