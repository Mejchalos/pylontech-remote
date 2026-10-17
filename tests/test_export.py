import os
import re
import shutil
import tempfile
import unittest
import zipfile

from pylontech_remote import export, parsers

from tests.fakeconsole import _fixture

ROW = re.compile(rb'^(\d+) +\d\d-')


def master_rows():
    """Rows of the master's own `datalist event 0`, as BatteryView stores them."""
    table = export.batteryview_table(_fixture('datalist_event_master_b69.25.raw'))
    rows = {}
    for line in table.split(b'\r\n'):
        m = ROW.match(line)
        if m:
            rows[int(m.group(1))] = line
    return rows


def blank_line_positions(table):
    """Row numbers that follow a line of spaces (where the console paged)."""
    lines = table.split(b'\r\n')
    return [int(lines[i + 1].split()[0]) for i, l in enumerate(lines[:-1])
            if l and not l.strip() and lines[i + 1][:1].isdigit()]


class ReconstructedRowTest(unittest.TestCase):
    """A row rebuilt from `data event I` must equal the battery's own `datalist` row."""

    def test_rows_without_stack_columns_are_byte_identical(self):
        rows = master_rows()
        for i in (0, 1, 2, 3, 10, 20):         # old rows: the master itself printed '-' there
            with self.subTest(i=i):
                rec = parsers.parse_data_record(_fixture('data_event_master_%d.raw' % i).decode())
                self.assertEqual(rec['index'], i)
                self.assertEqual(export.datalist_row(i, rec), rows[i])

    def test_newer_rows_match_except_stack_columns(self):
        rows = master_rows()
        for i in (30, 50, 70, 80, 84, 85):
            with self.subTest(i=i):
                rec = parsers.parse_data_record(_fixture('data_event_master_%d.raw' % i).decode())
                mine = export.datalist_row(i, rec)
                theirs = rows[i]
                cut = len(b'%-6d' % i) + 19 + 7 * 2 + 8 * 3 + 9 * 2 + 10 * 3 + 6 + 5 + 1 + 13
                self.assertEqual(mine[:cut], theirs[:cut])     # every value column
                self.assertEqual(len(mine), len(theirs))      # same column widths after them
                events = ''.join(n + ' ' for n in rec['event_names']).encode()
                self.assertTrue(theirs.endswith(b'     ' + events))
                self.assertTrue(mine.endswith(b'     ' + events))

    def test_event_names_and_fault(self):
        rec = parsers.parse_data_record(_fixture('data_event_master_1.raw').decode())
        self.assertEqual(rec['event_names'], ['PHV', 'BHV'])
        rec = parsers.parse_data_record(_fixture('data_event_master_20.raw').decode())
        self.assertEqual(rec['system_fault'], '0x200')
        self.assertIn(b' 0x200        ', export.datalist_row(20, rec))

    def test_slave_record(self):
        rec = parsers.parse_data_record(_fixture('data_2_event_0.raw').decode())
        self.assertEqual((rec['index'], rec['time']), (0, '25-04-26 19:30:38'))
        self.assertEqual(rec['event_names'], ['SYSERR'])
        self.assertEqual(len(rec['cells']), 15)
        hist = parsers.parse_data_record(_fixture('data_2_history_1.raw').decode())
        self.assertEqual(hist['index'], 1)
        self.assertEqual(len(hist['cells']), 15)


class FileShapeTest(unittest.TestCase):
    def test_batteryview_table(self):
        raw = b'A   \r\n\rPress [Enter] to be continued,other key to exit\r\r' + b' ' * 50 + b'\rB'
        self.assertEqual(export.batteryview_table(raw), b'A   \r\n' + b' ' * 50 + b'\r\nB\r\n')
        table = export.batteryview_table(_fixture('datalist_event_master_b69.25.raw'))
        self.assertNotIn(b'Press [Enter]', table)
        self.assertNotIn(b'\r\r', table)
        self.assertNotIn(b'\n\r', table)                       # CRLF line ends only
        self.assertTrue(table.startswith(b'datalist event 0\r\n@\r\nItem  Time'))
        self.assertTrue(table.endswith(b'Command completed successfully\r\n$$\r\npylon_debug>\r\n'))
        self.assertEqual(blank_line_positions(table), [15, 31, 47, 63, 79])
        self.assertEqual(len(master_rows()), 86)

    def test_reconstructed_table(self):
        recs = [parsers.parse_data_record(_fixture('data_event_master_%d.raw' % i).decode())
                for i in (0, 1, 2)] * 12                         # 36 rows: two paging breaks
        out = export.reconstructed_table('event', 2, recs)
        self.assertTrue(out.startswith(b'datalist event 0\r\n@\r\n[reconstructed by pylontech-remote'))
        self.assertIn(b'\r\n' + export.DATALIST_HEADER_B69_25 + b'\r\n', out)
        self.assertEqual(blank_line_positions(out), [15, 31])  # same rhythm as BatteryView
        rows = master_rows()
        for i in (0, 1, 2):
            self.assertIn(rows[i] + b'\r\n', out)            # byte-identical rows
        self.assertTrue(out.endswith(b'Command completed successfully\r\n$$\r\npylon_debug>\r\n'))
        self.assertNotIn(b'\r\r', out)

    def test_header_matches_the_battery(self):
        data = _fixture('datalist_event_master_b69.25.raw')
        self.assertIn(export.DATALIST_HEADER_B69_25 + b'\r\r\n', data)

    def test_file_name(self):
        self.assertEqual(export.file_name('X00000000TEST0002', 'event', '20261015085149'),
                         'X00000000TEST0002_event_20261015085149.txt')


