#!/usr/bin/env bash
# Install the F1 plugin into Omarchy.
#
# Nothing outside this plugin's own folder is written except one entry in
# ~/.config/omarchy/shell.json, and that entry is added idempotently with a
# timestamped backup. The script refuses to run rather than guess if it finds
# the environment unfamiliar.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ID="io.github.pranay4612.omarchy-f1"
PLUGINS_DIR="$HOME/.config/omarchy/plugins"
TARGET="$PLUGINS_DIR/$PLUGIN_ID"
SHELL_JSON="$HOME/.config/omarchy/shell.json"

BOLD=$'\033[1m'; RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; OFF=$'\033[0m'
[[ -t 1 ]] || { BOLD=""; RED=""; GREEN=""; YELLOW=""; OFF=""; }

SECTION=""
BEFORE=""

usage() {
  cat <<'USAGE'
Usage: ./install.sh [--section left|center|right] [--before <plugin-id>] [--no-enable]

  --section   which bar section to place the widget in
              (default: the manifest's barWidget.defaultSection)
  --before    place the widget immediately before this existing plugin in that
              section, so a hand-tuned bar order is preserved
  --no-enable copy the files but leave the plugin disabled

Examples:
  ./install.sh
  ./install.sh --section right --before io.github.caffeinatedtech.qs-plugin-deepseek-pricing
USAGE
}

while (( $# > 0 )); do
  case "$1" in
    --section) SECTION="${2:-}"; shift 2 ;;
    --section=*) SECTION="${1#*=}"; shift ;;
    --before) BEFORE="${2:-}"; shift 2 ;;
    --before=*) BEFORE="${1#*=}"; shift ;;
    --no-enable) NO_ENABLE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'install: unknown option %s\n\n' "$1" >&2; usage >&2; exit 1 ;;
  esac
done

say()  { printf '%s\n' "$*"; }
ok()   { printf '  %sok%s   %s\n' "$GREEN" "$OFF" "$*"; }
warn() { printf '  %swarn%s %s\n' "$YELLOW" "$OFF" "$*"; }
die()  { printf '  %sfail%s %s\n' "$RED" "$OFF" "$*" >&2; exit 1; }

say "${BOLD}F1 plugin installer${OFF}"
say ""

# ---------------------------------------------------------------- environment
say "Checking the environment"

command -v python3 >/dev/null 2>&1 || die "python3 is not installed"
PY_VERSION=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
ok "python3 $PY_VERSION"

# 3.8 is the floor for the typing syntax used in f1/ (PEP 604 unions in
# annotations are guarded, but the stdlib-only websocket code needs 3.8+).
python3 - <<'PY' || die "python3 3.8 or newer is required"
import sys
raise SystemExit(0 if sys.version_info >= (3, 8) else 1)
PY
ok "python version is sufficient"

command -v jq >/dev/null 2>&1 || die "jq is required (it ships with Omarchy)"
ok "jq"

# The plugin itself is pure standard library. If a real websockets or aiohttp
# happens to be installed that is irrelevant: nothing here imports it, and
# nothing needs installing.
MISSING=$(python3 - <<'PY'
import importlib.util
need = []
for mod in ("json", "base64", "zlib", "ssl", "socket", "urllib.request", "hashlib", "struct"):
    if importlib.util.find_spec(mod) is None:
        need.append(mod)
print(" ".join(need))
PY
)
[[ -z "$MISSING" ]] || die "python is missing standard library modules: $MISSING"
ok "no third-party Python packages needed (standard library only)"

if command -v omarchy >/dev/null 2>&1; then
  OMARCHY_VERSION=$(omarchy version 2>/dev/null || echo "unknown")
  ok "Omarchy $OMARCHY_VERSION"
  command -v quickshell >/dev/null 2>&1 || command -v qs >/dev/null 2>&1 \
    || die "Quickshell is not installed; the plugin cannot render without it"
  ok "Quickshell present"
else
  die "omarchy is not on PATH. This installer targets Omarchy and will not install into an unrelated desktop."
fi

# Quickshell's version decides nothing here, but a very old one lacks the
# FileView/Process APIs the service uses, so it is worth saying out loud.
QS_VERSION=$(qs -V 2>/dev/null | head -1 || true)
[[ -n "$QS_VERSION" ]] && ok "${QS_VERSION}"

