"""Read-only command allow-list — the single gate for everything written to the console.

Derived from docs/CONSOLE-NOTES.md. Anything not matching one of these patterns exactly is
refused before a single byte is sent. Do not add commands that change, clear, test or control
anything (see the forbidden list in CONSOLE-NOTES).
"""
import re

MODULE = r'[1-9][0-9]?'

ALLOWED = (
    r'',                                            # bare Enter: wake / resync
    r'help( [a-z]+)?',
    r'pwr( ' + MODULE + r')?',
    r'config',
    r'info( ' + MODULE + r')?',
    r'bat ' + MODULE,
    r'stat( ' + MODULE + r')?',
    r'data( ' + MODULE + r')? (event|history) [0-9]{1,4}',
    r'datalist (event|history) [0-9]{1,4}',
    r'log',
)

_PATTERNS = tuple(re.compile(p) for p in ALLOWED)


class ForbiddenCommand(ValueError):
    pass


def is_allowed(command):
    return isinstance(command, str) and any(p.fullmatch(command) for p in _PATTERNS)


def check(command):
    if not is_allowed(command):
        raise ForbiddenCommand('refused (not in allow-list): %r' % (command,))
    return command
