#!/bin/sh
# pylontech-remote uninstaller (installed as /data/pylontech/uninstall.sh). Run as root:
#
#   sh /data/pylontech/uninstall.sh [--dry-run]
#
# Removes the boot hook and the udev rule, then (after asking) /data/pylontech with the exports.
# Delete the Battery tab in Node-RED yourself.

BASE=/data/pylontech
NODERED=/data/home/nodered/.node-red
RCS=/data/rcS.local
RUN_RULE=/run/udev/rules.d/zz-pylontech-console.rules
MARK_BEGIN='# >>> pylontech-remote'
MARK_END='# <<< pylontech-remote'

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

say() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
do_() { if [ "$DRY" = 1 ]; then say "   [dry-run] $*"; else say "   $*"; eval "$@" || die "failed: $*"; fi; }
ask() {
    printf '%s [y/N] ' "$1"
    read -r answer < /dev/tty || return 1
    case "$answer" in y|Y|yes|a|A|ano) return 0 ;; esac
    return 1
}

[ "$(id -u)" = 0 ] || die "run as root"
if ps | grep -v grep | grep -q -E 'pylontech_(live|export)\.py'; then
    die "Live or a log export is running - stop it in the dashboard first"
fi

say "Boot hook in $RCS"
if [ -f "$RCS" ] && grep -q "^$MARK_BEGIN" "$RCS"; then
    do_ "cp -p '$RCS' '/tmp/rcS.local.before-uninstall'"
    if [ "$DRY" = 1 ]; then
        say "   [dry-run] remove the pylontech-remote block"
    else
        awk -v b="$MARK_BEGIN" -v e="$MARK_END" 'index($0, b) == 1 { skip = 1 } !skip { print } index($0, e) == 1 { skip = 0 }' \
            "$RCS" > "$RCS.new" && cat "$RCS.new" > "$RCS" && rm -f "$RCS.new" || die "cannot update $RCS"
        # nothing else left in it: remove the file
        if [ -z "$(grep -v -e '^#!' -e '^[[:space:]]*$' "$RCS")" ]; then rm -f "$RCS"; fi
    fi
else
    say "   not present"
fi

say "udev rule"
do_ "rm -f '$RUN_RULE'"
do_ "udevadm control --reload-rules"
say "   Venus OS will use the USB adapter again after the next restart."
say "   Unplug the console cable from the battery before that, otherwise Venus OS probes the console."

if [ -d "$NODERED/lib/flows" ]; then do_ "rm -f '$NODERED/lib/flows/pylontech-remote.json'"; fi

if [ -d "$BASE" ]; then
    say "$BASE: program, settings, exported logs ($(ls "$BASE/exports" 2> /dev/null | wc -l) files)"
    if ask "Delete $BASE including the exported logs?"; then
        do_ "rm -rf '$BASE'"
    else
        say "   kept"
    fi
fi
say "Done. Delete the Battery tab in Node-RED yourself."
