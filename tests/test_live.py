import json
import os
import shutil
import tempfile
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
        self.assertEqual(m['volt_mv'], 49697)
        self.assertEqual(m['alarms'], [])
        self.assertAlmostEqual(snap['pack']['volt_v'], 49.70, places=2)
        self.assertEqual(snap['pack']['power_w'], round(snap['pack']['volt_v'] * snap['pack']['curr_a']))
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

    def test_commands_per_window_without_saved_data(self):
        r = pylontech_live.Runner(self.s, self.state, 5)
        sizes = []
        for _ in range(6):
            before = len(self.commands())
            r.window()
            sizes.append(len(self.commands()) - before)
        self.assertEqual(sizes[0], 1 + 4 + 1 + 4 + 4)   # pwr, 4 x bat, config, 4 x info, 4 x stat
        self.assertEqual(sizes[1:], [5] * 5)            # then pwr + every module's cells

    def test_first_snapshot_is_complete(self):
        pylontech_live.Runner(self.s, self.state, 5).window()
        first = self.out[0]
        self.assertEqual(len(self.out), 1)
        for m in first['modules']:
            self.assertEqual((m['model'], m['n_cells'], m['soh_source']), ('US3000C', 15, 'bms'))
            self.assertEqual(m['fw'], 'B69.25.0.0')
        self.assertIsNotNone(first['thresholds'])

    def test_one_snapshot_per_cycle_with_all_cells_fresh(self):
        r = pylontech_live.Runner(self.s, self.state, 5)
        for i in range(3):
            r.window()
            self.assertEqual(len(self.out), i + 1)
            snap = self.out[-1]
            self.assertEqual([m['n_cells'] for m in snap['modules']], [15, 15, 15, 15])


class ModuleAlarmsTest(unittest.TestCase):
    def test_states_other_than_normal_are_alarms(self):
        from pylontech_remote.live import module_alarms
        row = {'raw': {'Volt.St': 'Normal', 'Curr.St': 'Normal', 'Temp.St': 'Normal',
                       'B.V.St': 'High', 'B.T.St': 'Normal', 'M.T.St': '-'}}
        self.assertEqual(module_alarms(row), [['Cell voltage', 'High']])
        self.assertEqual(module_alarms({}), [])


class SavedStaticDataTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, 'static.json')
        self.out = []
        pylontech_live.emit = self.out.append

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_live(self, windows):
        clock = FakeClock()
        fake = FakeConsole(clock=clock, n_modules=4)
        s = ConsoleSession('/dev/fake', gap=1.2, serial_factory=lambda p, b: fake,
                           clock=clock, sleep=clock.sleep)
        s.open(check_holders=False)
        store = pylontech_live.StaticStore(self.path)
        r = pylontech_live.Runner(s, StackState(clock=clock), 5, store)
        sizes = []
        for _ in range(windows):
            before = len(fake.written)
            r.window()
            sizes.append(len(fake.written) - before)
        return r, store, sizes

    def test_second_run_is_complete_at_once_and_refreshes_in_background(self):
        self.run_live(1)                                # first run: saves the slow-changing data
        self.assertTrue(os.path.exists(self.path))
        self.out[:] = []
        _, _, sizes = self.run_live(11)
        first = self.out[0]
        self.assertTrue(all(m['model'] == 'US3000C' and m['soh_source'] == 'bms' for m in first['modules']))
        self.assertEqual(sizes[0], 1 + 4 + 1)           # pwr, 4 x bat, one background item
        self.assertEqual(sizes[-1], 5)                  # background refresh done (9 items)

    def test_written_only_when_changed(self):
        _, store, _ = self.run_live(1)
        mtime = os.path.getmtime(self.path)
        with open(self.path) as f:
            saved = json.load(f)
        self.assertFalse(store.save(saved))
        self.assertEqual(os.path.getmtime(self.path), mtime)

    def test_other_module_in_slot_drops_saved_stats(self):
        state = StackState()
        state.load_static({'modules': {'2': {'info': {'barcode': 'OLD', 'model': 'US3000C'},
                                             'stat': {'soh_pct': 90, 'cycles': 999}}}})
        from tests.fakeconsole import _fixture
        state.update_info(2, _fixture('info_synthetic.raw').decode())
        self.assertNotIn(2, state.stat)


class StatsGroupingTest(unittest.TestCase):
    def test_groups_of_real_stat_reply(self):
        from pylontech_remote import parsers
        from pylontech_remote.live import group_stats
        from tests.fakeconsole import _fixture
        fields = parsers.parse_stat(_fixture('stat_b69.25.raw').decode())['fields']
        g = group_stats(fields)
        alarms = dict((l, v) for l, v, _ in g['alarms'])
        self.assertEqual(alarms['DOCA Times'], '5')
        self.assertEqual(alarms['Bat LV Times'], '4')
        for label in ('Reset Times', 'Shut Times', 'Bat HV Times', 'COC Times', 'DLT Times'):
            self.assertIn(label, alarms)
        for label in ('Charge Times', 'Idle Times', 'CYCLE Times', 'SOH Times', 'Data Items'):
            self.assertNotIn(label, alarms)
        records = [l for l, _, _ in g['records']]
        self.assertIn('Data Items', records)
        self.assertIn('Doca Items', records)
        shown = dict((l, s) for l, _, s in g['time'])
        self.assertEqual(shown['Pwr on Secs'], '272 d 2 h')         # 23509942 s
        self.assertEqual(shown['Low Volt1 Hours'], '14.0 h')
        self.assertEqual(shown['HT Secs'], '0 s')
        self.assertIn(['CYCLE Times', '216', '216'], g['operation'])
        self.assertNotIn('Device address', [l for grp in g.values() for l, _, _ in grp])
        self.assertEqual(sum(len(x) for x in g.values()), len(fields) - 1)

    def test_counters_survive_saving(self):
        from pylontech_remote.live import StackState
        from tests.fakeconsole import _fixture
        a = StackState()
        a.update_stat(2, _fixture('stat_b69.25.raw').decode())
        b = StackState()
        b.load_static(json.loads(json.dumps(a.static_dict())))
        self.assertEqual(b.stat[2]['fields'], a.stat[2]['fields'])
        self.assertEqual(b.stat[2]['read_at'], a.stat[2]['read_at'])


if __name__ == '__main__':
    unittest.main()
