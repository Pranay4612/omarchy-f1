#!/usr/bin/env bash
# End-to-end test of marketplace removal.
#
# `omarchy plugin remove <id>` deletes the plugin directory and never runs
# anything from inside it. This simulates exactly that and asserts the service
# does not survive it:
#
#   service running -> plugin directory deleted -> service notices, exits,
#   leaves no orphan, and takes its cache with it.
#
# The test works on a throwaway copy inside the project and redirects
# XDG_CACHE_HOME into the same sandbox, so it never touches the real
# installation, the real cache, or anything outside this project.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SANDBOX="$ROOT/.removaltest"
PLUGIN_COPY="$SANDBOX/plugin"
CACHE_ROOT="$SANDBOX/cache"
LOG="$SANDBOX/service.log"
PYTHON="${F1_PYTHON:-python3}"

BOLD=$'\033[1m'; RED=$'\033[31m'; GREEN=$'\033[32m'; DIM=$'\033[2m'; OFF=$'\033[0m'
[[ -t 1 ]] || { BOLD=""; RED=""; GREEN=""; DIM=""; OFF=""; }

pass() { printf '  %sPASS%s %s\n' "$GREEN" "$OFF" "$*"; }
fail() { printf '  %sFAIL%s %s\n' "$RED" "$OFF" "$*"; FAILED=1; }
FAILED=0

cleanup() {
  [[ -n "${SVC_PID:-}" ]] && kill -9 "$SVC_PID" 2>/dev/null || true
  rm -rf "$SANDBOX"
}
trap cleanup EXIT

echo "${BOLD}MARKETPLACE REMOVAL TEST${OFF}"
echo "${DIM}sandbox: $SANDBOX${OFF}"
echo

rm -rf "$SANDBOX"
mkdir -p "$PLUGIN_COPY" "$CACHE_ROOT"

# A faithful-enough copy: the manifest the liveness check looks for, the
# package, and the executable.
cp "$ROOT/manifest.json" "$PLUGIN_COPY/"
cp -a "$ROOT/f1" "$PLUGIN_COPY/f1"
mkdir -p "$PLUGIN_COPY/bin"
cp "$ROOT/bin/f1-service" "$PLUGIN_COPY/bin/"
chmod +x "$PLUGIN_COPY/bin/f1-service"
find "$PLUGIN_COPY" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

echo "1. starting the service from the copy"
XDG_CACHE_HOME="$CACHE_ROOT" "$PYTHON" "$PLUGIN_COPY/bin/f1-service" >"$LOG" 2>&1 &
SVC_PID=$!
sleep 4

if kill -0 "$SVC_PID" 2>/dev/null; then
  pass "service is running (pid $SVC_PID)"
else
  fail "service did not start"
  echo "${DIM}$(cat "$LOG")${OFF}"
  exit 1
fi

# Give it long enough to have published a snapshot and be mid-poll.
for _ in $(seq 1 25); do
  [[ -f "$CACHE_ROOT/omarchy/f1/state.json" ]] && break
  sleep 1
done
if [[ -f "$CACHE_ROOT/omarchy/f1/state.json" ]]; then
  pass "service published its snapshot into its own cache"
else
  fail "no snapshot written to $CACHE_ROOT/omarchy/f1/"
  echo "${DIM}$(cat "$LOG")${OFF}"
  exit 1
fi

CONNS_BEFORE=$(ss -tpn 2>/dev/null | grep -c "pid=$SVC_PID," || true)
: "${CONNS_BEFORE:=0}"
echo "${DIM}   established connections held by the service: ${CONNS_BEFORE:-0}${OFF}"

echo
echo "2. deleting the plugin directory (what 'omarchy plugin remove' does)"
rm -rf "$PLUGIN_COPY"
[[ -d "$PLUGIN_COPY" ]] && fail "could not delete the copy" || pass "plugin directory deleted"

echo
echo "3. waiting for the service to notice and exit"
EXITED=0
for _ in $(seq 1 30); do
  if ! kill -0 "$SVC_PID" 2>/dev/null; then EXITED=1; break; fi
  sleep 1
done

if [[ "$EXITED" == "1" ]]; then
  pass "service exited on its own (no orphan)"
else
  fail "service is STILL RUNNING 30s after its directory was deleted"
fi

set +e
wait "$SVC_PID" 2>/dev/null
RC=$?
set -e
if [[ "$RC" == "0" ]]; then
  pass "exit status is 0, so the shell does not report a crash"
else
  fail "exit status was $RC (a non-zero exit looks like a crash to the shell)"
fi

echo
echo "4. checking nothing was left behind"
if [[ -d "$CACHE_ROOT/omarchy/f1" ]]; then
  fail "cache namespace survived: $(ls -A "$CACHE_ROOT/omarchy/f1" | tr '\n' ' ')"
else
  pass "cache namespace removed"
fi

# The sandbox cache root itself must survive; only the plugin's own
# subdirectory is fair game to delete.
if [[ -d "$CACHE_ROOT" ]]; then
  pass "sandbox cache root untouched (only the plugin's namespace was removed)"
else
  fail "the service deleted more than its own namespace"
fi

STRAY=$(pgrep -f "$PLUGIN_COPY/bin/f1-service" 2>/dev/null | wc -l || true)
STRAY="${STRAY//[^0-9]/}"
if [[ "$STRAY" == "0" ]]; then
  pass "no process still references the removed plugin"
else
  fail "$STRAY orphaned process(es) still reference the removed plugin"
fi

CONNS_AFTER=$(ss -tpn 2>/dev/null | grep -c "pid=$SVC_PID," || true)
: "${CONNS_AFTER:=0}"
if [[ "${CONNS_AFTER:-0}" == "0" ]]; then
  pass "no network connections held (pid is gone)"
else
  echo "${DIM}   note: pid reaped, so ss cannot report on it${OFF}"
fi

echo
if [[ "$FAILED" == "0" ]]; then
  printf '%sRemoval is clean: no orphan, no leftover cache, no crash report.%s\n' "$GREEN" "$OFF"
else
  printf '%sRemoval left problems (see FAIL above).%s\n' "$RED" "$OFF"
  exit 1
fi
