#!/bin/sh
# pylontech-remote: runs at every boot from /data/rcS.local, before Venus OS starts serial-starter.
#
# Keeps serial-starter away from the battery console: the udev rule saved by the installer in
# /data/pylontech/udev.rules is put into /run/udev/rules.d (rebuilt at every boot, so it survives
# Venus OS updates without touching /etc) and applied to the console adapter only.
# The rule also gives the adapter a fixed name, /dev/ttyPYLON.

BASE=/data/pylontech
RULE=$BASE/udev.rules
MATCH=$BASE/udev.match
RUN_RULE=/run/udev/rules.d/zz-pylontech-console.rules
LOG=$BASE/boot.log

{
    echo "$(date '+%Y-%m-%d %H:%M:%S') pylontech-remote boot"
    if [ ! -f "$RULE" ] || [ ! -f "$MATCH" ]; then
        echo "no adapter configured ($RULE) - nothing to do"
        exit 0
    fi
    mkdir -p /run/udev/rules.d
    cp "$RULE" "$RUN_RULE"
    udevadm control --reload-rules
    # re-run the rules for the console adapter only (one property, e.g. ID_SERIAL_SHORT=... )
    udevadm trigger --action=add --subsystem-match=tty --property-match="$(cat "$MATCH")"
    udevadm settle -t 5
    if [ -e /dev/ttyPYLON ]; then
        dev=$(readlink -f /dev/ttyPYLON)
        echo "adapter: $dev, $(udevadm info -q property -n "$dev" | grep '^VE_SERVICE=')"
    else
        echo "adapter not connected (no /dev/ttyPYLON)"
    fi
} > "$LOG" 2>&1

exit 0
