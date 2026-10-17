#!/bin/sh
# pylontech-remote installer for Victron Venus OS (Cerbo GX). Run as root on the Cerbo:
#
#   wget -O /tmp/pylontech-install.sh https://raw.githubusercontent.com/Mejchalos/pylontech-remote/main/install.sh
#   sh /tmp/pylontech-install.sh
#
# Installs or updates the program in /data/pylontech, keeps Venus OS's serial-starter away from
# the battery console (udev rule restored at every boot from /data, so it survives Venus OS
# updates) and prepares the Node-RED flow. Every change is shown before it is made.
#
# Options:
#   --dry-run       show what would be done, change nothing
#   --reconfigure   choose the USB adapter again
#   --yes           no questions (fails if the adapter is not unambiguous)
#   --source DIR    install from an unpacked copy of the repository instead of downloading
#   --branch NAME   download this branch (default: main)
#
# The battery only ever receives read commands (one test read at the end).

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
prop() { udevadm info -q property -n "$1" 2>/dev/null | sed -n "s/^$2=//p"; }

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
if ps | grep -v grep | grep -q -E 'pylontech_(live|export)\.py'; then
    die "Live or a log export is running - stop it in the dashboard first"
fi

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
else
    ORIGIN="local copy $SRC"
fi
for f in pylontech_live.py pylontech_export.py pylontech_remote/session.py venus/boot.sh uninstall.sh nodered/pylontech_flow.json; do
    [ -f "$SRC/$f" ] || die "$SRC/$f missing - not a pylontech-remote source"
done
say "source: $SRC"

# -- 3. install the program --------------------------------------------------------------------
step "Installing into $BASE"
if [ -d "$BASE/app" ]; then say "existing installation found - updating the program, keeping settings, state and exports"; fi
do_ "mkdir -p '$BASE/app/pylontech_remote' '$BASE/state' '$BASE/exports' '$BASE/backup'"
do_ "rm -rf '$BASE/app/pylontech_remote/__pycache__' '$BASE/app/__pycache__'"
do_ "cp '$SRC/pylontech_live.py' '$SRC/pylontech_export.py' '$BASE/app/'"
do_ "cp '$SRC'/pylontech_remote/*.py '$BASE/app/pylontech_remote/'"
do_ "chmod 755 '$BASE/app/pylontech_live.py' '$BASE/app/pylontech_export.py'"
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
if [ -f "$BASE/udev.rules" ] && [ "$RECONF" = 0 ]; then
    say "already configured (use --reconfigure to choose again):"
    sed 's/^/   /' "$BASE/udev.rules"
