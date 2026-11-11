"""Fake firmware images. The 'image' is a Python script run as a subprocess."""

_HEADER = '''# fake firmware kind={kind} version={version}
import os, sys, time
VERSION = {version!r}
PARENT = os.getppid()
def run_forever():
    while os.getppid() == PARENT:   # exit if the updater (the "device") dies
        time.sleep(0.1)
def say(s):
    print(s, flush=True)
'''

_BODIES = {
    "good": "say('SELFTEST_OK'); say('CLOUD_OK'); run_forever()",
    "crash_now": "sys.exit(1)",
    "crash_later": "say('SELFTEST_OK'); say('CLOUD_OK'); time.sleep(0.4); sys.exit(1)",
    "no_cloud": "say('SELFTEST_OK'); run_forever()",
    "hang": "run_forever()",
    "selftest_fail": "say('SELFTEST_FAIL'); run_forever()",
}


def build_firmware(kind: str, version: str, size: int = 2048) -> bytes:
    text = _HEADER.format(kind=kind, version=version) + _BODIES[kind] + "\n"
    pad = size - len(text) - 2
    if pad < 0:
        raise ValueError("firmware larger than requested size")
    return (text + "#" + "." * pad + "\n").encode()
