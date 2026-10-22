#!/usr/bin/env python3
"""Deploy the Fracktal software stack to a printer over SSH, step by step, from a PC.

Every step is a DRY RUN unless --yes is given, and prints exactly what it would do.
Typical order (docs/DEPLOYMENT.md):

    python deploy/deploy_printer.py workspace                 # clone/update the 4 repos next to this one
    python deploy/deploy_printer.py preflight                 # read-only: what is on the printer?
    python deploy/deploy_printer.py inspect-ui                # read-only: how does it boot to the UI today?
    python deploy/deploy_printer.py base      --yes           # hardening overlay, fw-health, helper scripts
    python deploy/deploy_printer.py klipper   --yes           # klipper_IDEX Production (+ python deps)
    python deploy/deploy_printer.py octoprint --yes           # NextGen OctoPrint + ControlCenter
    python deploy/deploy_printer.py touchui   --yes           # X on tty1 -> ControlCenter at boot
    python deploy/deploy_printer.py splash    --yes           # quiet boot + logo
    python deploy/deploy_printer.py commission --model twindragon-600-v2 --serial FW-0421 --yes
    python deploy/deploy_printer.py verify                    # read-only health report

Connection: PRINTER_SSH_HOST / PRINTER_SSH_USER (default pi) / PRINTER_SSH_PASSWORD or PRINTER_SSH_KEY,
from the environment or the repo's .env (never committed). Needs: pip install paramiko pyyaml python-dotenv
"""
import argparse
import json
import os
import posixpath
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASE_IMAGE = REPO / "base-image"
REPORTS = REPO / "deploy" / "reports"
REMOTE_DIR = "/home/pi/fw-deploy"

GITHUB = "https://github.com/FracktalWorks"
REPOS = {  # folder name -> (clone url, branch to use)
    "Fracktal_OctoPrint_NextGen": (f"{GITHUB}/Fracktal_OctoPrint_NextGen.git", "production"),
    "klipper_IDEX": (f"{GITHUB}/klipper_IDEX.git", "Production"),
    "ControlCenter": (f"{GITHUB}/ControlCenter.git", "production"),
}


def load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO / ".env")
    except ImportError:
        pass


class Printer:
    """Thin paramiko wrapper: run (streaming), upload directories, with dry-run support."""

    def __init__(self, host, user, password, key, apply):
        import paramiko
        self.apply, self.host, self.user = apply, host, user
        self.c = paramiko.SSHClient()
        self.c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kw = {"hostname": host, "username": user, "timeout": 20, "look_for_keys": True, "allow_agent": True}
        if key and os.path.exists(os.path.expanduser(key)):
            kw["key_filename"] = os.path.expanduser(key)
        if password:
            kw["password"] = password
        self.c.connect(**kw)
        self.sftp = self.c.open_sftp()

    def run(self, cmd, mutating=False, timeout=1800, check=True):
        """Run a remote command. Mutating commands are only printed unless --yes."""
        if mutating and not self.apply:
            print(f"   [dry-run] {cmd}")
            return 0, ""
        print(f"   $ {cmd}")
        _, out, _ = self.c.exec_command(cmd, get_pty=True, timeout=timeout)
        buf = []
        for line in iter(out.readline, ""):
            print("     " + line.rstrip())
            buf.append(line)
        rc = out.channel.recv_exit_status()
        if check and rc != 0:
            raise SystemExit(f"FAILED (exit {rc}): {cmd}")
        return rc, "".join(buf)

    def quiet(self, cmd):
        _, out, _ = self.c.exec_command(cmd, timeout=60)
        return out.read().decode(errors="replace").strip()

    def put_dir(self, local: Path, remote: str):
        # uploads go to a scratch folder under /home/pi, so they are harmless even in a dry run
        print(f"   upload {local} -> {remote}")
        self._mkdir(remote)
        for p in sorted(local.rglob("*")):
            rel = p.relative_to(local).as_posix()
            if any(x in rel.split("/") for x in (".git", "__pycache__", "reports")):
                continue
            r = posixpath.join(remote, rel)
            if p.is_dir():
                self._mkdir(r)
            else:
                data = p.read_bytes()
                if p.suffix in (".sh", ".service", ".plymouth", ".script", ".json", ".conf", ".fw") or p.name in (
                        "fw-health", "fw-updates", "fw-commission", "fw-lock-rootfs", "xinitrc.fw"):
                    data = data.replace(b"\r\n", b"\n")  # never ship CRLF to the Pi
                with self.sftp.open(r, "wb") as f:
                    f.write(data)
                self.sftp.chmod(r, 0o755 if p.suffix in (".sh", ".py") or p.name.startswith("fw-") else 0o644)

    def put_file(self, local: Path, remote: str):
        self._mkdir(posixpath.dirname(remote))
        self.sftp.put(str(local), remote)

    def _mkdir(self, path):
        parts, cur = path.strip("/").split("/"), ""
        for p in parts:
            cur += "/" + p
            try:
                self.sftp.stat(cur)
            except IOError:
                self.sftp.mkdir(cur)