else
    n=0; list=''
    for d in /sys/class/tty/ttyUSB* /sys/class/tty/ttyACM*; do
        [ -e "$d" ] || continue
        dev=/dev/$(basename "$d")
        n=$((n + 1)); list="$list $dev"
        model=$(prop "$dev" ID_MODEL); drv=$(prop "$dev" ID_USB_DRIVER); serial=$(prop "$dev" ID_SERIAL_SHORT)
        service=$(prop "$dev" VE_SERVICE); holder=$(fuser "$dev" 2> /dev/null)
        note=''
        case "$model" in VE_Direct_cable|MK3-USB_Interface|USB-RS485_Cable|USB485_Iso_stick) note=' <- Victron device, not the battery console' ;; esac
        say "  $n) $dev  $drv  $model  serial=${serial:-none}  usb=$(prop "$dev" ID_PATH)  Venus OS: ${service:-?}${holder:+  in use by pid$holder}$note"
    done
    [ "$n" -gt 0 ] || die "no USB serial adapter found - plug in the console cable and run again"
    if [ "$n" = 1 ]; then
        choice=1
    elif [ "$YES" = 1 ]; then
        die "$n adapters found - run without --yes and choose one"
    else
        printf 'Which one is the battery console cable? [1-%s] ' "$n"
        read -r choice < /dev/tty || die "no answer"
    fi
    dev=$(echo $list | cut -d' ' -f"$choice")
    [ -n "$dev" ] || die "invalid choice"
    serial=$(prop "$dev" ID_SERIAL_SHORT); path=$(prop "$dev" ID_PATH)
    if [ -n "$serial" ]; then
        # adapter with a serial number (FTDI): the rule follows the cable to any USB socket
        rule="ACTION==\"add\", SUBSYSTEM==\"tty\", ENV{ID_SERIAL_SHORT}==\"$serial\", ENV{VE_SERVICE}=\"ignore\", SYMLINK+=\"ttyPYLON\""
        match="ID_SERIAL_SHORT=$serial"
        say "$dev has serial number $serial: the rule follows this cable to any USB socket."
    else
        # no serial number (e.g. CH340): vendor/product in this USB socket
        rule="ACTION==\"add\", SUBSYSTEM==\"tty\", ENV{ID_VENDOR_ID}==\"$(prop "$dev" ID_VENDOR_ID)\", ENV{ID_MODEL_ID}==\"$(prop "$dev" ID_MODEL_ID)\", ENV{ID_PATH}==\"$path\", ENV{VE_SERVICE}=\"ignore\", SYMLINK+=\"ttyPYLON\""
        match="ID_PATH=$path"
        say "$dev has no serial number: the rule is bound to this USB socket ($path)."
        say "If the cable is moved to another USB socket, run the installer again with --reconfigure."
    fi
    say "udev rule (Venus OS leaves this adapter alone; fixed name /dev/ttyPYLON):"
    say "   $rule"
    ask "Use $dev as the battery console?" || die "cancelled"
    do_ "echo '$rule' > '$BASE/udev.rules'"
    do_ "echo '$match' > '$BASE/udev.match'"
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
do_ "'$BASE/boot.sh'"
if [ "$DRY" = 0 ]; then
    sed 's/^/   /' "$BASE/boot.log"
    i=0
    while [ -e /dev/ttyPYLON ] && fuser /dev/ttyPYLON > /dev/null 2>&1 && [ $i -lt 15 ]; do sleep 1; i=$((i + 1)); done
fi

# -- 7. test read ------------------------------------------------------------------------------
step "Reading the battery (pwr, bat, info, stat, config - read only)"
if [ "$DRY" = 1 ]; then
    say "   [dry-run] skipped"
elif [ ! -e /dev/ttyPYLON ]; then
    say "skipped: /dev/ttyPYLON missing (cable not plugged in?)"
elif fuser /dev/ttyPYLON > /dev/null 2>&1; then
    say "skipped: the port is in use (pid $(fuser /dev/ttyPYLON 2> /dev/null))"
else
    python3 "$BASE/app/pylontech_live.py" --port /dev/ttyPYLON --once --state-file '' > /tmp/pylontech-test.json 2> /tmp/pylontech-test.err
    python3 - /tmp/pylontech-test.json << 'EOF' || say "test read failed - see /tmp/pylontech-test.err"
import json, sys
snap = json.loads(open(sys.argv[1]).read().strip().splitlines()[-1])
if not snap.get('ok'):
    sys.exit(1)
for m in snap['modules']:
    print('   M%-2d %-8s %-18s fw %-12s %3s%%  %d cells' % (m['id'], m['model'], m['barcode'], m['fw'], m['soc_pct'], m['n_cells']))
EOF
fi

# -- done --------------------------------------------------------------------------------------
step "Done"
say "Node-RED: Menu > Import > Local (library) > pylontech-remote > Import, then Deploy."
say "          (updating: delete the old Battery tab first)"
say "Dashboard: http://<cerbo-ip>:1880/dashboard/battery"
say "Boot log:  $BASE/boot.log   Uninstall: sh $BASE/uninstall.sh"
[ "$DRY" = 1 ] && say "*** DRY RUN: nothing was changed ***"
exit 0