class ExporterTest(unittest.TestCase):
    def make(self, **kw):
        import pylontech_export
        from pylontech_remote.session import ConsoleSession
        from tests.fakeconsole import FakeClock
        from tests.fakestack import FakeStack
        clock = FakeClock()
        fake = FakeStack(clock=clock, **kw)
        s = ConsoleSession('/dev/fake', gap=0.2, serial_factory=lambda p, b: fake,
                           clock=clock, sleep=clock.sleep)
        s.open(check_holders=False)
        self.out = []
        pylontech_export.emit = self.out.append
        return pylontech_export.Exporter(s, clock=clock), fake

    def rows(self, data, marker):
        part = data[data.index(marker):]
        return [l for l in part.split(b'\r\n') if ROW.match(l)]

    def test_whole_stack(self):
        ex, fake = self.make()
        stamp, _ = ex.run_all()
        self.assertEqual(stamp, '20261015202924')                 # battery time from pwr
        names = sorted(ex.files)
        self.assertEqual(len(names), 8)                           # 4 modules x event/history
        self.assertTrue(all(n.endswith('_%s.txt' % stamp) for n in names))
        self.assertEqual([m['module'] for m in ex.summary], [1, 2, 3, 4])
        self.assertEqual(ex.retries, 0)
        self.assertTrue([k for k in ex.files if k.startswith('X00000000TEST0001_event')])
        for kind, count in (('event', 5), ('history', 12)):
            slave_cmds = [c for c in fake.data_commands if c.startswith('data 3 %s ' % kind)]
            self.assertEqual(slave_cmds[0], 'data 3 %s %d' % (kind, count - 1))   # newest first
        self.assertTrue(all(b'Press [Enter]' not in v for v in ex.files.values()))
        self.assertIn('raw/pwr.txt', ex.raw)
        # BatteryView: event file = info, stat, pwr, datalist; history file = info, stat, datalist
        for name, data in ex.files.items():
            order = [data.find(b'info'), data.find(b'stat'), data.find(b'datalist')]
            self.assertEqual(order, sorted(order), name)
            master = name.startswith('X00000000TEST0001_')
            if '_event_' in name:                                  # the pwr reply
                self.assertIn(b'Power Volt' if master else b'pwr ', data, name)
                if not master:
                    self.assertIn(b'CFetState', data, name)        # the module's own pwr detail
            else:
                self.assertNotIn(b'Power Volt', data, name)
                self.assertNotIn(b'CFetState', data, name)
        cmds = [w.decode().rstrip('\n') for w in fake.written if w != b'\r']
        for n in (2, 3, 4):
            self.assertIn('pwr %d' % n, cmds)

    def test_slave_table_contents(self):
        ex, fake = self.make()
        ex.run_all()
        files = [v for k, v in ex.files.items() if '_history_' in k and b'[reconstructed' in v]
        self.assertEqual(len(files), 3)                           # modules 2-4
        m3 = [v for k, v in ex.files.items() if k.startswith('X00000000TEST0003_history')][0]
        rows = self.rows(m3, b'datalist history 0')
        self.assertEqual(len(rows), 12)
        self.assertEqual([int(r.split()[0]) for r in rows], list(range(12)))
        times = [r[6:23] for r in rows]
        self.assertEqual(times, sorted(times))                    # oldest first

    def test_ring_buffer_drop_during_read(self):
        # module 2 drops its 8 oldest history records after 5 reads (indexes shift by 8)
        ex, fake = self.make(counts={'event': 3, 'history': 30}, drop_after=(2, 'history', 5))
        ex.run_all()
        m2 = [m for m in ex.summary if m['module'] == 2][0]
        self.assertEqual(m2['missing'], {})
        files = [v for k, v in ex.files.items() if '_history_' in k and b'module 2 read' in v]
        rows = self.rows(files[0], b'datalist history 0')
        # 30 records existed; the 8 oldest were dropped by the battery while reading: 22 remain,
        # none lost, none doubled (the shift made us re-read some, they were deduplicated)
        times = [r[6:23] for r in rows]
        self.assertEqual(len(times), len(set(times)))
        self.assertGreaterEqual(len(times), 22)

    def test_incomplete_reply_is_retried(self):
        ex, fake = self.make()
        original = fake.answer
        state = {'broken': False}

        def flaky(command):
            if command == 'data 2 event 4' and not state['broken']:
                state['broken'] = True
                return b'data 2 event 4\n\r@\r\r\n-----\r\n\rItem Index      : 4'   # cut short
            return original(command)
        fake.answer = flaky
        ex.run_all()
        self.assertEqual(ex.retries, 1)
        self.assertEqual(len(ex.failed), 1)
        self.assertTrue(all(m['missing'] == {} for m in ex.summary))

    def test_rest_of_a_cut_reply_arrives_with_the_next_command(self):
        # seen on the real stack: the master cuts a slave's record short (prompt right after
        # the truncated text) and sends the rest as the reply to the next command
        ex, fake = self.make()
        original = fake.answer
        state = {'rest': None, 'cut': False}

        def lagging(command):
            if state['rest'] is not None and command:         # a bare Enter does not flush it
                rest, state['rest'] = state['rest'], None
                return command.encode() + b'\n\r\r\r\n' + rest
            full = original(command)
            if command == 'data 3 history 6' and not state['cut']:
                state['cut'] = True
                i = full.index(b'\r\r\n9 ')
                state['rest'] = full[i + 3:]
                return full[:i] + b'pylon_debug>'
            return full
        fake.answer = lagging
        ex.run_all()
        self.assertGreaterEqual(ex.retries, 2)                # the cut reply and the stray rest
        self.assertTrue(all(m['missing'] == {} for m in ex.summary))
        m3 = [v for k, v in ex.files.items() if k.startswith('X00000000TEST0003_history')][0]
        self.assertEqual(len(self.rows(m3, b'datalist history 0')), 12)

    def test_connected_module_is_read_verbatim(self):
        ex, fake = self.make(connected=3)
        stamp, battery_time = ex.run_connected()
        self.assertEqual(battery_time, '')                         # a module's own pwr has no time
        self.assertEqual(sorted(ex.files), ['X00000000TEST0003_event_%s.txt' % stamp,
                                            'X00000000TEST0003_history_%s.txt' % stamp])
        cmds = [w.decode().strip() for w in fake.written]
        self.assertEqual([c for c in cmds if c], ['info', 'stat', 'pwr', 'datalist event 0', 'datalist history 0'])
        self.assertEqual(fake.data_commands, [])
        event = ex.files['X00000000TEST0003_event_%s.txt' % stamp]
        self.assertTrue(event.startswith(b'info'))
        self.assertIn(b'CFetState', event)                         # the module's own pwr detail
        self.assertIn(b'Command completed successfully\r\n$$\r\npylon_debug>\r\n', event)
        self.assertNotIn(b'[reconstructed', event)
        self.assertEqual(ex.summary[0]['module'], 3)
        self.assertIn(b'device address 3', ex.readme(stamp, battery_time))

    def test_connected_to_the_master(self):
        ex, fake = self.make(connected=1)
        stamp, battery_time = ex.run_connected()
        self.assertEqual(stamp, '20261015202924')                 # battery time from the stack pwr
        self.assertEqual(len(ex.files), 2)
        self.assertTrue(all(k.startswith('X00000000TEST0001_') for k in ex.files))

    def test_module_zips_are_kept_apart_from_stack_zips(self):
        import pylontech_export
        tmp = tempfile.mkdtemp()
        try:
            pylontech_export.write_zip(tmp, '1', {}, {}, b'', keep=5)
            for k in range(4):
                pylontech_export.write_zip(tmp, str(k), {}, {}, b'', keep=3,
                                           prefix='pylontech_module_X%d_' % k)
            names = sorted(os.listdir(tmp))
            self.assertIn('pylontech_logs_1.zip', names)
            self.assertEqual(len([n for n in names if n.startswith('pylontech_module_')]), 3)
        finally:
            shutil.rmtree(tmp)

    def test_zip(self):
        import pylontech_export
        ex, _ = self.make()
        stamp, bt = ex.run_all()
        tmp = tempfile.mkdtemp()
        try:
            for k in range(7):
                path, name = pylontech_export.write_zip(tmp, stamp + str(k), ex.files, ex.raw,
                                                        ex.readme(stamp, bt), keep=5)
            self.assertEqual(len([f for f in os.listdir(tmp) if f.endswith('.zip')]), 5)
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                self.assertIn('README.txt', names)
                self.assertEqual(len([n for n in names if not n.startswith('raw/') and n != 'README.txt']), 8)
                self.assertIn(b'reconstructed', z.read('README.txt'))
        finally:
            shutil.rmtree(tmp)


if __name__ == '__main__':
    unittest.main()
