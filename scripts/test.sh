#!/usr/bin/env bash
# Run the test suite.
#
#   scripts/test.sh            unit tests, no network
#   scripts/test.sh --live     also hit the real public endpoints
#   scripts/test.sh --qml      also lint the QML against the installed shell
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
OMARCHY_PATH="${OMARCHY_PATH:-/usr/share/omarchy}"

echo "== python =="
python3 -m unittest discover -s tests -t . -v 2>&1 | tail -25

if [[ "${1:-}" == "--live" ]]; then
  echo "== live endpoints =="
  F1_LIVE_TESTS=1 python3 -m unittest tests.test_live -v 2>&1 | tail -20
fi

if [[ "${1:-}" == "--qml" || "${1:-}" == "--all" ]]; then
  if command -v qmllint >/dev/null; then
    echo "== qml =="
    IMPORT="$ROOT/.test-import"
    mkdir -p "$IMPORT/qs"
    cp -rL "$OMARCHY_PATH/shell/Commons" "$IMPORT/qs/" 2>/dev/null || true
    cp -rL "$OMARCHY_PATH/shell/Ui" "$IMPORT/qs/" 2>/dev/null || true
    trap 'rm -rf "$IMPORT"' EXIT
    status=0
    for f in Service.qml BarWidget.qml Panel.qml components/*.qml; do
      out=$(qmllint -I "$IMPORT" "$f" 2>&1) || status=1
      if [[ -n "$out" ]]; then
        echo "$out"
        status=1
      fi
    done
    [[ $status -eq 0 ]] && echo "all QML files lint clean"
    exit $status
  else
    echo "qmllint not installed; skipping QML check"
  fi
fi
