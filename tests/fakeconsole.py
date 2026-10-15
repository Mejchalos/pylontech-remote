"""A fake serial port that answers like the Pylontech console, from fixture files."""
import os

FIX = os.path.join(os.path.dirname(__file__), 'fixtures')
PROMPT = b'\r\n\rpylon_debug>'
PAGING_PROMPT = b'Press [Enter] to be continued,other key to exit'


def _fixture(name):
    with open(os.path.join(FIX, name), 'rb') as f:
        return f.read()


class FakeConsole(object):
    """Implements the bits of serial.Serial that ConsoleSession uses."""

    def __init__(self, replies=None, n_modules=4, clock=None):
        self.written = []
        self._out = b''
        self._pages = []
        self.closed = False
        self.n_modules = n_modules
        self.replies = replies or {}
        self.clock = clock

    # serial.Serial API --------------------------------------------------------------------
    @property
    def in_waiting(self):
        return 0

    def write(self, data):
        self.written.append(data)
        if data == b'\r':          # Enter at a paging prompt releases the next page
            if self._pages:
                self._out += self._pages.pop(0)
            return len(data)
        command = data.decode('ascii').rstrip('\n')
        # like the real console: stop after each paging prompt until Enter arrives
        parts = self.answer(command).split(PAGING_PROMPT)
        self._out += parts[0] + (PAGING_PROMPT if len(parts) > 1 else b'')
        self._pages = [p + PAGING_PROMPT for p in parts[1:-1]] + parts[-1:] if len(parts) > 1 else []
        return len(data)

    def read(self, n):
        if self.clock is not None:
            self.clock.advance(0.1)
        chunk, self._out = self._out[:n], self._out[n:]
        return chunk

    def close(self):
        self.closed = True

    # console behaviour --------------------------------------------------------------------
    def answer(self, command):
        if command in self.replies:
            return self.replies[command]
        if command == '':
            return PROMPT
        word = command.split()
        n = int(word[1]) if len(word) > 1 and word[1].isdigit() else 1
        if word[0] in ('bat', 'info', 'stat') and n > self.n_modules:
            return command.encode() + b'\n\r@\r\n\rTarget device is not present\r\r\n$$\r\n\rpylon_debug>'
        name = {'pwr': 'pwr_b69.25.raw', 'bat': 'bat_b69.25.raw', 'stat': 'stat_b69.25.raw',
                'info': 'info_synthetic.raw'}.get(word[0])
        if name:
            return _fixture(name)
        if command == 'config':
            return (b'config\n\r@\r\n\rOver Voltage    : 3650\r\n\rHigh Voltage    : 3600\r\n\r'
                    b'Low Voltage     : 3050\r\n\rUnder Voltage   : 2800\r\n\r'
                    b'Command completed successfully\r\n\r$$' + PROMPT)
        return command.encode() + b'\n\r@\r\n\rInvalid command or fail to excute.\r\n$$' + PROMPT


class FakeClock(object):
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s

    def sleep(self, s):
        self.t += max(0.0, s)
