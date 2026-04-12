#!/usr/bin/env bash
set -euo pipefail
BASE_URL=${1:-http://10.117.1.148:4444}
echo 'Checking health endpoint...'
curl -fsS "$BASE_URL/health" >/dev/null
echo 'Checking homepage...'
curl -fsS "$BASE_URL/" | grep -q 'LCMS Parent-Metabolite Reviewer'
echo 'Smoke test passed'
