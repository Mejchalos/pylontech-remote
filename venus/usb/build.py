"""Build the USB stick archives: install / uninstall pylontech-remote without SSH.

    python venus/usb/build.py [--version v0.1.0] [OUTDIR]      (default OUTDIR: dist/usb)

  venus-runtime-pylontech-install.tar.gz     installs or updates (runs install.sh --yes)
  venus-runtime-pylontech-uninstall.tar.gz   removes everything (runs uninstall.sh --yes)

Copy one of them to the root of a FAT32 USB stick and plug it into the Cerbo. Venus OS unpacks
every venus-runtime-*.tar.gz into /data and runs its rc/post-hook.sh as root
(/etc/init.d/update-data.sh).
"""
import io
import os
import sys
import tarfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PROGRAM = ['install.sh', 'uninstall.sh', 'venus/boot.sh', 'pylontech_live.py', 'pylontech_export.py',
           'nodered/pylontech_flow.json'] + \
          ['pylontech_remote/' + f for f in sorted(os.listdir(os.path.join(ROOT, 'pylontech_remote')))
           if f.endswith('.py')]
EXECUTABLE = ('.sh', 'pylontech_live.py', 'pylontech_export.py')


def read(rel):
    with open(os.path.join(ROOT, rel), 'rb') as f:
        data = f.read()
    return data if rel.endswith('.json') else data.replace(b'\r\n', b'\n')


class Archive(object):
    def __init__(self, path):
        self.tar = tarfile.open(path, 'w:gz', format=tarfile.GNU_FORMAT)
        self.dirs = set()
        self.now = int(time.time())

    def _info(self, name):
        info = tarfile.TarInfo(name)
        info.mtime = self.now
        info.uid = info.gid = 0
        info.uname = info.gname = 'root'
        return info

    def add(self, name, data, mode):
        parts = name.split('/')
        for k in range(1, len(parts)):
            d = '/'.join(parts[:k])
            if d not in self.dirs:
                info = self._info(d)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                self.tar.addfile(info)
                self.dirs.add(d)
        info = self._info(name)
        info.size = len(data)
        info.mode = mode
        self.tar.addfile(info, io.BytesIO(data))

    def close(self):
        self.tar.close()


def build(outdir, version):
    os.makedirs(outdir, exist_ok=True)
    stamp = '%s (%s)' % (version or 'development build', time.strftime('%Y-%m-%d'))

    path = os.path.join(outdir, 'venus-runtime-pylontech-install.tar.gz')
    a = Archive(path)
    a.add('rc/post-hook.sh', read('venus/usb/post-hook.sh'), 0o755)
    for rel in PROGRAM:
        a.add('pylontech-install/' + rel, read(rel), 0o755 if rel.endswith(EXECUTABLE) else 0o644)
    a.add('pylontech-install/VERSION', ('pylontech-remote %s, USB stick\n' % stamp).encode(), 0o644)
    a.close()
    print(path)

    path = os.path.join(outdir, 'venus-runtime-pylontech-uninstall.tar.gz')
    a = Archive(path)
    a.add('rc/post-hook.sh', read('venus/usb/uninstall-hook.sh'), 0o755)
    a.add('pylontech-uninstall/uninstall.sh', read('uninstall.sh'), 0o755)
    a.close()
    print(path)


if __name__ == '__main__':
    args = sys.argv[1:]
    version = None
    if '--version' in args:
        i = args.index('--version')
        version = args[i + 1]
        del args[i:i + 2]
    build(args[0] if args else os.path.join(ROOT, 'dist', 'usb'), version)
