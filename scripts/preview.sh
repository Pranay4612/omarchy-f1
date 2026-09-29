#!/usr/bin/env bash
# Render the panel components and write a design screenshot.
# Development only; nothing here is part of the shipped plugin.
#
#   scripts/preview.sh             live-session design
#   scripts/preview.sh --idle      championship design
#
# Two render paths:
#
#   wayland (default)  Opens a real overlay layer for a moment and captures it
#                      with grim. Accurate, including QtQuick.Shapes, which
#                      does not rasterise on the offscreen platform.
#   offscreen          Renders with QT_QPA_PLATFORM=offscreen and grabs the
#                      item directly. Touches nothing on the desktop, but the
#                      track stroke will be missing because Shapes need a real
#                      paint backend. Useful for layout-only checks.
#
# The real plugin runs inside the Omarchy shell, which already has qs.Commons
# and qs.Ui on QML2_IMPORT_PATH. A standalone quickshell instance does not, so
# the import path is reconstructed here from the installed shell.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OMARCHY_PATH="${OMARCHY_PATH:-/usr/share/omarchy}"
IMPORT_DIR="$ROOT/.preview-import"
RENDER="${F1_PREVIEW_RENDER:-wayland}"

MODE=live
[[ "${1:-}" == "--idle" ]] && MODE=idle
if [[ "$MODE" == "idle" ]]; then
  sed -i 's/^var mode = "live"/var mode = "idle"/' "$ROOT/dev-preview.js"
else
  sed -i 's/^var mode = "idle"/var mode = "live"/' "$ROOT/dev-preview.js"
fi

OUT="$ROOT/design/shots/$( [[ "$MODE" == "idle" ]] && echo championship || echo race-live ).png"
mkdir -p "$ROOT/design/shots"
rm -f "$OUT"

mkdir -p "$IMPORT_DIR/qs"
cp -rL "$OMARCHY_PATH/shell/Commons" "$IMPORT_DIR/qs/" 2>/dev/null || true
cp -rL "$OMARCHY_PATH/shell/Ui" "$IMPORT_DIR/qs/" 2>/dev/null || true
export QML2_IMPORT_PATH="$IMPORT_DIR"
trap 'rm -rf "$IMPORT_DIR"' EXIT

fail() {
  echo "preview failed:"
  grep -A4 "Failed to load" /tmp/f1-preview.log || true
  exit 1
}

# shell.qml hosts both harnesses; design renders mock data, panel runs the
# end-to-end check.
export F1_HARNESS=design
export F1_PANEL_SHOT=""

if [[ "$RENDER" == "wayland" ]] && command -v grim >/dev/null; then
  # The shell.qml entry paints a transparent layer-shell surface; F1_PREVIEW_SHOT
  # is unset so the grab timer never fires and the window stays up for grim.
  qs -p "$ROOT" >/tmp/f1-preview.log 2>&1 &
  QS_PID=$!
  sleep 6
  if grep -q "Failed to load configuration" /tmp/f1-preview.log; then
    kill $QS_PID 2>/dev/null || true
    fail
  fi
  # Capture just the preview surface: top-left, 780x520, the panel's own size.
  if ! timeout 10 grim -g "0,0 800x640" "$OUT" 2>/dev/null; then
    echo "grim could not capture; falling back to offscreen"
    kill $QS_PID 2>/dev/null || true
    wait $QS_PID 2>/dev/null || true
    RENDER=offscreen
  else
    kill $QS_PID 2>/dev/null || true
    wait $QS_PID 2>/dev/null || true
  fi
fi

if [[ "$RENDER" != "wayland" ]]; then
  export F1_PREVIEW_SHOT="$OUT"
  export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
  set +e
  timeout 30 qs -p "$ROOT" >/tmp/f1-preview.log 2>&1
  set -e
  grep -q "Failed to load configuration" /tmp/f1-preview.log && fail
fi

if [[ -s "$OUT" ]]; then
  echo "wrote $OUT ($RENDER)"
else
  echo "no image produced; see /tmp/f1-preview.log"
  tail -20 /tmp/f1-preview.log
  exit 1
fi
