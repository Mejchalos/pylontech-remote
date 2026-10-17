"""A fake 4-module stack for export tests: per-module record lists behind `data N kind i`,
`stat` with matching counts, `datalist` on the master, and an optional ring-buffer drop."""
import re

from tests.fakeconsole import FakeConsole, _fixture, PROMPT

_STAT = _fixture('stat_b69.25.raw')
_RECORD = _fixture('data_2_history_1.raw')


def _time(module, kind, k):
    minutes = k * 30 + module * 3 + (0 if kind == 'history' else 7)
    return '26-10-%02d %02d:%02d:00' % (1 + minutes // 1440, (minutes // 60) % 24, minutes % 60)


class FakeStack(FakeConsole):
    def __init__(self, counts=None, drop_after=None, n_modules=4, connected=1, **kw):
        FakeConsole.__init__(self, n_modules=n_modules, **kw)
        self.connected = connected            # the module whose console the cable is plugged into
        counts = counts or {'event': 5, 'history': 12}
        # records[module][kind] = list of serial numbers k (oldest first)
        self.records = dict((m, dict((kind, list(range(c))) for kind, c in counts.items()))
                            for m in range(1, n_modules + 1))
        self.drop_after = drop_after          # (module, kind, n_reads): drop 8 oldest after n reads
        self.reads = 0
        self.data_commands = []

    def answer(self, command):
        if self.connected != 1 and command in ('info', 'stat', 'pwr'):
            # on another module's own console these describe that module (pwr: its detail)
            n = self.connected
            out = self.answer('%s %d' % (command, n))
            return out.replace(('%s %d' % (command, n)).encode(), command.encode(), 1)
        m = re.match(r'^data(?: (\d+))? (event|history) (\d+)$', command)
        if m:
            module, kind, i = int(m.group(1) or 1), m.group(2), int(m.group(3))
            self.data_commands.append(command)
            self.reads += 1
            if self.drop_after and (module, kind, self.reads) == self.drop_after:
                del self.records[module][kind][:8]
            recs = self.records.get(module, {}).get(kind)
            if recs is None:
                return command.encode() + b'\n\r@\r\n\rTarget device is not present\r\r\n$$' + PROMPT
            if i >= len(recs):
                return command.encode() + b'\n\r@\r\n\rInvalid command or fail to excute.\r\n$$' + PROMPT
            k = recs[i]
            body = re.sub(rb'Rec Item Index  : \d+', b'Rec Item Index  : %d' % i, _RECORD)
            body = re.sub(rb'Time            : [0-9: -]+', ('Time            : ' + _time(module, kind, k)).encode(), body)
            return body.replace(b'data 2 history 1', command.encode())
        m = re.match(r'^stat(?: (\d+))?$', command)
        if m:
            module = int(m.group(1) or 1)
            recs = self.records[module]
            out = re.sub(rb'Data Items      :\s+\d+', b'Data Items      :      %d' % len(recs['event']), _STAT)
            out = re.sub(rb'HisData Items   :\s+\d+', b'HisData Items   :     %d' % len(recs['history']), out)
            return out.replace(b'stat 2', command.encode())
        m = re.match(r'^pwr (\d+)$', command)
        if m:
            out = _fixture('pwr_4_b69.25.raw').replace(b'pwr 4', command.encode())
            return out.replace(b' Power  4', b' Power  ' + m.group(1).encode())
        if command in ('datalist event 0', 'datalist history 0'):
            return _fixture('datalist_event_master_b69.25.raw').replace(b'datalist event 0', command.encode())
        m = re.match(r'^info(?: (\d+))?$', command)
        if m:
            module = int(m.group(1) or 1)
            out = _fixture('info_synthetic.raw').replace(b'info 2', command.encode())
            out = out.replace(b'Device address      : 2', b'Device address      : %d' % module)
            return out.replace(b'X00000000TEST0002', b'X00000000TEST000%d' % module)
        return FakeConsole.answer(self, command)
