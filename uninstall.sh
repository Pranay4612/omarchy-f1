#!/usr/bin/env bash
# Remove the F1 plugin from Omarchy.
#
# Only files belonging to this plugin are removed. The widget's entry in
# shell.json is removed with jq (after a backup), and the plugin's own cache is
# deleted. Nothing else in ~/.config/omarchy, and nothing in the rest of the
# home directory, is touched.

set -euo pipefail

PLUGIN_ID="f1.omarchy"
PLUGINS_DIR="$HOME/.config/omarchy/plugins"
TARGET="$PLUGINS_DIR/$PLUGIN_ID"
SHELL_JSON="$HOME/.config/omarchy/shell.json"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/omarchy/f1"

BOLD=$'\033[1m'; RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; OFF=$'\033[0m'
[[ -t 1 ]] || { BOLD=""; RED=""; GREEN=""; YELLOW=""; OFF=""; }

say()  { printf '%s\n' "$*"; }
ok()   { printf '  %sok%s   %s\n' "$GREEN" "$OFF" "$*"; }
warn() { printf '  %swarn%s %s\n' "$YELLOW" "$OFF" "$*"; }

KEEP_CACHE=0
for arg in "$@"; do
  case "$arg" in
    --keep-cache) KEEP_CACHE=1 ;;
    -h|--help)
      cat <<'USAGE'
Usage: ./uninstall.sh [--keep-cache]

Removes the F1 plugin from Omarchy: the plugin folder, its entry in the bar
layout, and (unless --keep-cache) its cache under
$XDG_CACHE_HOME/omarchy/f1.

A timestamped backup of shell.json is written before the layout is edited.
USAGE
      exit 0
      ;;
    *)
      printf 'uninstall: unknown option %s\n' "$arg" >&2
      exit 1
      ;;
  esac
done

say "${BOLD}Removing the F1 plugin${OFF}"
say ""

# ------------------------------------------------------------------- disable
if command -v omarchy-plugin-disable >/dev/null 2>&1; then
  omarchy-plugin-disable "$PLUGIN_ID" >/dev/null 2>&1 && ok "disabled in the shell" || true
fi
if command -v omarchy-shell >/dev/null 2>&1; then
  omarchy-shell shell rescanPlugins >/dev/null 2>&1 || true
fi

# ----------------------------------------------------------------- bar layout
if [[ -f "$SHELL_JSON" ]] && jq -e . "$SHELL_JSON" >/dev/null 2>&1; then
  if jq -e --arg id "$PLUGIN_ID" '
        (.bar.layout // {}) as $l
        | ([($l.left // [])[], ($l.center // [])[], ($l.right // [])[]]
           | any(.id == $id))
      ' "$SHELL_JSON" >/dev/null 2>&1; then
    BACKUP="$SHELL_JSON.backup-$(date +%Y%m%d%H%M%S)"
    cp -p "$SHELL_JSON" "$BACKUP"
    ok "backed up shell.json to $(basename "$BACKUP")"

    tmp=$(mktemp)
    jq --arg id "$PLUGIN_ID" '
      .bar.layout = (.bar.layout // {})
      | ["left", "center", "right"][] as $s
        | .bar.layout[$s] = ((.bar.layout[$s] // []) | map(select(.id != $id)))
    ' "$SHELL_JSON" >"$tmp" && mv "$tmp" "$SHELL_JSON"
    ok "removed the widget from the bar layout"
  else
    ok "widget was not in the bar layout"
  fi
else
  warn "no readable $SHELL_JSON; check your bar layout by hand"
fi

# -------------------------------------------------------------------- service
# The service is a detached child of the shell. Stop it before removing the
# files it executes.
if pgrep -f "f1-omarchy-plugin/bin/f1-service" >/dev/null 2>&1; then
  pkill -f "f1-omarchy-plugin/bin/f1-service" 2>/dev/null || true
  sleep 0.3
  ok "stopped the running F1 service"
fi

# --------------------------------------------------------------------- files
if [[ -d "$TARGET" ]]; then
  rm -rf "$TARGET"
  ok "removed $TARGET"
else
  ok "plugin folder was not installed"
fi

# Only the plugin's own files were ever written, so removing the folder is
# complete. Nothing else in ~/.config/omarchy is touched.

# Leave any backups from a previous install in place; they are inert and the
# user may want to compare. List them so nothing is a surprise.
if compgen -G "$PLUGINS_DIR/$PLUGIN_ID.backup-*" >/dev/null; then
  say ""
  say "  Previous installs were left in place as backups:"
  for d in "$PLUGINS_DIR/$PLUGIN_ID.backup-"*; do
    say "    $(basename "$d")"
  done
  say "  Delete them yourself when you are happy."
fi

# --------------------------------------------------------------------- cache
if [[ "$KEEP_CACHE" -eq 1 ]]; then
  ok "cache kept at $CACHE_DIR (--keep-cache)"
elif [[ -d "$CACHE_DIR" ]]; then
  rm -rf "$CACHE_DIR"
  ok "removed the cache at $CACHE_DIR"
else
  ok "no cache to remove"
fi

# Leftover empty parents, only if they are genuinely empty.
rmdir "$PLUGINS_DIR" 2>/dev/null || true

say ""
say "${GREEN}Uninstalled.${OFF}"
say ""
say "  Restoring the bar layout, if needed:"
say "    omarchy shell rescanPlugins"
say ""
say "  A backup of your previous shell.json is next to it in"
say "    $(dirname "$SHELL_JSON")"
