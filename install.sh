#!/bin/sh
# ─────────────────────────────────────────────────────────────────────────────
# pylontech-rs232-venus — installer for Victron Cerbo GX / Venus OS
#
# What it does:
#   1. Auto-detects the FTDI USB/RS232 adapter and its serial number
#   2. Writes a udev rule so Venus OS serial-starter releases the port
#      (otherwise gps_dbus grabs it and steals the bytes)
#   3. Reloads udev + restarts serial-starter
#   4. Ensures python3 + pyserial are available
#   5. Installs the reader to /data/pylontech_reader.py
#
# After this: import nodered/pylontech_flow.json into Node-RED and Deploy.
#
# Usage:  sh install.sh            (auto-detect port)
#         PYLONTECH_PORT=/dev/ttyUSB1 sh install.sh   (force a port)
# ─────────────────────────────────────────────────────────────────────────────
set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
RULE_NAME="99-pylontech-ftdi.rules"
READER_DST="/data/pylontech_reader.py"

echo "=== pylontech-rs232-venus installer ==="

# --- 0. root check ---------------------------------------------------------
if [ "$(id -u)" != "0" ]; then
    echo "ERROR: run as root (ssh root@<cerbo-ip>)." >&2
    exit 1
fi

# --- 1. detect the FTDI serial adapter -------------------------------------
PORT="${PYLONTECH_PORT:-}"
SERIAL=""

detect_serial() {
    # echo "ID_SERIAL_SHORT" for given tty if it is an FTDI (vendor 0403)
    _dev="$1"
    udevadm info -q property -n "$_dev" 2>/dev/null | awk -F= '
        /^ID_VENDOR_ID=/ {vid=$2}
        /^ID_SERIAL_SHORT=/ {ser=$2}
        END { if (vid=="0403") print ser }'
}

if [ -n "$PORT" ]; then
    echo "Using forced port: $PORT"
    SERIAL=$(udevadm info -q property -n "$PORT" 2>/dev/null | awk -F= '/^ID_SERIAL_SHORT=/{print $2}')
else
    for dev in /dev/ttyUSB*; do
        [ -e "$dev" ] || continue
        s=$(detect_serial "$dev")
        if [ -n "$s" ]; then
            PORT="$dev"; SERIAL="$s"
            echo "Detected FTDI adapter: $PORT  (serial $SERIAL)"
            break
        fi
    done
fi

if [ -z "$PORT" ]; then
    echo "ERROR: no FTDI USB/RS232 adapter found on /dev/ttyUSB*." >&2
    echo "       Plug it in and re-run, or set PYLONTECH_PORT=/dev/ttyUSBx." >&2
    exit 1
fi

# --- 2. write udev rule ----------------------------------------------------
mkdir -p /etc/udev/rules.d /data/etc/udev/rules.d
if [ -n "$SERIAL" ]; then
    RULE="ACTION==\"add\", SUBSYSTEM==\"tty\", ENV{ID_SERIAL_SHORT}==\"$SERIAL\", ENV{VE_SERVICE}=\"ignore\""
    echo "Writing udev rule by serial ($SERIAL) — safe, won't affect other FTDI devices."
else
    # fallback: match any FTDI tty (use only if the adapter has no serial)
    RULE="ACTION==\"add\", SUBSYSTEM==\"tty\", ATTRS{idVendor}==\"0403\", ENV{VE_SERVICE}=\"ignore\""
    echo "WARN: adapter reports no serial number — matching ALL FTDI tty devices."
fi
echo "$RULE" > "/etc/udev/rules.d/$RULE_NAME"
cp "/etc/udev/rules.d/$RULE_NAME" "/data/etc/udev/rules.d/$RULE_NAME"   # survive OS update
echo "  -> /etc/udev/rules.d/$RULE_NAME"
echo "  -> /data/etc/udev/rules.d/$RULE_NAME"

# --- 3. reload udev + restart serial-starter -------------------------------
udevadm control --reload-rules
PORTBASE=$(basename "$PORT")
udevadm trigger --name-match="$PORTBASE" 2>/dev/null || udevadm trigger
if [ -e /service/serial-starter ]; then
    svc -d /service/serial-starter; sleep 1; svc -u /service/serial-starter
fi
sleep 1
echo "VE_SERVICE for $PORT: $(udevadm info -q property -n "$PORT" 2>/dev/null | awk -F= '/^VE_SERVICE=/{print $2}')"

# --- 4. python3 + pyserial -------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found on this Venus OS image." >&2
    exit 1
fi
if ! python3 -c "import serial" 2>/dev/null; then
    echo "pyserial missing — attempting install..."
    if command -v opkg >/dev/null 2>&1; then
        opkg update >/dev/null 2>&1 && opkg install python3-pyserial || true
    fi
    if ! python3 -c "import serial" 2>/dev/null && command -v pip3 >/dev/null 2>&1; then
        pip3 install pyserial || true
    fi
    if ! python3 -c "import serial" 2>/dev/null; then
        echo "WARN: could not auto-install pyserial. Install it manually:" >&2
        echo "      opkg install python3-pyserial   OR   pip3 install pyserial" >&2
    fi
else
    echo "pyserial: OK"
fi

# --- 5. install reader -----------------------------------------------------
cp "$SCRIPT_DIR/pylontech_reader.py" "$READER_DST"
chmod +x "$READER_DST"
echo "Reader installed: $READER_DST"
if [ "$PORT" != "/dev/ttyUSB0" ]; then
    echo "NOTE: your adapter is on $PORT (not the default /dev/ttyUSB0)."
    echo "      Set PYLONTECH_PORT in the Node-RED exec node, or symlink, or export it."
fi

# --- 6. quick self-test ----------------------------------------------------
echo "=== self-test (reading battery, ~60-90s) ==="
if PYLONTECH_PORT="$PORT" python3 "$READER_DST" | head -c 400; then
    echo ""
    echo ""
    echo "=== DONE ==="
    echo "Next steps:"
    echo "  1. Node-RED must have @flowfuse/node-red-dashboard (Dashboard 2.0) installed."
    echo "  2. Import nodered/pylontech_flow.json (Menu -> Import) and Deploy."
    echo "  3. Open the dashboard at  http://<cerbo-ip>:1880/dashboard/battery"
else
    echo "Self-test failed — check wiring / udev rule (see README troubleshooting)."
fi
