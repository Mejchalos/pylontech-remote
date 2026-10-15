import json
import unittest

import pylontech_live
from pylontech_remote.live import StackState
from pylontech_remote.session import ConsoleSession

from tests.fakeconsole import FakeClock, FakeConsole


class LiveRunnerTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.fake = FakeConsole(clock=self.clock, n_modules=4)
        self.s = ConsoleSession('/dev/fake', gap=1.2, serial_factory=lambda p, b: self.fake,
                                clock=self.clock, sleep=self.clock.sleep)
        self.s.open(check_holders=False)
        self.state = StackState(clock=self.clock)
        self.out = []
        pylontech_live.emit = self.out.append       # capture snapshots instead of stdout

    def commands(self):
        return [w.decode().rstrip('\n') for w in self.fake.written if w != b'\r']

    def test_once_reads_everything(self):
        snap = pylontech_live.Runner(self.s, self.state, 5).once()
        json.dumps(snap)                              # serialisable
        self.assertEqual(snap['n_modules'], 4)
        m = snap['modules'][1]
        self.assertEqual(m['model'], 'US3000C')
        self.assertEqual(m['n_cells'], 15)
        self.assertEqual(m['soh_pct'], 98)
        self.assertEqual(m['soh_source'], 'bms')
        self.assertEqual(m['cycles'], 216)
        self.assertEqual(snap['thresholds']['bhv_mv'], 3600)
        self.assertIsNotNone(snap['pack']['soc_pct'])
        self.assertIs(snap['live'], False)

    def test_windows_start_with_pwr_and_rotate_cells(self):
        r = pylontech_live.Runner(self.s, self.state, 5)
        for _ in range(12):
            r.window()
        cmds = self.commands()[1:]                    # skip the wake-up Enter
        pwr_positions = [i for i, c in enumerate(cmds) if c == 'pwr']
        self.assertEqual(len(pwr_positions), 12)      # exactly one pwr per window
        # every module's cells were read; each of them at least twice after start-up
        for n in range(1, 5):
            self.assertGreaterEqual(cmds.count('bat %d' % n), 2)
        self.assertEqual(cmds.count('config'), 1)
        self.assertTrue(all(o['ok'] for o in self.out))
        last = self.out[-1]
        self.assertEqual(last['n_modules'], 4)
        self.assertTrue(all(m['n_cells'] == 15 for m in last['modules']))

    def test_commands_per_window(self):
        r = pylontech_live.Runner(self.s, self.state, 5)
        sizes = []
        for _ in range(14):
            before = len(self.commands())
            r.window()
            sizes.append(len(self.commands()) - before)
        self.assertTrue(all(s <= 1 + 4 + 1 for s in sizes))   # pwr + 4 x bat + one start-up item
        self.assertEqual(sizes[-1], 1 + 4)                   # steady state: pwr + every module's cells

    def test_one_snapshot_per_cycle_with_all_cells_fresh(self):
        r = pylontech_live.Runner(self.s, self.state, 5)
        for i in range(3):
            r.window()
            self.assertEqual(len(self.out), i + 1)
            snap = self.out[-1]
            self.assertEqual([m['n_cells'] for m in snap['modules']], [15, 15, 15, 15])
            ages = [m['cells_age_s'] for m in snap['modules']]
            self.assertLess(max(ages), 10)                   # all read within this cycle


if __name__ == '__main__':
    unittest.main()
