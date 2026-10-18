#!/usr/bin/env python3
"""Find the battery console cable among the Cerbo's USB serial adapters and keep Venus OS away
from it (the udev rule in /data/pylontech, applied by boot.sh). Runs as root.

    pylontech_adopt.py [--wait S]      started by boot.sh at boot and whenever a USB serial adapter
                                       is plugged in (udev): checks or searches, see below
    pylontech_adopt.py --once [--wait S]   one search (the installer)
    pylontech_adopt.py --list          the adapters and whether each one may be the console
    pylontech_adopt.py --use DEV       save the rule for DEV (the installer, after asking)

Only the battery's own answer counts: Enter is answered with the Pylontech prompt ("pylon>").
Timing: pylontech_remote/adapters.py.

Cable missing (/dev/ttyPYLON): search. First Venus OS gets a head start (--wait) to find its own
devices. Then each adapter that may be the console (a USB serial converter, not a Victron device,
no device found on it by Venus OS) is asked: Venus OS lets go of it (its own stop-tty.sh), it gets
Enter, the console is adopted, any other adapter goes straight back (start-tty.sh). While such an
adapter stays silent (battery off, cable not in the battery) it is asked again: every 10 min for
the first hour, then once an hour. Adapters Venus OS uses are never asked.

Cable bound to a USB socket (CH340, no serial number): whenever it appears it is checked, because
another CH340 in the same socket would match the rule too. Silent: asked again every 2 min for
30 min. Something else answers, or still silent after 30 min: the adapter goes to Venus OS (rule
moved to backup/) and the search above takes over. A cable with a serial number (FTDI) is not
checked: the rule matches that one cable only.

Log: /data/pylontech/adapter.log (changes only).
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pylontech_remote import adapters                                            # noqa: E402
from pylontech_remote.session import ConsoleSession, ConsoleError, port_holders  # noqa: E402

SERIAL_STARTER = '/opt/victronenergy/serial-starter'
RUN_RULE = '/run/udev/rules.d/zz-pylontech-console.rules'
CONSOLE = '/dev/ttyPYLON'
LOG_LIMIT = 64 * 1024

BASE = '/data/pylontech'
ignore_wake_until = 0.0     # wake-ups caused by our own udev triggers


def log(msg):
    line = '%s %s' % (time.strftime('%Y-%m-%d %H:%M:%S'), msg)
    print(line)
    sys.stdout.flush()
    path = os.path.join(BASE, 'adapter.log')
    try:
        if os.path.exists(path) and os.path.getsize(path) > LOG_LIMIT:
            with open(path, 'rb') as f:
                f.seek(-LOG_LIMIT // 2, os.SEEK_END)
                tail = f.read()
            with open(path, 'wb') as f:
                f.write(tail[tail.find(b'\n') + 1:])
        with open(path, 'a') as f:
            f.write(line + '\n')
    except OSError:
        pass


def wake_file():
    return os.path.join(BASE, 'state', 'adopt.wake')


def sleep_wake(seconds):
    """Sleep; True as soon as a USB serial adapter was plugged in meanwhile (udev -> boot.sh)."""
    end = time.time() + seconds
    while time.time() < end:
        try:
            if os.path.getmtime(wake_file()) >= ignore_wake_until:
                os.remove(wake_file())
                return True
            os.remove(wake_file())
        except OSError:
            pass
        time.sleep(min(5, max(0, end - time.time())))
    return False


def head_start(seconds):
    """Give Venus OS its head start in full (plug-in wake-ups do not shorten it)."""
    end = time.time() + seconds
    while time.time() < end:
        sleep_wake(end - time.time())


def ttys():
    return sorted(os.path.basename(p) for p in glob.glob('/sys/class/tty/ttyUSB*'))


def props(tty):
    try:
        out = subprocess.run(['udevadm', 'info', '-q', 'property', '-n', '/dev/' + tty],
                             stdout=subprocess.PIPE, universal_newlines=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    return adapters.parse_props(out)


def venus_services():
    """[(name, /Mgmt/Connection)] of the Venus OS services on D-Bus, or None if D-Bus cannot be
    read (then nothing is searched: which adapters Venus OS uses would be unknown)."""
    try:
        import dbus
        bus = dbus.SystemBus()
        names = [str(n) for n in bus.list_names() if str(n).startswith('com.victronenergy.')]
    except Exception:
        return None
    services = []
    for name in names:
        try:
            item = bus.get_object(name, '/Mgmt/Connection', introspect=False)
            connection = str(item.GetValue(dbus_interface='com.victronenergy.BusItem', timeout=3))
        except Exception:
            connection = ''
        services.append((name, connection))
    return services


def in_use(tty, services):
    svc = adapters.used_by_venus(tty, services)
    return svc and 'in use by Venus OS: %s' % svc


def serial_starter(script, tty):
    path = os.path.join(SERIAL_STARTER, script)
    if not os.path.exists(path):
        return False
    try:
        subprocess.run(['sh', path, tty], timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        log('   %s %s: %s' % (script, tty, e))
        return False
    return True


def wait_free(dev, seconds):
    end = time.time() + seconds
    while time.time() < end:
        if not port_holders(dev):
            return True
        time.sleep(1)
    return False


def held_by_us(pids):
    """Live or a log export has the port: it is in use as the battery console."""
    for pid in pids:
        try:
            with open('/proc/%d/cmdline' % pid, 'rb') as f:
                cmdline = f.read()
            if b'pylontech_live' in cmdline or b'pylontech_export' in cmdline:
                return True
        except OSError:
            pass
    return False


def probe(dev):
    """Send Enter (the session's opening, nothing else) and classify the answer:
    ('console'|'other'|'silent'|'busy', last line received or error)."""
    session = ConsoleSession(dev)
    received = []
    command = session.command

    def recorded(cmd, *args, **kw):
        reply = command(cmd, *args, **kw)
        received.append(reply.stale + reply.data)
        return reply
    session.command = recorded
    try:
        session.open(check_holders=False)
    except ConsoleError:
        pass
    except Exception as e:      # cannot open the port
        return 'busy', str(e)
    finally:
        session.close()
    data = b''.join(received)
    lines = data.strip().splitlines()
    return adapters.answer_kind(data), (lines[-1][-60:].decode('ascii', 'replace') if lines else '')


def save_rule(p, dry=False):
    rule, match = adapters.rule_for(p)
    print('udev rule (Venus OS leaves this adapter alone; fixed name /dev/ttyPYLON):')
    print('   ' + rule)
    if dry:
        print('   [dry-run] not saved')
        return
    backup_rule('')
    with open(os.path.join(BASE, 'udev.rules'), 'w') as f:
        f.write(rule + '\n')
    with open(os.path.join(BASE, 'udev.match'), 'w') as f:
        f.write(match + '\n')


def backup_rule(tag, move=False):
    stamp = time.strftime('%Y%m%d%H%M%S')
    os.makedirs(os.path.join(BASE, 'backup'), exist_ok=True)
    for name in ('udev.rules', 'udev.match'):
        path = os.path.join(BASE, name)
        if os.path.exists(path):
            target = os.path.join(BASE, 'backup', '%s.%s%s' % (name, tag, stamp))
            (shutil.move if move else shutil.copy)(path, target)


def socket_bound():
    try:
        with open(os.path.join(BASE, 'udev.match')) as f:
            return f.read().startswith('ID_PATH=')
    except OSError:
        return False


def release(tty, why):
    """The adapter in the cable's USB socket is not the battery console: give it to Venus OS."""
    global ignore_wake_until
    log('   /dev/%s: %s - not the battery console; it goes to Venus OS (rule moved to %s/backup/)'
        % (tty, why, BASE))
    backup_rule('released.', move=True)
    try:
        os.remove(RUN_RULE)
    except OSError:
        pass
    subprocess.run(['udevadm', 'control', '--reload-rules'], timeout=30)
    subprocess.run(['udevadm', 'trigger', '--action=add', '--sysname-match=' + tty], timeout=30)
    subprocess.run(['udevadm', 'settle', '-t', '5'], timeout=30)
    ignore_wake_until = time.time() + 15


def verify():
    """Check the socket-bound cable that just appeared. True: it is the console (or in use as
    such); False: it was given to Venus OS."""
    time.sleep(adapters.VERIFY_DELAY)
    end = time.time() + adapters.VERIFY_WINDOW
    others = 0
    said = False
    while os.path.exists(CONSOLE):
        dev = os.path.realpath(CONSOLE)
        tty = os.path.basename(dev)
        holders = port_holders(dev)
        if holders and held_by_us(holders):
            return True
        if not holders:
            kind, detail = probe(dev)
            if kind == 'console':
                log('   %s (/dev/%s): battery console confirmed (prompt "%s")' % (CONSOLE, tty, detail))
                return True
            others = others + 1 if kind == 'other' else 0
            if others >= 2:
                release(tty, 'answers "%s"' % detail)
                return False
            if not said:
                log('   %s (/dev/%s): no answer from the battery console - asking again every %d min for %d min'
                    % (CONSOLE, tty, adapters.VERIFY_INTERVAL // 60, adapters.VERIFY_WINDOW // 60))
                said = True
        if time.time() >= end:
            release(tty, 'no answer for %d min' % (adapters.VERIFY_WINDOW // 60))
            return False
        sleep_wake(adapters.VERIFY_INTERVAL)
    return True     # unplugged: nothing to check


def search_pass(services, seen):
    """Ask every adapter that may be the console. 'adopted', 'waiting' (some were asked without
    a console answer: ask again later) or 'none' (nothing to ask)."""
    asked = False
    for tty in ttys():
        dev = '/dev/' + tty
        p = props(tty)
        why = adapters.excluded(p) or in_use(tty, services)
        if why:
            if seen.get(tty) != why:
                log('   %s: %s - skipped (%s)' % (dev, adapters.describe(p), why))
                seen[tty] = why
            continue
        asked = True
        stopped = serial_starter('stop-tty.sh', tty)
        if not wait_free(dev, 30):
            kind, detail = 'busy', 'in use by pid %s' % port_holders(dev)
        else:
            kind, detail = probe(dev)
        if kind == 'console':
            log('   %s: %s - battery console found (prompt "%s")' % (dev, adapters.describe(p), detail))
            try:
                save_rule(p)
            except (OSError, ValueError) as e:
                log('   cannot save the rule: %s' % e)
                if stopped:
                    serial_starter('start-tty.sh', tty)
                return 'none'
            subprocess.run(['sh', os.path.join(BASE, 'boot.sh'), 'apply'], timeout=60)
            log('   adopted: %s is now %s (rule in %s/udev.rules)' % (dev, CONSOLE, BASE)
                if os.path.exists(CONSOLE) else '   rule saved, but %s did not appear' % CONSOLE)
            return 'adopted'
        if stopped:
            serial_starter('start-tty.sh', tty)
        state = '%s: %s' % (kind, detail)
        if seen.get(tty) != state:
            text = {'silent': 'no answer', 'other': 'answers "%s"' % detail, 'busy': detail}[kind]
            log('   %s: %s - Venus OS found no device on it; asked with Enter: %s'
                % (dev, adapters.describe(p), text))
            seen[tty] = state
    return 'waiting' if asked else 'none'


def search(head, once=False):
    log('battery console cable not connected - searching the USB serial adapters in %d s' % head)
    head_start(head)
    seen = {}
    attempt = 0
    while True:
        if os.path.exists(CONSOLE):
            log('   %s is back' % CONSOLE)
            return 0
        services = venus_services()
        if services is None:
            log('   cannot read D-Bus (which adapters Venus OS uses) - not searching')
            return 1
        result = search_pass(services, seen)
        attempt += 1
        if result == 'adopted':
            return 0
        if once or result == 'none':
            log('   battery console not found%s' % ('' if once else
                ' - searching again when a USB serial adapter is plugged in, and at the next boot'))
            return 1
        delay = adapters.retry_delay(attempt)
        if attempt == 1 or delay != adapters.retry_delay(attempt - 1):
            log('   not found yet - asking these adapters again every %d min' % (delay // 60))
        if sleep_wake(delay):
            log('   a USB serial adapter was plugged in - searching in %d s' % adapters.HEAD_START)
            head_start(adapters.HEAD_START)
            seen.clear()


def run(head, once):
    if os.path.exists(CONSOLE):
        if once or not socket_bound() or verify():
            return 0
        head = adapters.HEAD_START
    return search(head, once)


def list_adapters():
    services = venus_services() or []
    found = ttys()
    for n, tty in enumerate(found, 1):
        p = props(tty)
        if os.path.realpath(CONSOLE) == '/dev/' + tty:
            why = 'the battery console (%s)' % CONSOLE
        else:
            why = adapters.excluded(p) or in_use(tty, services)
        print('  %d) /dev/%s  %s%s' % (n, tty, adapters.describe(p), '  <- %s' % why if why else ''))
    if not found:
        print('  no USB serial adapter')


def main():
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument('--wait', type=float, default=adapters.HEAD_START)
    ap.add_argument('--once', action='store_true')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--use', metavar='DEV')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--base', default=BASE)
    a = ap.parse_args()
    BASE = a.base

    if a.list:
        list_adapters()
        return 0
    if a.use:
        save_rule(props(os.path.basename(a.use)), dry=a.dry_run)
        return 0

    import fcntl
    os.makedirs(os.path.join(BASE, 'state'), exist_ok=True)
    lock = open(os.path.join(BASE, 'state', 'adopt.lock'), 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # one is running (maybe waiting for its next try): tell it an adapter was plugged in
        open(wake_file(), 'w').close()
        print('another search is running - woken up')
        return 0
    try:
        os.remove(wake_file())
    except OSError:
        pass
    return run(a.wait, a.once)


if __name__ == '__main__':
    sys.exit(main())
