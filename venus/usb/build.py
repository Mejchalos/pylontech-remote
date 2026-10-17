"""Build venus-runtime.tar.gz: install pylontech-remote from a USB stick, without SSH.

    python venus/usb/build.py [OUTDIR]          (default: dist/usb)

Copy the file to the root of a USB stick (FAT32) and plug it into the Cerbo. Venus OS unpacks it
into /data and runs rc/post-hook.sh as root, which runs install.sh without questions.
"""
import io
import os
import sys
import tarfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FILES = ['install.sh', 'uninstall.sh', 'venus/boot.sh', 'pylontech_live.py', 'pylontech_export.py',
         'nodered/pylontech_flow.json'] + \
        ['pylontech_remote/' + f for f in sorted(os.listdir(os.path.join(ROOT, 'pylontech_remote')))
         if f.endswith('.py')]
EXECUTABLE = ('.sh', 'pylontech_live.py', 'pylontech_export.py')


def add(tar, name, data, mode):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = mode
    info.mtime = int(time.time())
    info.uid = info.gid = 0
    info.uname = info.gname = 'root'
    tar.addfile(info, io.BytesIO(data))


def add_dir(tar, name):
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.mode = 0o755
    info.mtime = int(time.time())
    info.uname = info.gname = 'root'
    tar.addfile(info)


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, 'venus-runtime.tar.gz')
    with tarfile.open(path, 'w:gz', format=tarfile.GNU_FORMAT) as tar:
        add_dir(tar, 'rc')
        with open(os.path.join(ROOT, 'venus', 'usb', 'post-hook.sh'), 'rb') as f:
            add(tar, 'rc/post-hook.sh', f.read().replace(b'\r\n', b'\n'), 0o755)
        dirs = set()
        for rel in FILES:
            parts = ('pylontech-install/' + rel).split('/')
            for k in range(1, len(parts)):
                d = '/'.join(parts[:k])
                if d not in dirs:
                    add_dir(tar, d)
                    dirs.add(d)
            with open(os.path.join(ROOT, rel), 'rb') as f:
                data = f.read()
            if not rel.endswith('.json'):
                data = data.replace(b'\r\n', b'\n')
            add(tar, 'pylontech-install/' + rel, data, 0o755 if rel.endswith(EXECUTABLE) else 0o644)
    print(path)
    return path


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'dist', 'usb'))
