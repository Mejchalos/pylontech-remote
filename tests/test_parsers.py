import os
import unittest

from pylontech_remote import parsers

FIX = os.path.join(os.path.dirname(__file__), 'fixtures')


def fixture(name):
    with open(os.path.join(FIX, name), 'rb') as f:
        return f.read().decode('ascii')


class PwrTest(unittest.TestCase):
    def test_modules(self):
        mods = parsers.parse_pwr(fixture('pwr_b69.25.raw'))
        self.assertEqual([m['id'] for m in mods], [1, 2, 3, 4])   # slots 5-16 are Absent
        m = mods[0]
        self.assertEqual(m['volt_mv'], 49695)
        self.assertEqual(m['curr_ma'], -3099)
        self.assertEqual(m['temp_mc'], 23800)
        self.assertEqual((m['tlow_mc'], m['thigh_mc']), (22500, 22800))
        self.assertEqual((m['vlow_mv'], m['vhigh_mv']), (3313, 3313))
        self.assertEqual(m['base_state'], 'Dischg')
        self.assertEqual(m['soc_pct'], 77)
        self.assertEqual(m['time'], '2026-10-15 20:29:24')
        self.assertEqual(m['mos_temp_mc'], 22400)
        self.assertNotIn('_extra', m['raw'])
        self.assertEqual(mods[3]['vhigh_mv'], 3315)


class BatTest(unittest.TestCase):
    def test_cells(self):
        cells = parsers.parse_bat(fixture('bat_b69.25.raw'))
        self.assertEqual(len(cells), 15)
        self.assertEqual([c['cell'] for c in cells], list(range(15)))
        c = cells[0]
        self.assertEqual(c['v_mv'], 3312)
        self.assertEqual(c['curr_ma'], -2772)
        self.assertEqual(c['temp_c'], 22.9)
        self.assertEqual(c['state'], 'Dischg')
        self.assertEqual(c['soc_pct'], 79)
        self.assertEqual(c['coul_mah'], 57313)
        self.assertIs(c['bal'], False)
        self.assertEqual(cells[2]['soc_pct'], 80)


class KvTest(unittest.TestCase):
    def test_stat(self):
        st = parsers.parse_stat(fixture('stat_b69.25.raw'))
        self.assertEqual(st['address'], 2)
        self.assertEqual(st['event_items'], 104)
        self.assertEqual(st['history_items'], 1795)
        self.assertEqual(st['cycles'], 216)
        self.assertEqual(st['soh_pct'], 98)
        self.assertIsNotNone(st['bat_hv_times'])

    def test_info(self):
        info = parsers.parse_info(fixture('info_synthetic.raw'))
        self.assertEqual(info['address'], 2)
        self.assertEqual(info['model'], 'US3000C')
        self.assertEqual(info['barcode'], 'X00000000TEST0002')
        self.assertEqual(info['fw'], 'B69.25.0.0')


class MarkersTest(unittest.TestCase):
    def test_absent(self):
        self.assertTrue(parsers.is_absent(fixture('data_absent_module.raw')))
        self.assertFalse(parsers.is_absent(fixture('pwr_b69.25.raw')))


if __name__ == '__main__':
    unittest.main()
