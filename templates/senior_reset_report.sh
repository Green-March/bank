#!/usr/bin/env bash
set -euo pipefail
# Usage: senior_reset_report.sh <junior_number>
# Resets queue/reports/junior{N}_report.yaml to idle state.
# Senior calls this before assigning a new task to a junior.

if [[ "$#" -lt 1 || -z "${1-}" ]]; then
  echo "ERROR: junior number required. Usage: senior_reset_report.sh <1|2|3>" >&2
  exit 2
fi

junior_num="$1"

if [[ ! "$junior_num" =~ ^[1-3]$ ]]; then
  echo "ERROR: junior number must be 1, 2, or 3. Got: ${junior_num}" >&2
  exit 2
fi

script_dir="$(cd "$(dirname "$0")" && pwd)"
report_file="${script_dir}/../queue/reports/junior${junior_num}_report.yaml"

if [[ ! -d "$(dirname "${report_file}")" ]]; then
  echo "ERROR: directory not found: $(dirname "${report_file}")" >&2
  exit 1
fi

tmp_file=""
cleanup() {
  if [[ -n "${tmp_file}" && -f "${tmp_file}" ]]; then
    rm -f "${tmp_file}"
  fi
}
trap cleanup EXIT INT TERM

tmp_file="$(mktemp "$(dirname "${report_file}")/.junior${junior_num}_report.yaml.tmp.XXXXXX")"

cat > "${tmp_file}" <<EOF
worker_id: junior${junior_num}
task_id: null
ticker: null
analysis_type: null
timestamp: ""
status: idle
result: null
quality_check_required: true
EOF

mv "${tmp_file}" "${report_file}"
tmp_file=""

echo "Reset queue/reports/junior${junior_num}_report.yaml to idle"
