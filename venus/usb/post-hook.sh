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
#
# A stick left in the Cerbo is processed again at boot; then nothing is done if this version is
# already installed.

PATH=/usr/sbin:/usr/bin:/sbin:/bin
SRC=/data/pylontech-install
RUN=/tmp/pylontech-install.run
LOG=/tmp/pylontech-install.log
ID=$(get-unique-id 2> /dev/null)
[ -n "$ID" ] || ID=unknown

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