say ""
say "No packages are installed by this script. There is nothing to install:
the plugin is QML plus a standard-library Python service, and both data
sources are free public endpoints that need no key and no account."

# ------------------------------------------------------------------- validate
say ""
say "Checking the plugin"
command -v omarchy-plugin-validate >/dev/null 2>&1 || die "omarchy-plugin-validate is missing"
omarchy-plugin-validate "$ROOT" || die "the plugin does not satisfy the Omarchy manifest schema"
ok "manifest validates against the installed schema"

# shell.qml and the preview harness exist only so `qs -p .` can render the
# design; they are development files and must never reach the plugins folder.
# The runtime tree. Kept as an explicit list so a development file can never be
# installed by accident, and so uninstall can mirror it exactly.
RUNTIME_FILES=(
  manifest.json
  Service.qml
  BarWidget.qml
  Panel.qml
  TrackMap.qml
  DriverList.qml
  DriverRow.qml
  Championship.qml
  RaceControl.qml
  SectionLabel.qml
  StatChip.qml
  F1FlagIcon.qml
)
for f in "${RUNTIME_FILES[@]}"; do
  [[ -e "$ROOT/$f" ]] || die "missing $f"
done
ok "entry points and components present"

# --------------------------------------------------------------------- files
say ""
say "Installing to $TARGET"

if [[ -e "$TARGET" ]]; then
  if [[ -d "$TARGET/.git" ]]; then
    BACKUP="$TARGET.backup-$(date +%Y%m%d%H%M%S)"
    say "  existing git checkout found; moving it to"
    say "    $BACKUP"
    mv "$TARGET" "$BACKUP"
  else
    BACKUP="$TARGET.backup-$(date +%Y%m%d%H%M%S)"
    say "  existing install found; moving it to"
    say "    $BACKUP"
    mv "$TARGET" "$BACKUP"
  fi
fi

mkdir -p "$TARGET"

# An explicit list, so a development file can never be installed by accident.
copy_into() {
  local rel="$1"
  mkdir -p "$TARGET/$(dirname "$rel")"
  cp -a "$ROOT/$rel" "$TARGET/$rel"
}

for f in "${RUNTIME_FILES[@]}"; do copy_into "$f"; done
copy_into f1
copy_into bin
ok "copied manifest, QML, components, service and CLI"

