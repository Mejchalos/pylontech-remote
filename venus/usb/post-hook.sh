#!/bin/sh
# pylontech-remote: install from a USB stick, without SSH.
#
# Venus OS unpacks venus-runtime-pylontech-install.tar.gz from an inserted USB stick into /data and
# then runs this script as root (see /etc/init.d/update-data.sh). It runs the normal installer
# without questions; the result goes to /data/pylontech/install.log and next to the archive on the
# stick (pylontech-install-log.txt). The archive is renamed so that it runs only once.

PATH=/usr/sbin:/usr/bin:/sbin:/bin
SRC=/data/pylontech-install
LOG=/tmp/pylontech-install.log

{
    echo "pylontech-remote USB install, $(date '+%Y-%m-%d %H:%M:%S')"
    if [ "$1" = success ] && [ -f "$SRC/install.sh" ]; then
        sh "$SRC/install.sh" --yes --source "$SRC"
        echo "installer exit code: $?"
    else
        echo "unpacking the archive failed ($1)"
    fi
} > "$LOG" 2>&1

[ -d /data/pylontech ] && cp "$LOG" /data/pylontech/install.log
rm -rf "$SRC"

for a in /media/*/venus-runtime-pylontech-install*.tar.gz /media/*/venus-runtime.tar.gz; do
    [ -f "$a" ] || continue
    cp "$LOG" "$(dirname "$a")/pylontech-install-log.txt"
    mv "$a" "$a.installed"
done
sync
exit 0
