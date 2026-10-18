"""The cable search and check (pylontech_adopt.py) with the Cerbo simulated: adapters, Venus OS
services and the answers to Enter are fakes, time runs on a fake clock."""
import os
import shutil
import tempfile
import unittest

import pylontech_adopt as adopt
from pylontech_remote import adapters

VICTRON = {'ID_USB_DRIVER': 'ftdi_sio', 'ID_MODEL': 'VE_Direct_cable', 'ID_SERIAL_SHORT': 'VE1'}
METER = {'ID_USB_DRIVER': 'ch341', 'ID_MODEL': 'USB_Serial', 'ID_VENDOR_ID': '1a86',
         'ID_MODEL_ID': '7523', 'ID_PATH': 'platform-a-usb-0:1:1.0'}
FTDI = {'ID_USB_DRIVER': 'ftdi_sio', 'ID_MODEL': 'FT232R_USB_UART', 'ID_VENDOR_ID': '0403',
        'ID_MODEL_ID': '6001', 'ID_SERIAL_SHORT': 'A10KXYZ1', 'ID_PATH': 'platform-b-usb-0:1:1.0'}


class FakeTime(object):
    def __init__(self):
        self.t = 1000000.0
        self.sleeps = []
        self.limit = None

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s
        self.sleeps.append(s)
        if self.limit is not None and self.t > self.limit:
            raise StopIteration('enough')

    def strftime(self, fmt, *a):
        return 'T'


class Cerbo(object):
    """Patches pylontech_adopt with a simulated Cerbo."""

    def __init__(self, test, adapters_, services=(), answers=None):
        self.test = test
        self.base = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.base, 'state'))
        self.adapters = dict(adapters_)
        self.services = list(services)
        self.answers = answers or {}          # tty -> list of answers (last one repeats)
        self.asked = []
        self.lines = []
        self.saved = []
        self.released = []
        self.console = os.path.join(self.base, 'ttyPYLON')     # stands for /dev/ttyPYLON
        self.clock = FakeTime()
        self._orig = {}
        patch = {
            'BASE': self.base, 'CONSOLE': self.console, 'time': self.clock,
            'ttys': lambda: sorted(self.adapters), 'props': lambda tty: self.adapters[tty],
            'venus_services': lambda: self.services, 'probe': self.probe,
            'serial_starter': lambda script, tty: True, 'wait_free': lambda dev, s: True,
            'port_holders': lambda dev: [], 'log': self.lines.append,
            'save_rule': lambda p, dry=False: self.saved.append(p), 'release': self.release,
            'subprocess': self, 'head_start': lambda s: self.clock.sleep(s),
        }
        for k, v in patch.items():
            self._orig[k] = getattr(adopt, k)
            setattr(adopt, k, v)
        test.addCleanup(self.restore)

    def restore(self):
        for k, v in self._orig.items():
            setattr(adopt, k, v)
        shutil.rmtree(self.base)

    def run(self, cmd, timeout=None):            # subprocess.run: boot.sh apply
        open(self.console, 'w').close()

    def probe(self, dev):
        tty = os.path.basename(dev)
        self.asked.append((self.clock.t, tty))
        seq = self.answers.get(tty, ['silent'])
        kind = seq.pop(0) if len(seq) > 1 else seq[0]
        return kind, {'console': 'pylon>', 'other': 'shell>', 'silent': ''}[kind]

    def release(self, tty, why):
        self.released.append((tty, why))
        os.remove(self.console)


