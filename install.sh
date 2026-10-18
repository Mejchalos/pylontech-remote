#!/bin/sh
# pylontech-remote installer for Victron Venus OS (Cerbo GX). Run as root on the Cerbo:
#
#   wget -O /tmp/pylontech-install.sh https://raw.githubusercontent.com/Mejchalos/pylontech-remote/main/install.sh
#   sh /tmp/pylontech-install.sh
#
# Installs or updates the program in /data/pylontech, keeps Venus OS's serial-starter away from
# the battery console (udev rule restored at every boot from /data, so it survives Venus OS
# updates) and prepares the Node-RED flow. A replaced cable is found automatically (boot.sh,
# pylontech_adopt.py). Every change is shown before it is made.
#
# Options:
#   --dry-run       show what would be done, change nothing
#   --reconfigure   choose the USB adapter again (or let it be found automatically)
#   --yes           no questions; the cable is found automatically (the adapter that answers
#                   Enter with the console prompt)
#   --source DIR    install from an unpacked copy of the repository instead of downloading
#   --branch NAME   download this branch (default: main)
#
# The battery only ever receives read commands (a test read at the end).
# Exit code: 0 done, 1 failed (see the message), 3 installed but the battery did not answer.

REPO=Mejchalos/pylontech-remote
BRANCH=main
BASE=/data/pylontech
NODERED=/data/home/nodered/.node-red
RCS=/data/rcS.local
OLD_ETC_RULE=/etc/udev/rules.d/zz-pylontech-console.rules
MARK_BEGIN='# >>> pylontech-remote (added by the installer; removed by /data/pylontech/uninstall.sh)'
MARK_END='# <<< pylontech-remote'

DRY=0; YES=0; RECONF=0; SRC=''
while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY=1 ;;
        --yes) YES=1 ;;
        --reconfigure) RECONF=1 ;;
        --source) SRC=$2; shift ;;
        --branch) BRANCH=$2; shift ;;
        *) echo "unknown option: $1"; exit 2 ;;
    esac
    shift
done

