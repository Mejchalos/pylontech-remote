import os
import shutil
import tempfile
import unittest

import pylontech_live
from pylontech_remote import adapters
from pylontech_remote.session import ConsoleSession

from tests.fakeconsole import FakeClock, FakeConsole

CH340 = {'ID_USB_DRIVER': 'ch341', 'ID_MODEL': 'USB_Serial', 'ID_VENDOR_ID': '1a86',
         'ID_MODEL_ID': '7523', 'ID_PATH': 'platform-1c14400.usb-usb-0:1:1.0',
         'VE_SERVICE': 'cgwacs:default'}
FTDI = {'ID_USB_DRIVER': 'ftdi_sio', 'ID_MODEL': 'FT232R_USB_UART', 'ID_VENDOR_ID': '0403',
        'ID_MODEL_ID': '6001', 'ID_SERIAL_SHORT': 'A10KXYZ1', 'ID_PATH': 'platform-1c1b000.usb-usb-0:1.1:1.0',
        'VE_SERVICE': 'rs485:default'}


class CandidateTest(unittest.TestCase):
    def test_converters_may_be_the_console(self):
        self.assertIsNone(adapters.excluded(CH340))
        self.assertIsNone(adapters.excluded(FTDI))

    def test_victron_devices_are_never_the_console(self):
        for model in ('VE_Direct_cable', 'MK3-USB_Interface', 'USB-RS485_Cable', 'FT232EX'):
            self.assertEqual(adapters.excluded(dict(FTDI, ID_MODEL=model)), 'Victron device')
        self.assertEqual(adapters.excluded(dict(FTDI, ID_VENDOR='VictronEnergy_BV')), 'Victron device')

    def test_modems_and_gps_are_never_touched(self):
        self.assertIn('not a USB serial converter', adapters.excluded(dict(CH340, ID_USB_DRIVER='option')))
        self.assertIn('not a USB serial converter', adapters.excluded(dict(CH340, ID_USB_DRIVER='cdc_acm')))

    def test_adapter_reserved_by_another_program(self):
        self.assertEqual(adapters.excluded(dict(CH340, VE_SERVICE='ignore')), 'reserved by another program')

    def test_used_by_venus(self):
        services = [('com.victronenergy.system', ''), ('com.victronenergy.grid.cgwacs_ttyUSB1_mb1', '/dev/ttyUSB1'),
                    ('com.victronenergy.vebus.ttyS4', 'VE.Bus'), ('com.victronenergy.grid.cg_BY123', 'Modbus RTU ttyUSB2:1')]
        self.assertEqual(adapters.used_by_venus('ttyUSB1', services), 'com.victronenergy.grid.cgwacs_ttyUSB1_mb1')
        self.assertEqual(adapters.used_by_venus('ttyUSB2', services), 'com.victronenergy.grid.cg_BY123')
        self.assertIsNone(adapters.used_by_venus('ttyUSB0', services))
        self.assertIsNone(adapters.used_by_venus('ttyUSB1', [('com.victronenergy.solarcharger.ttyUSB10', '')]))

    def test_parse_props(self):
        p = adapters.parse_props('DEVNAME=/dev/ttyUSB0\nID_USB_DRIVER=ch341\nID_PATH=platform-x:1.0\n')
        self.assertEqual(p['ID_USB_DRIVER'], 'ch341')
        self.assertEqual(p['ID_PATH'], 'platform-x:1.0')


class RuleTest(unittest.TestCase):
    def test_serial_number_rule_follows_the_cable(self):
        rule, match = adapters.rule_for(FTDI)
        self.assertEqual(match, 'ID_SERIAL_SHORT=A10KXYZ1')
        self.assertIn('ENV{ID_SERIAL_SHORT}=="A10KXYZ1"', rule)
        self.assertNotIn('ID_PATH', rule)
        self.assertIn('ENV{VE_SERVICE}="ignore"', rule)
        self.assertIn('SYMLINK+="ttyPYLON"', rule)

    def test_no_serial_number_rule_is_bound_to_the_socket(self):
        rule, match = adapters.rule_for(CH340)
        self.assertEqual(match, 'ID_PATH=platform-1c14400.usb-usb-0:1:1.0')
        self.assertIn('ENV{ID_VENDOR_ID}=="1a86", ENV{ID_MODEL_ID}=="7523"', rule)

    def test_odd_serial_number_falls_back_to_the_socket(self):
        rule, match = adapters.rule_for(dict(FTDI, ID_SERIAL_SHORT='a"b'))
        self.assertTrue(match.startswith('ID_PATH='))

    def test_unusable_ids_are_refused(self):
        with self.assertRaises(ValueError):
            adapters.rule_for(dict(CH340, ID_PATH='bad"path'))


