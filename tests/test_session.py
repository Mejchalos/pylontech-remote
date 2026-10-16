import unittest

from pylontech_remote import allowlist
from pylontech_remote.session import ConsoleSession

from tests.fakeconsole import FakeClock, FakeConsole


def make(gap=1.2, **kw):
    clock = FakeClock()
    fake = FakeConsole(clock=clock, **kw)
    s = ConsoleSession('/dev/fake', gap=gap, serial_factory=lambda p, b: fake,
                       clock=clock, sleep=clock.sleep)
    s.open(check_holders=False)
    return s, fake, clock


class SessionTest(unittest.TestCase):
    def test_forbidden_is_never_written(self):
        s, fake, _ = make()
        before = list(fake.written)
        for c in ('shut', 'datac history', 'time 2026 1 1 0 0 0', 'bat 1\nshut'):
            self.assertRaises(allowlist.ForbiddenCommand, s.command, c)
        self.assertEqual(fake.written, before)

    def test_reply_ends_at_prompt(self):
        s, _, _ = make()
        r = s.command('pwr')
        self.assertEqual(r.end_reason, 'prompt')
        self.assertTrue(r.ok)
        self.assertIn('Power Volt', r.text)

    def test_gap_between_commands(self):
        s, fake, clock = make(gap=1.2)
        s.command('pwr')
        t_end = clock.t
        s.command('bat 1')
        # the write of 'bat 1' happened at least `gap` after the previous reply ended
        self.assertGreaterEqual(clock.t - t_end, 1.2)

    def test_paging_answered_with_enter(self):
        paged = (b'log\n\r@\r\n\rline1\r\n\rPress [Enter] to be continued,other key to exit\r\r'
                 b'          \rline2\r\n\rCommand completed successfully\r\n\r$$\r\n\rpylon_debug>')
        s, fake, _ = make(replies={'log': paged})
        r = s.command('log')
        self.assertEqual(r.pages, 1)
        self.assertIn(b'\r', fake.written)
        self.assertNotIn(b' ', fake.written)          # space would abort the output

    def test_silence_ends_on_idle(self):
        s, _, _ = make(replies={'pwr': b'pwr\n\r@\r\n\rhalf a reply'})
        r = s.command('pwr', idle=1.0)
        self.assertEqual(r.end_reason, 'idle')
        self.assertFalse(r.ok)


class RealPagingTest(unittest.TestCase):
    def test_real_log_capture_pages_through(self):
        from tests.fakeconsole import _fixture
        s, fake, _ = make(replies={'log': _fixture('log_paged_b69.25.raw')})
        r = s.command('log')
        self.assertTrue(r.ok)
        self.assertEqual(r.pages, 10)
        self.assertIn('Index   : 0', r.text)


class TruncatedReplyTest(unittest.TestCase):
    def test_prompt_right_after_truncated_text_ends_the_reply(self):
        cut = b'data 4 history 1790\n\r@\r\r\nBat Events      : 0x0        pylon_debug>'
        s, _, clock = make(replies={'data 4 history 1790': cut})
        t0 = clock.t
        r = s.command('data 4 history 1790', idle=8.0)
        self.assertEqual(r.end_reason, 'prompt')       # no 8 s wait
        self.assertLess(clock.t - t0, 2.0)
        self.assertNotIn('Command completed successfully', r.text)


if __name__ == '__main__':
    unittest.main()