def say(title):
    print(f"\n=== {title} " + "=" * max(3, 66 - len(title)))


def workspace_dir(args):
    return Path(args.workspace).resolve() if args.workspace else REPO.parent


def git(*a, cwd=None):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


# ── steps ─────────────────────────────────────────────────────────────────────

def step_workspace(args, _p):
    say("workspace: clone/update repos")
    ws = workspace_dir(args)
    for name, (url, branch) in REPOS.items():
        if name == "ControlCenter" and args.cc_ref:
            branch = args.cc_ref
        d = ws / name
        if not d.exists():
            print(f"   clone {url} -> {d}")
            if args.yes:
                subprocess.run(["git", "clone", url, str(d)], check=True)
        if d.exists() and args.yes:
            if git("status", "--porcelain", cwd=d):
                print(f"   SKIP {name}: local changes present, leaving it as is")
                continue
            git("fetch", "origin", cwd=d)
            git("checkout", branch, cwd=d)
            git("pull", "--ff-only", "origin", branch, cwd=d)
            print(f"   {name}: {branch} @ {git('rev-parse', '--short', 'HEAD', cwd=d)}")
        elif d.exists():
            print(f"   [dry-run] would checkout {branch} in {d}")


def step_preflight(args, p):
    say("preflight (read-only)")
    q = p.quiet
    info = {
        "os": q("grep PRETTY_NAME /etc/os-release | cut -d= -f2"),
        "arch": q("uname -m"), "kernel": q("uname -r"),
        "python3": q("python3 --version"),
        "free_home_mb": q("df -Pm /home | awk 'NR==2{print $4}'"),
        "root_mount": q("findmnt -no OPTIONS / | cut -d, -f1"),
        "octoprint_venv_version": q("/home/pi/OctoPrint/venv/bin/python -c 'import octoprint;print(octoprint.__version__)' 2>/dev/null") or "none",
        "klipper_dir": q("ls -d ~/klipper_IDEX ~/klipper 2>/dev/null | tr '\\n' ' '") or "none",
        "klipper_branch": q("git -C ~/klipper_IDEX branch --show-current 2>/dev/null") or "n/a",
        "fw_commissioned": q("test -e /etc/fw/commissioned && echo yes || echo no"),
        "undervoltage": q("vcgencmd get_throttled 2>/dev/null") or "n/a",
        "services": q("systemctl is-active klipper octoprint fw-health fw-touchui 2>/dev/null | tr '\\n' ' '"),
    }
    print(json.dumps(info, indent=2))
    problems = []
    if "trixie" not in info["os"].lower() and "13" not in info["os"]:
        problems.append("Not Debian 13: the NextGen OctoPrint needs Python >= 3.9. Older printers: STOP unless you are sure.")
    if info["octoprint_venv_version"].startswith("1.7."):
        problems.append("Legacy OctoPrint 1.7.x is installed: the octoprint step REPLACES it (old venv kept for rollback).")
    if info["root_mount"] == "ro":
        problems.append("Root is read-only: run 'sudo fw-rw on' on the printer first.")
    try:
        if int(info["free_home_mb"]) < 1500:
            problems.append("Less than 1.5 GB free in /home.")
    except ValueError:
        pass
    for x in problems:
        print("   !!", x)
    return info


