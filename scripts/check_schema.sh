#!/usr/bin/env bash
set -euo pipefail

# Script to verify that the committed schema.yml matches the current Django models and views
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMP_SCHEMA="$(mktemp /tmp/schema_check_XXXXXX.yml)"

cleanup() {
    rm -f "${TEMP_SCHEMA}"
}
trap cleanup EXIT

echo "Generating current OpenAPI schema..."
cd "${REPO_ROOT}/backend"

# Determine python command
if [ -f "${REPO_ROOT}/.venv/bin/python" ]; then
    PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
else
    PYTHON_BIN="python"
fi

"${PYTHON_BIN}" manage.py spectacular --file "${TEMP_SCHEMA}" > /dev/null

echo "Comparing generated schema with committed schema.yml..."
if diff -u "${REPO_ROOT}/schema.yml" "${TEMP_SCHEMA}"; then
    echo "SUCCESS: schema.yml is up to date."
    exit 0
else
    echo "ERROR: Committed schema.yml does not match generated schema!" >&2
    echo "Run: python backend/manage.py spectacular --file schema.yml" >&2
    exit 1
fi