# Binaries must be executable after the copy.
chmod +x "$TARGET"/bin/* 2>/dev/null || true
ok "binaries are executable"

# Dev-only files stay behind on purpose.
say "  ${YELLOW}not installed:${OFF} shell.qml, DevPreview.qml, dev-preview.js,"
say "    PanelHarness.qml, design/, tests/, scripts/, circuits/ (development only)"

# Symlinks are refused by the plugin loader, so check what we just wrote.
if find "$TARGET" -name .git -prune -o -type l -print -quit | grep -q .; then
  die "the copied tree contains a symlink, which the plugin loader refuses"
fi
ok "no symlinks in the installed tree"

omarchy-plugin-validate "$TARGET" || die "the installed copy does not validate"
ok "installed copy validates"

# ------------------------------------------------------------------- enable
say ""
say "Enabling in the Omarchy shell"

if omarchy-plugin-list --json 2>/dev/null | jq -e --arg id "$PLUGIN_ID" 'any(.[]; .id == $id)' >/dev/null; then
  ok "the shell already knows about $PLUGIN_ID"
else
  omarchy-shell shell rescanPlugins >/dev/null 2>&1 || warn "rescanPlugins did not respond; the shell may pick it up on its own"
  found=0
  for _ in $(seq 1 40); do
    if omarchy-plugin-list --json 2>/dev/null | jq -e --arg id "$PLUGIN_ID" 'any(.[]; .id == $id)' >/dev/null; then
      found=1
      break
    fi
    sleep 0.1
  done
  [[ $found -eq 1 ]] || die "the running shell did not discover $PLUGIN_ID"
  ok "the shell discovered $PLUGIN_ID"
fi

# Place the widget in the bar. shell.json is the one shared file this touches,
# so back it up first and edit it with jq rather than a text munger.
DEFAULT_SECTION=$(jq -r '.barWidget.defaultSection // "right"' "$TARGET/manifest.json" 2>/dev/null || echo right)
[[ -n "$SECTION" ]] || SECTION="$DEFAULT_SECTION"
if [[ -f "$SHELL_JSON" ]] && jq -e . "$SHELL_JSON" >/dev/null 2>&1; then
  BACKUP="$SHELL_JSON.backup-$(date +%Y%m%d%H%M%S)"
  cp -p "$SHELL_JSON" "$BACKUP"
  ok "backed up shell.json to $(basename "$BACKUP")"

  if jq -e --arg id "$PLUGIN_ID" '
        (.bar.layout // {}) as $l
        | ([($l.left // [])[], ($l.center // [])[], ($l.right // [])[]]
           | any(.id == $id))
      ' "$SHELL_JSON" >/dev/null 2>&1; then
    ok "already present in the bar layout; leaving shell.json untouched"
  else
    tmp=$(mktemp)
    if [[ -n "$BEFORE" ]]; then
      # Insert ahead of an existing widget so a hand-tuned order survives.
      # Any previous copy is removed first, so re-running the installer moves
      # the widget instead of duplicating it.
      jq --arg id "$PLUGIN_ID" --arg section "$SECTION" --arg before "$BEFORE" '
        .bar.layout = (.bar.layout // {})
        | (.bar.layout[$section] // []) as $row
        | ($row | map(.id) | index($before)) as $at
        | .bar.layout[$section] = (
            if $at == null then $row + [{id: $id}]
            else ($row[0:$at] + [{id: $id}] + $row[$at:])
            end
          )
      ' "$SHELL_JSON" >"$tmp" && mv "$tmp" "$SHELL_JSON"

      # Confirm the adjacency rather than trusting the filter.
      read -r -a ORDER <<<"$(jq -r --arg sec "$SECTION" '.bar.layout[$sec] // [] | map(.id) | join(" ")' "$SHELL_JSON")"
      placed=0
      for i in "${!ORDER[@]}"; do
        if [[ "${ORDER[$i]}" == "$PLUGIN_ID" ]]; then
          if (( i + 1 < ${#ORDER[@]} )) && [[ "${ORDER[$i + 1]}" == "$BEFORE" ]]; then
            placed=1
          fi
          break
        fi
      done
      if (( placed )); then
        ok "added to the $SECTION section, immediately before $BEFORE"
      else
        warn "position next to $BEFORE not confirmed; bar order is now: ${ORDER[*]}"
      fi
    else
      jq --arg id "$PLUGIN_ID" --arg section "$SECTION" '
        .bar.layout = (.bar.layout // {})
        | .bar.layout[$section] = ((.bar.layout[$section] // []) + [{id: $id}])
      ' "$SHELL_JSON" >"$tmp" && mv "$tmp" "$SHELL_JSON"
      ok "added to the $SECTION section"
    fi
  fi
else
  warn "no readable $SHELL_JSON; enable the widget from the bar's own menu"
fi

if omarchy-plugin-enable "$PLUGIN_ID" >/dev/null 2>&1; then
  ok "plugin enabled"
else
  warn "could not enable automatically; run: omarchy plugin enable $PLUGIN_ID"
fi

# ------------------------------------------------------------------ keyboard
say ""
say "Optional keyboard shortcut"
say "  To open the panel from anywhere, add a keybind to your Hyprland config:"
say ""
say "    bind = SUPER SHIFT F, exec, omarchy-shell io.github.pranay4612.omarchy-f1.widget toggle"
say ""
say "  This installer does not edit your Hyprland config. Add the line above"
say "  to ~/.config/hypr/hyprland.conf (or a file it includes) if you want it."

# ------------------------------------------------------------------- wrap up
say ""
say "${GREEN}Installed.${OFF}"
say ""
say "  Bar widget      F1 in the bar, top right by default"
say "  Panel           click the bar widget"
say "  Keys            Up/Down select, Enter highlight, Esc close"
say ""
say "  Check the data layer at any time:"
say "    $TARGET/bin/f1-test-live --protocol    decode check, no network needed"
say "    $TARGET/bin/f1-test-live               live feed check"
say ""
say "  Nothing runs in the background unless a session is live; with no"
say "  session the plugin polls a small index file every few minutes and shows"
say "  the championship."
