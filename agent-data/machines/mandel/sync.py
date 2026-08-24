#!/usr/bin/env python3
"""Keep the MANDEL snapshot in this directory honest against the live machine.

The printer is the source of truth. This script only makes that checkable —
`--check` before every edit, because a stale snapshot pushed back to the machine
silently reverts whatever was changed there in between.

    python sync.py --check     diff repo against the machine
    python sync.py --pull      machine -> repo
    python sync.py --push      repo -> machine (prompts; --yes to skip)

Credentials come from the environment or a .env beside the repo root:
PRINTER_SSH_HOST, PRINTER_SSH_USER, PRINTER_SSH_PASS.
"""
import argparse
import difflib
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# repo path (relative to this file) -> path on the printer
FILES = {
    "config/printer.cfg": "/home/pi/printer_data/config/printer.cfg",
    "config/clay_macros.cfg": "/home/pi/printer_data/config/clay_macros.cfg",
    "panels/clay.py": "/home/pi/KlipperScreen/panels/clay.py",
    "klipperscreen/KlipperScreen.conf": "/home/pi/printer_data/config/KlipperScreen.conf",
}

# NOT synced here: KlipperScreen's four patched TRACKED files. They are captured
# as klipperscreen/local-modifications.patch instead, because they are diffs
# against a specific upstream commit and a whole-file push would silently pin
# the machine to whatever upstream version this snapshot was taken from.
# Refresh with:  ssh pi@<host> "cd KlipperScreen && git diff"


def load_env():
    """Environment first, then a .env at the repo root. .env is gitignored."""
    root = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
    path = os.path.join(root, ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))
    host = os.environ.get("PRINTER_SSH_HOST")
    user = os.environ.get("PRINTER_SSH_USER", "pi")
    pw = os.environ.get("PRINTER_SSH_PASS")
    if not host or not pw:
        sys.exit("Set PRINTER_SSH_HOST / PRINTER_SSH_USER / PRINTER_SSH_PASS "
                 "in the environment or .env (see .env.example).")
    return host, user, pw


def connect():
    try:
        import paramiko
    except ImportError:
        sys.exit("paramiko is required:  pip install -r requirements.txt")
    host, user, pw = load_env()
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, username=user, password=pw, timeout=20)
    return c


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--pull", action="store_true")
    g.add_argument("--push", action="store_true")
    ap.add_argument("--yes", action="store_true", help="skip the push confirmation")
    a = ap.parse_args()

    sftp = connect().open_sftp()
    drift = 0

    for rel, remote in FILES.items():
        local = os.path.join(HERE, rel)
        try:
            with sftp.open(remote, "rb") as f:
                rbytes = f.read()
        except IOError:
            print("  %-24s MISSING ON MACHINE" % rel)
            drift += 1
            continue
        lbytes = open(local, "rb").read() if os.path.exists(local) else b""

        if hashlib.md5(rbytes).hexdigest() == hashlib.md5(lbytes).hexdigest():
            print("  %-24s in sync" % rel)
            continue

        drift += 1
        if a.check:
            # Line endings matter here (printer.cfg is CRLF); compare decoded
            # text so the diff is readable, but never rewrite them on push.
            rl = rbytes.decode("utf-8", "replace").replace("\r\n", "\n").splitlines()
            ll = lbytes.decode("utf-8", "replace").replace("\r\n", "\n").splitlines()
            print("  %-24s DIFFERS  (machine %d lines, repo %d)" % (rel, len(rl), len(ll)))
            for line in list(difflib.unified_diff(ll, rl, "repo", "machine", lineterm="", n=1))[:40]:
                print("      " + line)
        elif a.pull:
            os.makedirs(os.path.dirname(local), exist_ok=True)
            open(local, "wb").write(rbytes)
            print("  %-24s PULLED  (%d bytes)" % (rel, len(rbytes)))
        elif a.push:
            if not a.yes:
                ans = input("  push %s -> %s ? [y/N] " % (rel, remote))
                if ans.strip().lower() not in ("y", "yes"):
                    print("  %-24s skipped" % rel)
                    continue
            with sftp.open(remote, "wb") as f:
                f.write(lbytes)
            print("  %-24s PUSHED  (%d bytes)" % (rel, len(lbytes)))

    if a.check:
        print("\n%s" % ("all in sync" if not drift else
                        "%d file(s) differ — THE MACHINE IS THE SOURCE OF TRUTH, "
                        "pull before editing" % drift))
    if a.push:
        print("\nNow: FIRMWARE_RESTART for .cfg, "
              "'sudo systemctl restart KlipperScreen' for clay.py, then verify "
              "over the Moonraker API.")
    return 1 if (a.check and drift) else 0


if __name__ == "__main__":
    sys.exit(main())
