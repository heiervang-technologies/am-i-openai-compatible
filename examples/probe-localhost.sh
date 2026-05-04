#!/usr/bin/env bash
# Smoke-probe a local OpenAI-compatible server and print the result.
#
# Usage:
#   examples/probe-localhost.sh                      # http://localhost:8080
#   examples/probe-localhost.sh http://1.2.3.4:11434 # custom URL
#   examples/probe-localhost.sh -- --skip-phase-b    # forwarded to aioc

set -euo pipefail

URL="${1:-http://localhost:8080}"
shift || true

NAME="$(echo "$URL" | sed -E 's#^https?://##; s#[:/].*##')"
REPORT="$(mktemp -t aioc-probe.XXXXXX.json)"

echo "Probing $URL  (label: $NAME)"
aioc probe "$URL" --name "$NAME" --report "$REPORT" "$@"

echo
echo "Report saved to: $REPORT"
echo "Summary:"
python -c "import json,sys; r=json.load(open('$REPORT'));
print('  ', '  '.join(f'{k}={v}' for k,v in r['summary'].items()))"
