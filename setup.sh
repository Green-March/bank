#!/bin/bash
# ============================================================
# setup.sh - Compatibility wrapper
# ============================================================
# This script forwards all arguments to go.sh.
# Prefer running ./go.sh directly.
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/go.sh" "$@"