class SearchTest(unittest.TestCase):
    def test_skips_victron_and_venus_devices_and_adopts_the_console(self):
        c = Cerbo(self, {'ttyUSB0': VICTRON, 'ttyUSB1': METER, 'ttyUSB2': FTDI},
                  services=[('com.victronenergy.grid.cg_BY1', 'Modbus RTU ttyUSB1:1')],
                  answers={'ttyUSB2': ['console']})
        self.assertEqual(adopt.search_pass(c.services, {}), 'adopted')
        self.assertEqual([t for _, t in c.asked], ['ttyUSB2'])     # only the free converter
        self.assertEqual(c.saved, [FTDI])
        self.assertTrue(any('Victron device' in l for l in c.lines))
        self.assertTrue(any('in use by Venus OS' in l for l in c.lines))

    def test_nothing_to_ask(self):
        c = Cerbo(self, {'ttyUSB0': VICTRON})
        self.assertEqual(adopt.search(adapters.HEAD_START), 1)
        self.assertEqual(c.asked, [])

    def test_silent_adapter_is_asked_again_10_min_then_hourly(self):
        c = Cerbo(self, {'ttyUSB0': FTDI})
        c.clock.limit = c.clock.t + 60 + 6 * 600 + 3 * 3600 + 1
        with self.assertRaises(StopIteration):
            adopt.search(adapters.HEAD_START)
        times = [t for t, _ in c.asked]
        gaps = [round(b - a) for a, b in zip(times, times[1:])]
        self.assertEqual(gaps, [600] * 6 + [3600] * 3)
        # the log says it once, not at every try
        self.assertEqual(sum('no answer' in l for l in c.lines), 1)

    def test_battery_switched_on_later_is_adopted(self):
        c = Cerbo(self, {'ttyUSB0': FTDI}, answers={'ttyUSB0': ['silent', 'silent', 'console']})
        self.assertEqual(adopt.search(adapters.HEAD_START), 0)
        self.assertEqual(len(c.asked), 3)
        self.assertEqual(c.saved, [FTDI])


class VerifyTest(unittest.TestCase):
    def cerbo(self, answers):
        c = Cerbo(self, {'ttyPYLON': METER}, answers={'ttyPYLON': answers})
        open(c.console, 'w').close()
        return c

    def test_confirmed(self):
        c = self.cerbo(['console'])
        self.assertTrue(adopt.verify())
        self.assertEqual(c.released, [])

    def test_silent_for_30_min_goes_to_venus(self):
        c = self.cerbo(['silent'])
        self.assertFalse(adopt.verify())
        self.assertEqual(len(c.asked), 16)                   # 0, 2, ... 30 min
        self.assertEqual(c.released[0][1], 'no answer for 30 min')

    def test_battery_wakes_up_within_the_window(self):
        c = self.cerbo(['silent'] * 5 + ['console'])
        self.assertTrue(adopt.verify())
        self.assertEqual(c.released, [])

    def test_another_device_goes_to_venus_at_once(self):
        c = self.cerbo(['other', 'other'])
        self.assertFalse(adopt.verify())
        self.assertEqual(len(c.asked), 2)
        self.assertIn('shell>', c.released[0][1])

    def test_cable_with_serial_number_is_not_checked(self):
        c = Cerbo(self, {'ttyPYLON': FTDI})
        open(c.console, 'w').close()
        with open(os.path.join(c.base, 'udev.match'), 'w') as f:
            f.write('ID_SERIAL_SHORT=A10KXYZ1\n')
        self.assertEqual(adopt.run(adapters.HEAD_START_BOOT, False), 0)
        self.assertEqual(c.asked, [])

    def test_socket_bound_cable_released_then_searched(self):
        c = Cerbo(self, {'ttyPYLON': METER}, answers={'ttyPYLON': ['other']})
        open(c.console, 'w').close()
        with open(os.path.join(c.base, 'udev.match'), 'w') as f:
            f.write('ID_PATH=platform-a-usb-0:1:1.0\n')
        c.clock.limit = c.clock.t + 4000
        with self.assertRaises(StopIteration):
            adopt.run(adapters.HEAD_START_BOOT, False)
        self.assertEqual(len(c.released), 1)
        self.assertTrue(any('searching the USB serial adapters' in l for l in c.lines))


if __name__ == '__main__':
    unittest.main()
