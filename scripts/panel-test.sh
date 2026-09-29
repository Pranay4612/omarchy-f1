#!/usr/bin/env bash
# End-to-end check: mount the real Service.qml and the real Panel.qml and
# assert they produce a populated panel from a real snapshot.
#
# This is the test that catches what a lint cannot: a property that does not
# exist on a live object, a component that throws at runtime, a layout that
# does not fit. It runs in its own quickshell instance and never touches the
# user's Omarchy configuration.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OMARCHY_PATH="${OMARCHY_PATH:-/usr/share/omarchy}"
IMPORT="$ROOT/.harness-import"
WORK="$(mktemp -d)"

cleanup() { rm -rf "$IMPORT" "$WORK"; }
trap cleanup EXIT

# A snapshot built by the plugin's own state code from formula1.com fixtures.
python3 "$ROOT/scripts/make-snapshot.py" --out "$WORK" >/dev/null

mkdir -p "$IMPORT/qs"
cp -rL "$OMARCHY_PATH/shell/Commons" "$IMPORT/qs/" 2>/dev/null || true
cp -rL "$OMARCHY_PATH/shell/Ui" "$IMPORT/qs/" 2>/dev/null || true

export QML2_IMPORT_PATH="$IMPORT"
export XDG_CACHE_HOME="$WORK"
export F1_HARNESS=panel

# qs.Ui.Panel is built on a layer-shell surface, so this has to run on the
# real compositor; there is no offscreen backend for it. The surface lives for
# a few seconds and is destroyed on exit.
if [[ "${1:-}" == "--shot" ]]; then
  export F1_PANEL_SHOT="$ROOT/design/shots/panel-e2e.png"
else
  export F1_PANEL_SHOT=""
fi
export QT_QPA_PLATFORM=wayland
qs -p "$ROOT" >/tmp/f1-panel-test.log 2>&1 &
PID=$!
sleep 8
kill $PID 2>/dev/null || true
wait $PID 2>/dev/null || true

# The service must actually be launchable from the path the QML resolved.
# A path that is a URL rather than a filesystem path looks harmless right up
# until the spawn fails, and a warm cache hides the symptom entirely.
SVC_PATH=$(grep -oE "PANEL_SERVICE .*" /tmp/f1-panel-test.log | head -1 | sed 's/^PANEL_SERVICE //' || true)
if [[ -n "$SVC_PATH" ]]; then
  if [[ "$SVC_PATH" == *"://"* ]]; then
    echo "  service path is a URL, not a filesystem path:"
    echo "    $SVC_PATH"
    echo "  the service could never be launched"
    exit 1
  fi
  if [[ ! -f "$SVC_PATH" ]]; then
    echo "  service script does not exist: $SVC_PATH"
    exit 1
  fi
  LAUNCH_CACHE="$WORK/launch"
  mkdir -p "$LAUNCH_CACHE"
  if XDG_CACHE_HOME="$LAUNCH_CACHE" timeout 40 python3 "$SVC_PATH" --once >/dev/null 2>&1; then
    echo "  service launches from the resolved path"
  else
    echo "  service failed to launch from: $SVC_PATH"
    exit 1
  fi
else
  echo "  the harness did not report a service path"
  exit 1
fi

RESULT=$(grep -oE "PANEL_TEST (PASS|FAIL).*" /tmp/f1-panel-test.log | head -1 || true)

if [[ -z "$RESULT" ]]; then
  echo "panel test did not report; see /tmp/f1-panel-test.log"
  grep -E "ERROR|TypeError|ReferenceError|Unable to assign|is not a type|not available" \
    /tmp/f1-panel-test.log | sort -u | head -10
  exit 1
fi

echo "$RESULT"

# Runtime warnings are failures here: a ReferenceError in a live panel is a
# visible bug even when the harness's own assertions happen to pass.
WARNINGS=$(grep -E "ReferenceError|TypeError|Unable to assign|Cannot assign" \
  /tmp/f1-panel-test.log | sort -u | head -5 || true)
if [[ -n "$WARNINGS" ]]; then
  echo "runtime errors:"
  echo "$WARNINGS"
  exit 1
fi

[[ "$RESULT" == *PASS* ]] || exit 1
echo "panel renders from a real snapshot, no runtime errors"