def step_inspect_ui(args, p):
    say("inspect-ui (read-only): how does this unit boot to the UI today?")
    out = REPORTS / f"{args.host}-{time.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    probes = {
        "cmdline.txt": "cat /boot/firmware/cmdline.txt /boot/cmdline.txt 2>/dev/null",
        "config.txt": "cat /boot/firmware/config.txt /boot/config.txt 2>/dev/null",
        "xinitrc-global": "cat /etc/X11/xinit/xinitrc 2>/dev/null",
        "xinitrc-user": "cat ~/.xinitrc 2>/dev/null",
        "profile-startx": "grep -Hn startx ~/.bash_profile ~/.profile ~/.bashrc 2>/dev/null",
        "getty-override": "cat /etc/systemd/system/getty@tty1.service.d/*.conf 2>/dev/null",
        "units": "systemctl list-units --type=service --state=running --no-pager | grep -iE 'fw-|octoprint|klipper|lightdm|getty|plymouth|touch|x11'",
        "plymouth": "plymouth-set-default-theme 2>&1; ls /usr/share/plymouth/themes 2>&1; dpkg -l plymouth 2>&1 | tail -1",
        "x-and-controlcenter": "pgrep -a Xorg; pgrep -af 'main.py|octoprint_ControlCenter'",
        "display": "ls /sys/class/drm 2>/dev/null; cat /sys/class/graphics/fb0/virtual_size 2>/dev/null; ls /dev/input 2>/dev/null",
        "fstab": "cat /etc/fstab",
        "pip-venv": "/home/pi/OctoPrint/venv/bin/pip list 2>/dev/null | grep -iE 'octoprint|pyqt|opencv|websocket|requests|yaml'",
    }
    for name, cmd in probes.items():
        text = p.quiet(cmd)
        (out / f"{name}.txt").write_text(text + "\n", encoding="utf-8")
        print(f"   {name}: {len(text.splitlines())} lines")
    print(f"\n   Saved to {out}\n   Read these before running touchui/splash: they say what will be replaced.")


def step_base(args, p):
    say("base: hardening overlay + fw-health + helper scripts (apply.sh)")
    p.put_dir(BASE_IMAGE, f"{REMOTE_DIR}/base-image")
    flags = "--user " + args.user
    if args.full_base:
        flags += " --boot-tuning --nftables --hold-kernel --ext4-remount-ro"
    p.run(f"sudo sh {REMOTE_DIR}/base-image/apply.sh {flags}", mutating=True)


def step_klipper(args, p):
    say("klipper: klipper_IDEX Production + python deps (MCU firmware is NOT touched)")
    p.run("cd ~/klipper_IDEX && git status --porcelain | head -5", check=False)
    p.run("cd ~/klipper_IDEX && git fetch origin && git checkout Production && git pull --ff-only origin Production", mutating=True)
    p.run("~/klippy-env/bin/pip install -r ~/klipper_IDEX/scripts/klippy-requirements.txt", mutating=True)
    p.run("~/klippy-env/bin/python --version")
    if args.restart:
        p.run("sudo systemctl restart klipper", mutating=True)
    else:
        print("   Klipper NOT restarted (add --restart when no print is running).")


def step_octoprint(args, p):
    say("octoprint: NextGen OctoPrint + ControlCenter (fracktal/install-octoprint.sh)")
    ws = workspace_dir(args)
    src = ws / "Fracktal_OctoPrint_NextGen" / "fracktal"
    if not src.exists():
        raise SystemExit(f"{src} missing: run the 'workspace' step first")
    p.put_dir(src, f"{REMOTE_DIR}/octoprint-fracktal")
    op = (f"--version {args.op_version}" if args.op_version else
          f"--source {GITHUB}/Fracktal_OctoPrint_NextGen/archive/refs/heads/production.zip")
    # Default: the installer's own pinned ControlCenter (a tagged build with a real version number).
    cc = (f"--cc-source {args.cc_source}" if args.cc_source else
          f"--cc-source {GITHUB}/ControlCenter/archive/{args.cc_ref}.zip" if args.cc_ref else "")
    plugins = f' --plugins "{args.op_plugins}"' if args.op_plugins else ""  # TwinDragonPrintRestore is always added
    base = f"bash {REMOTE_DIR}/octoprint-fracktal/install-octoprint.sh {op} {cc}{plugins}"
    p.run(base)  # without --yes the installer only prints its plan
    if args.apply:
        p.run(base + " --yes")


def step_touchui(args, p):
    say("touchui: X on tty1 -> ControlCenter at boot (fw-touchui.service)")
    p.put_dir(BASE_IMAGE / "touchui", f"{REMOTE_DIR}/touchui")
    p.run(f"sudo bash {REMOTE_DIR}/touchui/install-touchui.sh --user {args.user}" + (" --yes" if args.apply else ""))
    if args.apply:
        print("   Installed. 'sudo systemctl start fw-touchui' (or reboot) starts it. Logs: journalctl -u fw-touchui -b")


def step_splash(args, p):
    say("splash: quiet boot + logo (Plymouth)")
    logo = Path(args.logo) if args.logo else (workspace_dir(args) / "ControlCenter" / "octoprint_ControlCenter" /
                                              "ui" / "resources" / "img" / "splash.png")
    if not logo.exists():
        raise SystemExit(f"logo not found: {logo} (pass --logo <png>)")
    p.put_dir(BASE_IMAGE / "splash", f"{REMOTE_DIR}/splash")
    p.put_file(logo, f"{REMOTE_DIR}/splash/logo.png")
    p.run("touch /etc/.rwtest 2>/dev/null && rm -f /etc/.rwtest || echo 'root is read-only: sudo fw-rw on first'", check=False)
    p.run(f"sudo bash {REMOTE_DIR}/splash/install-splash.sh --logo {REMOTE_DIR}/splash/logo.png" + (" --yes" if args.apply else ""))


