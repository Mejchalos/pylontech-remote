#!/bin/sh
# pylontech-remote: install from a USB stick, without SSH. The stick is reusable: plug it into a
# Cerbo, wait a minute, pull it out, go to the next installation.
#
# Venus OS unpacks venus-runtime-pylontech-install.tar.gz from an inserted USB stick into /data and
# then runs this script as root (see /etc/init.d/update-data.sh). It runs the normal installer
# without questions (an existing installation is updated; settings and exports are kept).
#
# On the stick, per Cerbo (VRM portal ID):
#   pylontech-results.txt                   one line per installation: date, Cerbo, result
#   pylontech-logs/<id>-install-log.txt     the installer's output, newest run first
#   pylontech-logs/<id>-diagnostics.txt     the battery's raw replies (contain serial numbers)
#   pylontech-logs/<id>-state.txt           the USB serial adapters before the installer runs
#
# A stick left in the Cerbo is processed again at boot; then nothing is done if this version is
# already installed.

PATH=/usr/sbin:/usr/bin:/sbin:/bin
SRC=/data/pylontech-install
RUN=/tmp/pylontech-install.run
LOG=/tmp/pylontech-install.log
ID=$(get-unique-id 2> /dev/null)
[ -n "$ID" ] || ID=unknown

# The USB serial adapters as they are now, before the installer changes anything (to find out
# why a cable was not found): pylontech-logs/<id>-state.txt, newest first.
state() {
    echo "pylontech-remote adapter state, $(date '+%Y-%m-%d %H:%M:%S'), Cerbo $ID, up $(cut -d' ' -f1 /proc/uptime) s"
    echo; echo '## devices'
    ls -l /dev/ttyPYLON /dev/ttyUSB* /dev/serial-starter/ 2>&1
    for d in /dev/ttyUSB*; do
        [ -e "$d" ] || continue
        echo; echo "## $d"
        udevadm info -q property -n "$d" 2>&1 \
            | grep -E '^(ID_USB_DRIVER|ID_MODEL|ID_SERIAL_SHORT|ID_PATH|VE_SERVICE|DEVLINKS)='
        for p in /proc/[0-9]*; do
            ls -l "$p/fd" 2> /dev/null | grep -q " $d\$" \
                && echo "open by pid ${p#/proc/}: $(tr '\0' ' ' < "$p/cmdline")"
        done
    done
    echo; echo '## Venus OS services on USB serial adapters'
    ls /service 2> /dev/null | grep -i ttyUSB
    echo; echo '## udev rules'
    for f in /run/udev/rules.d/zz-pylontech-*.rules /data/pylontech/udev.rules /data/pylontech/udev.match; do
        echo "-- $f"; cat "$f" 2>&1
    done
    echo; echo '## running'
    ps | grep -E 'pylontech_|serial-starter' | grep -v grep
    echo; echo '## kernel (USB plug-in / unplug)'
    dmesg 2> /dev/null | grep -iE 'ttyUSB|ftdi|ch341|usb [0-9-]+(\.[0-9]+)*: (new|USB disconnect)' | tail -n 40
    echo; echo '## /data/pylontech/boot.log'
    cat /data/pylontech/boot.log 2>&1
    echo; echo '## /data/pylontech/adapter.log (end)'
    tail -n 60 /data/pylontech/adapter.log 2>&1
}
state > /tmp/pylontech-state.txt 2>&1
for a in /media/*/venus-runtime-pylontech-install*.tar.gz; do
    [ -f "$a" ] || continue
    out="$(dirname "$a")/pylontech-logs/$ID-state.txt"
    mkdir -p "$(dirname "$out")"
    { cat /tmp/pylontech-state.txt; printf '\n\n========== earlier ==========\n\n'
      [ -f "$out" ] && head -n 1500 "$out"; } > "$out.new" && mv "$out.new" "$out"
done

uptime=$(cut -d. -f1 /proc/uptime)
if [ "$uptime" -lt 300 ] && [ -f "$SRC/VERSION" ] && [ -f /data/pylontech/VERSION ] \
        && grep -qF "$(cat "$SRC/VERSION")" /data/pylontech/VERSION; then
    rm -rf "$SRC"
    for a in /media/*/venus-runtime-pylontech-install*.tar.gz; do
        [ -f "$a" ] && echo "$(date '+%Y-%m-%d %H:%M')  Cerbo $ID  ALREADY INSTALLED (this version) - nothing done" \
            >> "$(dirname "$a")/pylontech-results.txt"
    done
    sync
    exit 0
fi

{
    echo "pylontech-remote USB install, $(date '+%Y-%m-%d %H:%M:%S'), Cerbo $ID"
    if [ "$1" = success ] && [ -f "$SRC/install.sh" ]; then
        sh "$SRC/install.sh" --yes --source "$SRC"
        code=$?
    else
        echo "unpacking the archive failed ($1)"
        code=1
    fi
    echo "installer exit code: $code"
} > "$RUN" 2>&1

case $code in
    0) result='OK - installed, the battery answered' ;;
    3) result='INSTALLED, BATTERY NOT REACHED YET - plug the cable into the battery: it is found automatically' ;;
    *) result='FAILED - see the ERROR line in the log, fix it and plug the stick in again' ;;
esac
{ echo "RESULT: $result"; echo; cat "$RUN"; } > "$LOG"

# newest run first, earlier runs below
keep() {
    if [ -f "$1" ]; then
        { cat "$LOG"; printf '\n\n========== earlier ==========\n\n'; head -n 2000 "$1"; } > "$1.new" && mv "$1.new" "$1"
    else
        cp "$LOG" "$1"
    fi
}

[ -d /data/pylontech ] && keep /data/pylontech/install.log
rm -rf "$SRC"

for a in /media/*/venus-runtime-pylontech-install*.tar.gz; do
    [ -f "$a" ] || continue
    stick=$(dirname "$a")
    mkdir -p "$stick/pylontech-logs"
    keep "$stick/pylontech-logs/$ID-install-log.txt"
    [ -f /data/pylontech/diagnostics.txt ] && cp /data/pylontech/diagnostics.txt "$stick/pylontech-logs/$ID-diagnostics.txt"
    echo "$(date '+%Y-%m-%d %H:%M')  Cerbo $ID  $result" >> "$stick/pylontech-results.txt"
done
sync
exit 0
