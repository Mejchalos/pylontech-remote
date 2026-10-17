#!/bin/sh
# pylontech-remote: uninstall from a USB stick, without SSH.
#
# Venus OS unpacks venus-runtime-pylontech-uninstall.tar.gz from an inserted USB stick into /data
# and then runs this script as root (see /etc/init.d/update-data.sh). It runs the uninstaller
# without questions: boot hook, udev rule and /data/pylontech including the exported logs are
# removed. The result goes next to the archive on the stick (pylontech-uninstall-log.txt); the
# archive is renamed so that it runs only once. Delete the Battery tab in Node-RED yourself.

PATH=/usr/sbin:/usr/bin:/sbin:/bin
SRC=/data/pylontech-uninstall
LOG=/tmp/pylontech-uninstall.log

{
    echo "pylontech-remote USB uninstall, $(date '+%Y-%m-%d %H:%M:%S')"
    if [ "$1" = success ] && [ -f "$SRC/uninstall.sh" ]; then
        sh "$SRC/uninstall.sh" --yes
        echo "uninstaller exit code: $?"
    else
        echo "unpacking the archive failed ($1)"
    fi
} > "$LOG" 2>&1

rm -rf "$SRC"

for a in /media/*/venus-runtime-pylontech-uninstall*.tar.gz; do
    [ -f "$a" ] || continue
    cp "$LOG" "$(dirname "$a")/pylontech-uninstall-log.txt"
    mv "$a" "$a.done"
done
sync
exit 0