def step_commission(args, p):
    say("commission: choose the printer model + give OctoPrint its own API key")
    models = json.loads((BASE_IMAGE / "commissioning" / "models.json").read_text(encoding="utf-8"))["models"]
    if args.model not in models or not args.serial:
        raise SystemExit("--model and --serial required. Models: " + ", ".join(models))
    m = models[args.model]
    rec = {"serial": args.serial, "model": args.model, "model_name": m["name"],
           "printer_cfg_include": m["include"], "toolheads": m["toolheads"], "hostname": f"fw-{args.serial}".lower()}
    print("   record:", json.dumps(rec))
    if args.apply:
        tmp = "/tmp/fw-commission.json"
        with p.sftp.open(tmp, "w") as f:
            f.write(json.dumps(rec, indent=2) + "\n")
    p.run("sudo sh -c 'B=/boot/firmware; [ -d $B ] || B=/boot; cp /tmp/fw-commission.json $B/fw-commission.json'", mutating=True)
    p.run("sudo /usr/local/sbin/fw-commission --force", mutating=True)
    print("   CAN UUIDs / MCU serials in printer.cfg are per board: set them by hand (see docs/DEPLOYMENT.md).")


def step_verify(args, p):
    say("verify (read-only)")
    p.run("systemctl is-active klipper octoprint fw-health fw-touchui", check=False)
    p.run("pgrep -a Xorg; pgrep -af 'octoprint_ControlCenter.*main.py|main.py' | head -3", check=False)
    p.run("curl -s -m 5 -o /dev/null -w 'OctoPrint HTTP %{http_code}\\n' http://127.0.0.1:5000/api/version", check=False)
    p.run("journalctl -u fw-touchui -b --no-pager -n 15", check=False)
    diag = REPO / ".github/skills/3d-printer-expert/scripts/pi_system_diagnostics.py"
    print("\n   Full report from this PC:")
    print(f"   python {diag} --host {args.host} --check all")


STEPS = {"workspace": step_workspace, "preflight": step_preflight, "inspect-ui": step_inspect_ui, "base": step_base,
         "klipper": step_klipper, "octoprint": step_octoprint, "touchui": step_touchui, "splash": step_splash,
         "commission": step_commission, "verify": step_verify}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=STEPS)
    ap.add_argument("--yes", action="store_true", help="really do it (default: dry run)")
    ap.add_argument("--host", default=None)
    ap.add_argument("--user", default=None, help="SSH/session user (default PRINTER_SSH_USER or pi)")
    ap.add_argument("--workspace", help="folder holding the cloned repos (default: parent of this repo)")
    ap.add_argument("--full-base", action="store_true", help="base: also boot tuning, nftables, kernel hold, ext4 remount-ro")
    ap.add_argument("--restart", action="store_true", help="klipper: restart the service afterwards")
    ap.add_argument("--op-version", help="octoprint: install this release (e.g. 1.11.8.post1) instead of the production branch")
    ap.add_argument("--cc-ref", help="octoprint: install ControlCenter from this branch/tag instead of the installer default (release 1.1.8)")
    ap.add_argument("--cc-source", help="ControlCenter pip source (URL or path); overrides --cc-ref")
    ap.add_argument("--op-plugins", help='octoprint: extra pip plugins, e.g. the ones the old venv had (installer lists them)')
    ap.add_argument("--logo", help="splash: PNG to show (default: ControlCenter's splash.png)")
    ap.add_argument("--model"); ap.add_argument("--serial")
    args = ap.parse_args(argv)
    args.apply = args.yes
    load_env()
    if args.step == "workspace":
        return step_workspace(args, None) or 0
    args.host = args.host or os.environ.get("PRINTER_SSH_HOST")
    args.user = args.user or os.environ.get("PRINTER_SSH_USER", "pi")
    if not args.host:
        sys.exit("Set PRINTER_SSH_HOST (in .env or the environment) or pass --host")
    try:
        import paramiko  # noqa: F401
    except ImportError:
        sys.exit("pip install paramiko python-dotenv pyyaml")
    p = Printer(args.host, args.user, os.environ.get("PRINTER_SSH_PASSWORD", ""), os.environ.get("PRINTER_SSH_KEY", ""), args.apply)
    print(f"Connected to {args.user}@{args.host}  [{'APPLY' if args.apply else 'DRY RUN - add --yes to apply'}]")
    STEPS[args.step](args, p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
