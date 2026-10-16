import unittest

from pylontech_remote import allowlist

ALLOWED = [
    '', 'help', 'help data', 'pwr', 'pwr 4', 'config', 'info', 'info 2', 'bat 1', 'bat 16', 'stat', 'stat 4',
    'data event 0', 'data history 1795', 'data 2 event 0', 'data 4 history 1200',
    'datalist event 0', 'datalist history 1790', 'log',
]

# Everything here changes, clears, tests or controls the battery (listed in `help`),
# or is an allowed command with something smuggled in.
FORBIDDEN = [
    'time', 'time 2026 10 15 12 00 00', 'shut', 'trst', 'updata', 'login', 'login debug', 'logout',
    'datac', 'datac event', 'datac history', 'logc', 'statc', 'save', 'save history',
    'config bov 3650', 'config default', 'config save', 'setsoc 50', 'totalcoul 74000',
    'currcal 1', 'inacal', 'emptyvolt 3000', 'urates 9600', 'setprt sma', 'setlowcfg save',
    'autoswitch 1', 'prot bhv dis', 'ctrl cfet off', 'ctrl afuse on', 'eepw 0 0 0 1', 'eepe 0',
    'flaw 0 0 0', 'flae 0', 'mm 4 0 0', 'tbuz', 'tled on', 'tmos cfet', 'tclear', 'tbar 1',
    'tcycle 1', 'twdg', 'soh 2', 'disp', 'ct 1', 'tcan 1',
    'bat 1\nshut', 'pwr\n', ' pwr', 'pwr ', 'PWR', 'bat 0', 'bat 100', 'info 1 2',
    'data event', 'data 2 event', 'datalist 2 history 0', 'data event 1 2', None, 42,
]


class AllowListTest(unittest.TestCase):
    def test_allowed(self):
        for c in ALLOWED:
            with self.subTest(c=c):
                self.assertEqual(allowlist.check(c), c)

    def test_forbidden(self):
        for c in FORBIDDEN:
            with self.subTest(c=c):
                self.assertRaises(allowlist.ForbiddenCommand, allowlist.check, c)


if __name__ == '__main__':
    unittest.main()