class AnswerTest(unittest.TestCase):
    def test_only_the_pylontech_prompt_is_the_console(self):
        self.assertEqual(adapters.answer_kind(b'\r\n\rpylon>'), 'console')
        self.assertEqual(adapters.answer_kind(b'\r\n$$\r\n\rpylon_debug> '), 'console')
        self.assertEqual(adapters.answer_kind(b'\r\nshell>'), 'other')         # another console
        self.assertEqual(adapters.answer_kind(b'$GPRMC,123519,A,4807.038,N'), 'other')
        self.assertEqual(adapters.answer_kind(b'pylon> garbage after it'), 'other')
        self.assertEqual(adapters.answer_kind(b''), 'silent')
        self.assertEqual(adapters.answer_kind(b'\r\n \r\n'), 'silent')

    def test_retry_schedule(self):
        self.assertEqual([adapters.retry_delay(n) for n in range(1, 9)],
                         [600, 600, 600, 600, 600, 600, 3600, 3600])
        self.assertEqual(adapters.VERIFY_WINDOW // adapters.VERIFY_INTERVAL, 15)


class _Silent(object):
    """A port nobody answers on (battery off, or a Modbus meter that only answers its protocol)."""
    def __init__(self, clock, out=b''):
        self.written = []
        self.out = out
        self.clock = clock

    in_waiting = 0

    def write(self, data):
        self.written.append(data)
        return len(data)

    def read(self, n):
        self.clock.advance(0.1)
        chunk, self.out = self.out[:n], self.out[n:]
        return chunk

    def close(self):
        pass


class AdoptProbeTest(unittest.TestCase):
    def probe(self, port, clock):
        import pylontech_adopt
        real = pylontech_adopt.ConsoleSession
        pylontech_adopt.ConsoleSession = lambda dev: real(dev, serial_factory=lambda p, b: port,
                                                          clock=clock, sleep=clock.sleep)
        try:
            return pylontech_adopt.probe('/dev/fake')
        finally:
            pylontech_adopt.ConsoleSession = real

    def test_console(self):
        clock = FakeClock()
        fake = FakeConsole(clock=clock)
        self.assertEqual(self.probe(fake, clock), ('console', 'pylon_debug>'))
        self.assertEqual(set(fake.written), {b'\n'})

    def test_silent_adapter_gets_enter_only(self):
        clock = FakeClock()
        port = _Silent(clock)
        kind, _ = self.probe(port, clock)
        self.assertEqual(kind, 'silent')
        self.assertEqual(set(port.written), {b'\n'})

    def test_other_device(self):
        clock = FakeClock()
        port = _Silent(clock, b'$GPGGA,092750.000,5321.6802,N,00630.3372,W\r\n')
        kind, detail = self.probe(port, clock)
        self.assertEqual(kind, 'other')
        self.assertIn('GPGGA', detail)


class ProbeTest(unittest.TestCase):
    """The probe is the session's opening: Enter only, then the prompt."""

    def test_open_sends_enter_only_and_keeps_the_prompt(self):
        clock = FakeClock()
        fake = FakeConsole(clock=clock, n_modules=2)
        s = ConsoleSession('/dev/fake', serial_factory=lambda p, b: fake, clock=clock, sleep=clock.sleep)
        s.open(check_holders=False)
        self.assertTrue(s.greeting.ok)
        self.assertEqual(set(fake.written), {b'\n'})


class RawDumpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_every_command_and_reply_is_written(self):
        clock = FakeClock()
        fake = FakeConsole(clock=clock, n_modules=2)
        s = ConsoleSession('/dev/fake', serial_factory=lambda p, b: fake, clock=clock, sleep=clock.sleep)
        path = os.path.join(self.tmp, 'diag.txt')
        pylontech_live.record(s, path)
        s.open(check_holders=False)
        s.command('pwr')
        with open(path) as f:
            text = f.read()
        self.assertIn("### ''", text)
        self.assertIn("### 'pwr'", text)
        self.assertIn('Power', text)


if __name__ == '__main__':
    unittest.main()
