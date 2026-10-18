"""USB serial adapters on the Cerbo: which one may be the battery console, and the udev rule for it.

Pure functions on udev properties (`udevadm info -q property`), so they can be tested anywhere.
"""
import re

# USB-serial converter chips a console cable is built with. Anything else (4G modems, GPS
# receivers, ...) is never touched.
CONVERTER_DRIVERS = ('ftdi_sio', 'ch341', 'cp210x', 'pl2303')

# Victron's own USB devices. FT232EX: VE.Direct cables without their own model name (Venus OS
# treats it as VE.Direct too).
VICTRON_MODELS = ('VE_Direct_cable', 'MK3-USB_Interface', 'USB-RS485_Cable', 'USB485_Iso_stick',
                  'FT232EX')

_SAFE = re.compile(r'^[A-Za-z0-9._:-]+$')

# The Pylontech console prompt ("pylon>", "pylon_debug>") at the end of the answer to Enter.
# Only this counts: whatever else answers is not the battery console.
PYLON_PROMPT = re.compile(rb'pylon[A-Za-z_]*>\s*$')

# Timing (seconds)
HEAD_START = 60            # after a USB serial adapter is plugged in: Venus OS finds its devices
HEAD_START_BOOT = 120      # the same after boot (all Venus OS services start)
VERIFY_DELAY = 10          # before checking a socket-bound adapter (CH340) that was plugged in
VERIFY_INTERVAL = 120      # silent socket-bound adapter: asked again every 2 min ...
VERIFY_WINDOW = 1800       # ... for 30 min, then it goes to Venus OS
RETRY_FIRST = 600          # adapters Venus OS does not use: asked again every 10 min ...
RETRY_FIRST_COUNT = 6      # ... for the first hour ...
RETRY_LATER = 3600         # ... then once an hour, until the battery answers


def answer_kind(received):
    """What answered Enter: 'console' (Pylontech prompt), 'other' (something else talks) or
    'silent' (nothing: battery off, cable not in the battery, or a device that only answers its
    own protocol, e.g. a Modbus energy meter)."""
    if PYLON_PROMPT.search(received):
        return 'console'
    return 'other' if received.strip() else 'silent'


def retry_delay(attempt):
    """Pause before the next search for an adapter Venus OS does not use; `attempt` = searches
    done so far (1 after the first)."""
    return RETRY_FIRST if attempt <= RETRY_FIRST_COUNT else RETRY_LATER


def parse_props(text):
    """`udevadm info -q property` output -> dict."""
    props = {}
    for line in text.splitlines():
        key, sep, value = line.partition('=')
        if sep:
            props[key.strip()] = value.strip()
    return props


def describe(props):
    serial = props.get('ID_SERIAL_SHORT') or 'none'
    return '%s %s, serial %s, USB socket %s' % (
        props.get('ID_USB_DRIVER', '?'), props.get('ID_MODEL', '?'), serial, props.get('ID_PATH', '?'))


def excluded(props):
    """Why this adapter cannot be the battery console, or None if it may be."""
    model = props.get('ID_MODEL', '')
    if model in VICTRON_MODELS or 'victron' in props.get('ID_VENDOR', '').lower():
        return 'Victron device'
    driver = props.get('ID_USB_DRIVER', '')
    if driver not in CONVERTER_DRIVERS:
        return 'not a USB serial converter (driver %s)' % (driver or 'unknown')
    if props.get('VE_SERVICE') == 'ignore':
        return 'reserved by another program'
    return None


def used_by_venus(tty, services):
    """The D-Bus service Venus OS created for a device it found on this tty, or None.

    `services`: (name, /Mgmt/Connection) of the com.victronenergy.* services. The tty is in the
    name (com.victronenergy.grid.cgwacs_ttyUSB0_mb1, com.victronenergy.vebus.ttyUSB1) or only in
    the connection (Modbus RTU meters: com.victronenergy.grid.cg_BY12345, "Modbus RTU ttyUSB0:1")."""
    pattern = re.compile(r'(?<![A-Za-z0-9])%s(?![0-9])' % re.escape(tty))
    for name, connection in services:
        if pattern.search(name) or pattern.search(connection or ''):
            return name
    return None


def rule_for(props):
    """(udev rule, property for `udevadm trigger --property-match`) for the console adapter.

    With a serial number (FTDI) the rule follows the cable to any USB socket; without one
    (CH340) it matches vendor/product in this USB socket."""
    serial = props.get('ID_SERIAL_SHORT', '')
    if serial and _SAFE.match(serial):
        return ('ACTION=="add", SUBSYSTEM=="tty", ENV{ID_SERIAL_SHORT}=="%s", '
                'ENV{VE_SERVICE}="ignore", SYMLINK+="ttyPYLON"' % serial,
                'ID_SERIAL_SHORT=%s' % serial)
    values = [props.get(k, '') for k in ('ID_VENDOR_ID', 'ID_MODEL_ID', 'ID_PATH')]
    if not all(_SAFE.match(v) for v in values):
        raise ValueError('adapter without usable USB ids: %s' % describe(props))
    return ('ACTION=="add", SUBSYSTEM=="tty", ENV{ID_VENDOR_ID}=="%s", ENV{ID_MODEL_ID}=="%s", '
            'ENV{ID_PATH}=="%s", ENV{VE_SERVICE}="ignore", SYMLINK+="ttyPYLON"' % tuple(values),
            'ID_PATH=%s' % values[2])