say()  { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
# run a command that changes something (only printed in --dry-run)
do_()  { if [ "$DRY" = 1 ]; then say "   [dry-run] $*"; else say "   $*"; eval "$@" || die "failed: $*"; fi; }
ask()  {
    [ "$YES" = 1 ] && return 0
    printf '%s [y/N] ' "$1"
    read -r answer < /dev/tty || return 1
    case "$answer" in y|Y|yes|a|A|ano) return 0 ;; esac
    return 1
}
# what the Cerbo sees on USB (for the log when the cable is not found)
usb_report() {
    say "USB devices:"
    for u in /sys/bus/usb/devices/*; do
        [ -f "$u/idVendor" ] || continue
        [ "$(cat "$u/idVendor")" = 1d6b ] && continue     # the Cerbo's own USB hubs
        drv=''
        for i in "$u"/*:*; do [ -L "$i/driver" ] && drv="$drv $(basename "$(readlink "$i/driver")")"; done
        say "   $(basename "$u")  $(cat "$u/idVendor"):$(cat "$u/idProduct")  $(cat "$u/manufacturer" 2>/dev/null) $(cat "$u/product" 2>/dev/null)  driver:${drv:- none}"
    done
    say "Kernel messages about USB (last 20):"
    dmesg | grep -i -E 'usb|tty|ch34|ftdi|pl2303|cp210' | tail -n 20 | sed 's/^/   /'
}

[ "$DRY" = 1 ] && say "*** DRY RUN: nothing will be changed ***"

# -- 1. checks ---------------------------------------------------------------------------------
step "Checking the Cerbo"
[ "$(id -u)" = 0 ] || die "run as root"
[ -f /opt/victronenergy/version ] || die "this is not Venus OS"
say "Venus OS $(sed -n 1p /opt/victronenergy/version)"
command -v python3 > /dev/null || die "python3 missing - Venus OS Large is required"
python3 -c 'import serial' 2> /dev/null || die "python3 module 'serial' missing - Venus OS Large is required"
id nodered > /dev/null 2>&1 || die "user 'nodered' missing - Venus OS Large with Node-RED is required"
[ -d "$NODERED" ] || say "WARNING: Node-RED has not been started yet ($NODERED missing) - enable it in Settings > Integrations"
if [ -d "$NODERED/node_modules/@flowfuse/node-red-dashboard" ]; then
    say "Node-RED Dashboard 2.0: installed"
else
    say "WARNING: Node-RED Dashboard 2.0 not installed - install @flowfuse/node-red-dashboard from the palette manager"
fi
running=$(ps | grep -v grep | grep -E 'pylontech_(live|export)\.py' | awk '{ print $1 }')
if [ -n "$running" ]; then
    [ "$YES" = 1 ] || die "Live or a log export is running - stop it in the dashboard first"
    say "Stopping Live / log export (pid $running); start Live again in the dashboard afterwards"
    do_ "kill $running"
    [ "$DRY" = 1 ] || sleep 2
fi
# a cable search in the background (pylontech_adopt.py) is started again below if still needed
running=$(ps | grep -v grep | grep -E 'pylontech_adopt\.py' | awk '{ print $1 }')
[ -n "$running" ] && do_ "kill $running"

# -- 2. get the program ------------------------------------------------------------------------
step "Getting pylontech-remote"
if [ -z "$SRC" ]; then
    TMP=/tmp/pylontech-remote-install
    rm -rf "$TMP" && mkdir -p "$TMP" || die "cannot create $TMP"
    URL="https://github.com/$REPO/archive/refs/heads/$BRANCH.tar.gz"
    say "downloading $URL"
    wget -q -O "$TMP/src.tar.gz" "$URL" || die "download failed"
    tar -xzf "$TMP/src.tar.gz" -C "$TMP" || die "cannot unpack"
    SRC=$(find "$TMP" -mindepth 1 -maxdepth 1 -type d | sed -n 1p)
    ORIGIN="$REPO $BRANCH"
elif [ -f "$SRC/VERSION" ]; then
    ORIGIN=$(sed -n 1p "$SRC/VERSION")
else
    ORIGIN="local copy $SRC"
fi
for f in pylontech_live.py pylontech_export.py pylontech_adopt.py pylontech_remote/session.py venus/boot.sh uninstall.sh nodered/pylontech_flow.json; do
    [ -f "$SRC/$f" ] || die "$SRC/$f missing - not a pylontech-remote source"
done
say "source: $SRC"

# -- 3. install the program --------------------------------------------------------------------
step "Installing into $BASE"
if [ -d "$BASE/app" ]; then say "existing installation found - updating the program, keeping settings, state and exports"; fi
do_ "mkdir -p '$BASE/app/pylontech_remote' '$BASE/state' '$BASE/exports' '$BASE/backup'"
do_ "rm -rf '$BASE/app/pylontech_remote/__pycache__' '$BASE/app/__pycache__'"
do_ "cp '$SRC/pylontech_live.py' '$SRC/pylontech_export.py' '$SRC/pylontech_adopt.py' '$BASE/app/'"
do_ "cp '$SRC'/pylontech_remote/*.py '$BASE/app/pylontech_remote/'"
do_ "chmod 755 '$BASE/app/pylontech_live.py' '$BASE/app/pylontech_export.py' '$BASE/app/pylontech_adopt.py'"
do_ "cp '$SRC/venus/boot.sh' '$SRC/uninstall.sh' '$BASE/'"
do_ "chmod 755 '$BASE/boot.sh' '$BASE/uninstall.sh'"
do_ "cp '$SRC/nodered/pylontech_flow.json' '$BASE/pylontech_flow.json'"
do_ "chown nodered:nodered '$BASE/state' '$BASE/exports'"
do_ "echo 'installed $(date '+%Y-%m-%d %H:%M') from $ORIGIN' > '$BASE/VERSION'"
if [ -d "$NODERED" ]; then
    do_ "mkdir -p '$NODERED/lib/flows'"
    do_ "cp '$SRC/nodered/pylontech_flow.json' '$NODERED/lib/flows/pylontech-remote.json'"
    do_ "chown -R nodered:nodered '$NODERED/lib'"
fi

# -- 4. the console adapter --------------------------------------------------------------------
step "USB adapter of the battery console"
# Without a choice here the cable is found automatically after the boot hook is in place (step 6):
# the adapter that answers Enter with the console prompt. A replaced cable is found the same way.
python3 "$SRC/pylontech_adopt.py" --list
if [ -f "$BASE/udev.rules" ] && [ "$RECONF" = 0 ]; then
    say "configured (use --reconfigure to choose again):"
    sed 's/^/   /' "$BASE/udev.rules"
elif [ "$YES" = 1 ]; then
    say "the cable is found automatically below"
else
    printf 'Which one is the battery console cable? [number, Enter = find it automatically] '
    read -r choice < /dev/tty || choice=''
    if [ -f "$BASE/udev.rules" ]; then
        do_ "cp -p '$BASE/udev.rules' '$BASE/backup/udev.rules.$(date +%Y%m%d%H%M%S)'"
        do_ "rm -f '$BASE/udev.rules' '$BASE/udev.match'"
    fi
    if [ -n "$choice" ]; then
        dev=$(ls /sys/class/tty | grep '^ttyUSB' | sort | sed -n "${choice}p")
        [ -n "$dev" ] || die "invalid choice"
        ask "Use /dev/$dev as the battery console?" || die "cancelled"
        if [ "$DRY" = 1 ]; then
            python3 "$SRC/pylontech_adopt.py" --use "/dev/$dev" --dry-run
        else
            python3 "$SRC/pylontech_adopt.py" --use "/dev/$dev" || die "cannot save the rule"
        fi
    else
        say "the cable is found automatically below"
    fi
fi

# -- 5. restore the rule at every boot ---------------------------------------------------------
step "Boot hook ($RCS)"
if [ -f "$RCS" ] && grep -qF '# >>> pylontech-remote' "$RCS"; then
    say "already present"
else
    block="$MARK_BEGIN
[ -x $BASE/boot.sh ] && $BASE/boot.sh
$MARK_END"
    if [ -f "$RCS" ]; then
        say "$RCS exists (other software uses it too): adding our block after its first line, backup in $BASE/backup/"
        do_ "cp -p '$RCS' '$BASE/backup/rcS.local.$(date +%Y%m%d%H%M%S)'"
        if [ "$DRY" = 1 ]; then
            say "   [dry-run] insert into $RCS:"; printf '%s\n' "$block" | sed 's/^/      /'
        else
            awk -v b="$block" 'NR==1 && /^#!/ { print; print b; done=1; next } NR==1 { print b; done=1 } { print }' "$RCS" > "$RCS.new" \
                && cat "$RCS.new" > "$RCS" && rm -f "$RCS.new" || die "cannot update $RCS"
            say "   block added to $RCS"
        fi
    else
        if [ "$DRY" = 1 ]; then
            say "   [dry-run] create $RCS:"; printf '#!/bin/sh\n%s\n' "$block" | sed 's/^/      /'
        else
            printf '#!/bin/sh\n%s\n' "$block" > "$RCS" || die "cannot write $RCS"
            say "   created $RCS"
        fi
    fi
    do_ "chmod 755 '$RCS'"
fi

if [ -f "$OLD_ETC_RULE" ]; then
    say "An older rule from a manual setup is in $OLD_ETC_RULE. It is replaced by the boot hook"
    say "(and would disappear with the next Venus OS update anyway)."
    if ask "Remove it (a backup goes to $BASE/backup/)?"; then
        do_ "cp -p '$OLD_ETC_RULE' '$BASE/backup/'"
        do_ "rm -f '$OLD_ETC_RULE'"
    fi
fi

# -- 6. apply now ------------------------------------------------------------------------------
step "Applying the rule now"
do_ "'$BASE/boot.sh' apply"
# the last run's lines of the boot log
[ "$DRY" = 0 ] && awk '/ pylontech-remote boot/ { b = "" } { b = b "   " $0 "\n" } END { printf "%s", b }' "$BASE/boot.log"
if [ "$DRY" = 0 ] && [ ! -e /dev/ttyPYLON ]; then
    step "Looking for the battery console cable"
    python3 "$BASE/app/pylontech_adopt.py" --once --wait 30 | sed 's/^/   /'
    if [ ! -e /dev/ttyPYLON ]; then
        usb_report
        say "Not found now. The search goes on in the background, and a cable plugged in later is"
        say "found automatically (log: $BASE/adapter.log)."
    fi
fi

# -- 7. test read ------------------------------------------------------------------------------
step "Reading the battery (pwr, bat, info, stat, config - read only)"
TEST=0
if [ "$DRY" = 1 ]; then
    say "   [dry-run] skipped"
elif [ ! -e /dev/ttyPYLON ]; then
    say "FAILED: no battery console cable (no /dev/ttyPYLON)."
    TEST=1
else
    # Venus OS lets go of the port within seconds; wait until it has been free for 3 s
    free=0; i=0
    while [ $free -lt 3 ] && [ $i -lt 30 ]; do
        if fuser /dev/ttyPYLON > /dev/null 2>&1; then free=0; else free=$((free + 1)); fi
        sleep 1; i=$((i + 1))
    done
    TEST=1
    rm -f "$BASE/diagnostics.txt"
    for attempt in 1 2 3; do
        [ $attempt -gt 1 ] && sleep 5
        if fuser /dev/ttyPYLON > /dev/null 2>&1; then
            say "   attempt $attempt: the port is in use (pid $(fuser /dev/ttyPYLON 2> /dev/null))"
            continue
        fi
        # every command with its raw reply goes to diagnostics.txt (to adapt the program to
        # other batteries and firmwares)
        python3 "$BASE/app/pylontech_live.py" --port /dev/ttyPYLON --once --state-file '' \
            --raw-dump "$BASE/diagnostics.txt" > /tmp/pylontech-test.json 2> /tmp/pylontech-test.err
        if python3 - /tmp/pylontech-test.json "$attempt" << 'PYEOF'; then TEST=0; break; fi
import json, sys
try:
    snap = json.loads(open(sys.argv[1]).read().strip().splitlines()[-1])
except (OSError, IndexError, ValueError):
    snap = {'error': 'the reader gave no answer'}
if not snap.get('ok'):
    print('   attempt %s: %s' % (sys.argv[2], snap.get('error')))
    sys.exit(1)
for m in snap['modules']:
    g = lambda k: '?' if m.get(k) is None else m.get(k)
    print('   M%-2s %-8s %-18s fw %-12s %3s%%  %s cells' % (g('id'), g('model'), g('barcode'), g('fw'), g('soc_pct'), g('n_cells')))
PYEOF
        tail -n 5 /tmp/pylontech-test.err | sed 's/^/      /'
    done
    if [ $TEST = 1 ]; then
        say "FAILED: the battery did not answer. The program is installed; check that the cable is in the"
        say "CONSOLE port of the master module (the one connected to the Cerbo by BMS-CAN)."
    fi
    say "Raw replies of the battery: $BASE/diagnostics.txt"
fi

# -- done --------------------------------------------------------------------------------------
step "Done"
say "Node-RED: Menu > Import > Local (library) > pylontech-remote > Import, then Deploy."
say "          (updating: delete the old Battery tab first)"
say "Dashboard: https://<cerbo-ip>:1881/dashboard/battery   (VRM: Venus OS Large > Node-RED Dashboard 2.0)"
say "Logs:      $BASE/boot.log, $BASE/adapter.log (cable search)   Uninstall: sh $BASE/uninstall.sh"
[ "$DRY" = 1 ] && say "*** DRY RUN: nothing was changed ***"
# battery not reached: keep searching / checking in the background (pylontech_adopt.py)
[ "$TEST" = 1 ] && sh "$BASE/boot.sh" adopt
exit $((TEST * 3))
