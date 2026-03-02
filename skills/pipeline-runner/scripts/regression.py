"""Regression testing for BANK pipeline.

Re-runs pipeline from a specified step for multiple tickers,
compares JSON outputs before/after, and generates a diff report.
Rolls back on failure.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# Allow running as script from project root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline import PipelineConfig

JST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------------------
# DAG helpers
# ---------------------------------------------------------------------------

def compute_exec_set(config: PipelineConfig, from_step: str) -> set[str]:
    """Compute steps that will be executed from *from_step* onwards (BFS)."""
    dependents: dict[str, list[str]] = {s.id: [] for s in config.steps}
    for step in config.steps:
        for dep in step.depends_on:
            dependents[dep].append(step.id)

    exec_set = {from_step}
    queue = [from_step]
    while queue:
        sid = queue.pop(0)
        for dep_id in dependents.get(sid, []):
            if dep_id not in exec_set:
                exec_set.add(dep_id)
                queue.append(dep_id)
    return exec_set


def resolve_output_dirs(
    config: PipelineConfig, ticker: str, exec_set: set[str],
) -> dict[str, str]:
    """Map step_id -> resolved output_dir for steps in exec_set."""
    dirs: dict[str, str] = {}
    for step in config.steps:
        if step.id in exec_set:
            dirs[step.id] = step.output_dir.replace("{ticker}", ticker)
    return dirs


# ---------------------------------------------------------------------------
# Vars resolution (3-tier fallback)
# ---------------------------------------------------------------------------

def find_log(ticker: str) -> Path | None:
    """Find the pipeline log for *ticker*."""
    for candidate in (
        Path(f"data/{ticker}/pipeline_log.json"),
        Path(f"data/{ticker}/logs/pipeline_run.json"),
    ):
        if candidate.exists():
            return candidate
    return None


def _extract_shares_outstanding(ticker: str) -> str:
    """Try to recover shares_outstanding from existing DCF output."""
    dcf_path = Path(f"data/{ticker}/valuation/dcf.json")
    if dcf_path.exists():
        try:
            with open(dcf_path, encoding="utf-8") as f:
                dcf = json.load(f)
            val = dcf.get("assumptions", {}).get("shares_outstanding")
            if val is not None:
                return str(int(val)) if float(val) == int(float(val)) else str(val)
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            pass
    return ""


def resolve_vars(
    ticker: str, log_path: Path | None,
) -> tuple[dict[str, str] | None, str | None]:
    """Resolve runtime vars with 3-tier fallback.

    Returns (vars_dict, source) or (None, None) on skip.
    """
    # Tier 1: pipeline log with runtime_vars
    if log_path:
        try:
            with open(log_path, encoding="utf-8") as f:
                log_data = json.load(f)
            rv = log_data.get("runtime_vars", {})
            if rv:
                return {k: str(v) for k, v in rv.items()}, "pipeline_log"
        except (json.JSONDecodeError, OSError):
            pass

    # Tier 2: resolve_result.json + reconstruct from existing step outputs
    resolve_path = Path(f"data/{ticker}/resolved/resolve_result.json")
    if resolve_path.exists():
        try:
            with open(resolve_path, encoding="utf-8") as f:
                result = json.load(f)
            vars_dict: dict[str, str] = {}
            for key in ("edinet_code", "fye_month", "company_name"):
                if key in result and result[key] is not None:
                    vars_dict[key] = str(result[key])
            # Recover shares_outstanding from DCF assumptions if available,
            # otherwise use empty string so the pipeline proceeds gracefully.
            vars_dict["shares_outstanding"] = _extract_shares_outstanding(ticker)
            if vars_dict:
                return vars_dict, "resolve_result"
        except (json.JSONDecodeError, OSError):
            pass

    # Tier 3: skip
    return None, None


# ---------------------------------------------------------------------------
# JSON diff
# ---------------------------------------------------------------------------

def json_diff(old: Any, new: Any, path: str = "") -> list[dict[str, Any]]:
    """Recursively compare two JSON values, returning a list of diffs."""
    diffs: list[dict[str, Any]] = []

    if type(old) is not type(new):
        diffs.append({"path": path or "$", "type": "changed", "old": old, "new": new})
        return diffs

    if isinstance(old, dict):
        all_keys = sorted(set(old.keys()) | set(new.keys()))
        for key in all_keys:
            child_path = f"{path}.{key}" if path else key
            if key not in old:
                diffs.append({"path": child_path, "type": "added", "new": new[key]})
            elif key not in new:
                diffs.append({"path": child_path, "type": "removed", "old": old[key]})
            else:
                diffs.extend(json_diff(old[key], new[key], child_path))
    elif isinstance(old, list):
        for i in range(max(len(old), len(new))):
            child_path = f"{path}[{i}]"
            if i >= len(old):
                diffs.append({"path": child_path, "type": "added", "new": new[i]})
            elif i >= len(new):
                diffs.append({"path": child_path, "type": "removed", "old": old[i]})
            else:
                diffs.extend(json_diff(old[i], new[i], child_path))
    else:
        if old != new:
            diffs.append({"path": path or "$", "type": "changed", "old": old, "new": new})

    return diffs


# ---------------------------------------------------------------------------
# Backup / rollback
# ---------------------------------------------------------------------------

def _unique_output_dirs(output_dirs: dict[str, str]) -> set[str]:
    return set(output_dirs.values())


def backup_dirs(
    ticker: str, output_dirs: dict[str, str], timestamp: str,
) -> dict[str, dict[str, str]]:
    """Backup output directories to /tmp.  Returns {dir_path: {src, dst}}."""
    backup_root = Path(f"/tmp/bank_regression_{ticker}_{timestamp}")
    backup_map: dict[str, dict[str, str]] = {}

    for dir_path in sorted(_unique_output_dirs(output_dirs)):
        src = Path(dir_path)
        if not src.exists():
            continue

        rel_key = dir_path.replace("/", "_")
        dst = backup_root / rel_key

        # For ticker-root dirs (e.g. data/{ticker}), only copy direct files
        # to avoid copying the huge raw/ subtree.
        ticker_root = Path(f"data/{ticker}")
        if src == ticker_root:
            dst.mkdir(parents=True, exist_ok=True)
            for f in src.iterdir():
                if f.is_file():
                    shutil.copy2(f, dst / f.name)
        else:
            shutil.copytree(src, dst, dirs_exist_ok=True)

        backup_map[dir_path] = {"src": str(src), "dst": str(dst)}

    return backup_map


def rollback(
    backup_map: dict[str, dict[str, str]], ticker: str,
) -> None:
    """Restore output directories from backup."""
    ticker_root = str(Path(f"data/{ticker}"))
    for dir_path, paths in backup_map.items():
        src = Path(paths["dst"])   # backup
        dst = Path(paths["src"])   # original

        if not src.exists():
            continue

        if dir_path == ticker_root:
            # Only restore direct files
            for f in src.iterdir():
                if f.is_file():
                    shutil.copy2(f, dst / f.name)
        else:
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)


def cleanup_backup(backup_map: dict[str, dict[str, str]]) -> None:
    """Remove all backup directories after successful run."""
    roots: set[Path] = set()
    for paths in backup_map.values():
        roots.add(Path(paths["dst"]).parent)
    for root in roots:
        if root.exists():
            shutil.rmtree(root)


# ---------------------------------------------------------------------------
# JSON snapshot collection
# ---------------------------------------------------------------------------

def collect_json_files(directory: str) -> dict[str, Any]:
    """Collect {relative_path: parsed_json} for every *.json under *directory*."""
    files: dict[str, Any] = {}
    dir_path = Path(directory)
    if not dir_path.exists():
        return files
    for f in sorted(dir_path.rglob("*.json")):
        rel = str(f.relative_to(dir_path))
        try:
            with open(f, encoding="utf-8") as fh:
                files[rel] = json.load(fh)
        except (json.JSONDecodeError, OSError):
            pass
    return files


# ---------------------------------------------------------------------------
# Per-ticker regression run
# ---------------------------------------------------------------------------

def run_ticker(
    ticker: str,
    config: PipelineConfig,
    from_step: str,
    pipeline_path: str,
    exec_set: set[str],
    output_dirs: dict[str, str],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Orchestrate regression for a single ticker."""
    result: dict[str, Any] = {
        "ticker": ticker,
        "status": "pending",
        "vars_source": None,
        "diffs": {},
        "errors": [],
    }

    # --- Resolve vars ---
    log_path = find_log(ticker)
    runtime_vars, vars_source = resolve_vars(ticker, log_path)
    result["vars_source"] = vars_source

    if runtime_vars is None:
        result["status"] = "skipped"
        result["errors"].append("SKIPPED: insufficient data")
        return result

    # --- Dry-run ---
    if dry_run:
        result["status"] = "dry_run"
        result["output_dirs"] = output_dirs
        result["vars"] = {"ticker": ticker, **runtime_vars}
        result["log_path"] = str(log_path) if log_path else None
        return result

    timestamp = datetime.now(JST).strftime("%Y%m%d_%H%M%S")

    # --- Backup ---
    backup_map = backup_dirs(ticker, output_dirs, timestamp)

    # --- Pre-run snapshots ---
    pre_jsons: dict[str, dict[str, Any]] = {}
    for dir_path in _unique_output_dirs(output_dirs):
        pre_jsons[dir_path] = collect_json_files(dir_path)

    # --- Build CLI command ---
    vars_parts = [f"ticker={ticker}"]
    use_log = log_path if vars_source == "pipeline_log" else None

    if use_log:
        pass  # runtime_vars come from --log
    else:
        for k, v in runtime_vars.items():
            vars_parts.append(f"{k}={v}")

    cmd = [
        "python3", "skills/pipeline-runner/scripts/main.py", "run",
        "--pipeline", str(pipeline_path),
        "--vars", ",".join(vars_parts),
        "--from-step", from_step,
    ]
    if use_log:
        cmd.extend(["--log", str(use_log)])

    # --- Execute ---
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )

        if proc.returncode != 0:
            result["errors"].append(f"Pipeline exit code: {proc.returncode}")
            stderr_tail = proc.stderr[-500:] if proc.stderr else ""
            if stderr_tail:
                result["errors"].append(stderr_tail)
            rollback(backup_map, ticker)
            result["status"] = "rolled_back"
            return result

    except subprocess.TimeoutExpired:
        result["errors"].append("Pipeline timed out (600s)")
        rollback(backup_map, ticker)
        result["status"] = "rolled_back"
        return result

    # --- Post-run diffs ---
    for step_id, dir_path in output_dirs.items():
        post_jsons = collect_json_files(dir_path)
        pre = pre_jsons.get(dir_path, {})

        file_diffs: dict[str, list[dict[str, Any]]] = {}
        all_files = sorted(set(pre.keys()) | set(post_jsons.keys()))
        for fname in all_files:
            if fname not in pre:
                file_diffs[fname] = [{"path": "$", "type": "added", "new": "(new file)"}]
            elif fname not in post_jsons:
                file_diffs[fname] = [{"path": "$", "type": "removed", "old": "(deleted)"}]
            else:
                d = json_diff(pre[fname], post_jsons[fname])
                if d:
                    file_diffs[fname] = d

        if file_diffs:
            result["diffs"][step_id] = file_diffs

    result["status"] = "completed"

    # --- Cleanup successful backup ---
    cleanup_backup(backup_map)

    return result


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(
    results: list[dict[str, Any]], from_step: str, report_path: str,
) -> str:
    """Generate a markdown regression report."""
    lines = [
        "# Regression Report",
        "",
        f"**Date**: {datetime.now(JST).isoformat()}",
        f"**From Step**: {from_step}",
        f"**Tickers**: {len(results)}",
        "",
        "## Summary",
        "",
        "| Ticker | Status | Vars Source | Changed Files |",
        "|--------|--------|-------------|---------------|",
    ]

    for r in results:
        changed = sum(len(d) for d in r.get("diffs", {}).values())
        lines.append(
            f"| {r['ticker']} | {r['status']} "
            f"| {r.get('vars_source') or '-'} | {changed} |"
        )

    lines.extend(["", "## Details", ""])

    for r in results:
        lines.append(f"### {r['ticker']} — {r['status']}")
        lines.append("")

        if r.get("errors"):
            lines.append("**Errors:**")
            for e in r["errors"]:
                lines.append(f"- {e}")
            lines.append("")

        if r.get("diffs"):
            for step_id, file_diffs in r["diffs"].items():
                lines.append(f"#### Step: {step_id}")
                lines.append("")
                for fname, diffs in file_diffs.items():
                    lines.append(f"**{fname}**: {len(diffs)} change(s)")
                    for d in diffs[:10]:
                        if d["type"] == "changed":
                            lines.append(
                                f"  - `{d['path']}`: `{d.get('old')}` → `{d.get('new')}`"
                            )
                        elif d["type"] == "added":
                            lines.append(
                                f"  - `{d['path']}`: +(added) `{d.get('new')}`"
                            )
                        elif d["type"] == "removed":
                            lines.append(
                                f"  - `{d['path']}`: -(removed) `{d.get('old')}`"
                            )
                    if len(diffs) > 10:
                        lines.append(f"  - ... and {len(diffs) - 10} more changes")
                    lines.append("")
        else:
            lines.append("No changes detected.")
            lines.append("")

    report = "\n".join(lines)
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(report_path).write_text(report, encoding="utf-8")
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Regression testing for BANK pipeline",
    )
    parser.add_argument(
        "--tickers", required=True,
        help="Comma-separated ticker codes",
    )
    parser.add_argument(
        "--from-step", default="calculate", dest="from_step",
        help="Step to resume from (default: calculate)",
    )
    parser.add_argument(
        "--pipeline", required=True,
        help="Path to pipeline YAML",
    )
    parser.add_argument(
        "--report", default="data/regression_report.md",
        help="Output report path",
    )
    parser.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help="Show what would be done without executing",
    )

    args = parser.parse_args()
    tickers = [t.strip() for t in args.tickers.split(",")]

    # Load pipeline config
    config = PipelineConfig.load(args.pipeline)

    # Compute exec set
    exec_set = compute_exec_set(config, args.from_step)

    print(f"Regression: from_step={args.from_step}")
    print(f"Exec set: {sorted(exec_set)}")
    print(f"Tickers: {tickers}")

    # Run regression per ticker
    results: list[dict[str, Any]] = []
    for ticker in tickers:
        output_dirs = resolve_output_dirs(config, ticker, exec_set)

        print(f"\n{'=' * 60}")
        print(f"Processing {ticker}")
        print(f"{'=' * 60}")

        r = run_ticker(
            ticker, config, args.from_step, args.pipeline,
            exec_set, output_dirs, args.dry_run,
        )
        results.append(r)

        print(f"  Status: {r['status']}")
        if r.get("errors"):
            for e in r["errors"]:
                print(f"  Error: {e}")
        if r.get("diffs"):
            for step_id, fd in r["diffs"].items():
                print(f"  Step {step_id}: {len(fd)} file(s) changed")

    # Generate report
    report_path = args.report
    generate_report(results, args.from_step, report_path)
    print(f"\nReport written to: {report_path}")

    # Summary
    statuses = {r["status"] for r in results}
    completed = sum(1 for r in results if r["status"] == "completed")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    failed = sum(1 for r in results if r["status"] in ("failed", "rolled_back"))
    print(f"\nCompleted: {completed}, Skipped: {skipped}, Failed: {failed}")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
