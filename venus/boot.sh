#!/bin/sh
# pylontech-remote: runs at every boot from /data/rcS.local, before Venus OS starts serial-starter.
#
# Keeps serial-starter away from the battery console: the udev rule saved in
# /data/pylontech/udev.rules is put into /run/udev/rules.d (rebuilt at every boot, so it survives
# Venus OS updates without touching /etc) and applied to the console adapter only.
# The rule also gives the adapter a fixed name, /dev/ttyPYLON.
#
# pylontech_adopt.py, started here at boot and by a udev rule whenever a USB serial adapter is
# plugged in, looks for the console while /dev/ttyPYLON is missing (no cable configured yet, or
# the cable was replaced) and checks a cable bound to a USB socket (CH340) when it appears.
# Log: /data/pylontech/adapter.log.
#
#   boot.sh           at boot: apply the rules, then check / search in the background
#   boot.sh apply     apply the rules only (installer, after a new cable was adopted)
#   boot.sh adopt     check / search in the background (udev, installer)

BASE=/data/pylontech
RULE=$BASE/udev.rules
MATCH=$BASE/udev.match
RUN_RULE=/run/udev/rules.d/zz-pylontech-console.rules
WATCH_RULE=/run/udev/rules.d/zz-pylontech-watch.rules
LOG=$BASE/boot.log

search() {
    [ -f "$BASE/app/pylontech_adopt.py" ] || return 0
    setsid /usr/bin/python3 "$BASE/app/pylontech_adopt.py" --wait "$1" < /dev/null > /dev/null 2>&1 3>&- &
}

if [ "$1" = adopt ]; then
    search 60
    exit 0
fi

# at boot a new log; later runs are added to it
if [ -z "$1" ]; then exec 3> "$LOG"; else exec 3>> "$LOG"; fi
{
    echo "$(date '+%Y-%m-%d %H:%M:%S') pylontech-remote boot${1:+ ($1)}"
    mkdir -p /run/udev/rules.d
    echo 'ACTION=="add", SUBSYSTEM=="tty", KERNEL=="ttyUSB[0-9]*", RUN+="/bin/sh /data/pylontech/boot.sh adopt"' > "$WATCH_RULE"
    if [ -f "$RULE" ] && [ -f "$MATCH" ]; then
        cp "$RULE" "$RUN_RULE"
        udevadm control --reload-rules
        # re-run the rules for the console adapter only (one property, e.g. ID_SERIAL_SHORT=... )
        udevadm trigger --action=add --subsystem-match=tty --property-match="$(cat "$MATCH")"
        udevadm settle -t 5
    else
        rm -f "$RUN_RULE"
        udevadm control --reload-rules
        echo "no cable configured yet ($RULE)"
    fi
    if [ -e /dev/ttyPYLON ]; then
        dev=$(readlink -f /dev/ttyPYLON)
        echo "adapter: $dev, $(udevadm info -q property -n "$dev" | grep '^VE_SERVICE=')"
    else
        echo "battery console cable not connected (no /dev/ttyPYLON)"
    fi
    if [ -z "$1" ]; then
        echo "cable check / search in the background (see $BASE/adapter.log)"
        search 120
    fi
} >&3 2>&1

exit 0
