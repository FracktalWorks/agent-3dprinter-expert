#!/usr/bin/env python3
"""Deploy the Fracktal software stack to a printer over SSH, step by step, from a PC.

Every step is a DRY RUN unless --yes is given, and prints exactly what it would do.
Typical order (docs/DEPLOYMENT.md):

    python deploy/deploy_printer.py workspace --yes           # clone/update the repos next to this one
    python deploy/deploy_printer.py preflight                 # read-only: what is on the printer?
    python deploy/deploy_printer.py inspect-ui                # read-only: how does it boot to the UI today?
    python deploy/deploy_printer.py base      --yes           # hardening overlay, fw-health, helper scripts
    python deploy/deploy_printer.py configs   --yes           # Klipper configs -> ~/printer_data/config (+ links)
    python deploy/deploy_printer.py can                       # CAN boards + chip types; --set ... --yes writes UUIDs
    python deploy/deploy_printer.py klipper   --yes --restart # klipper_IDEX Production (+ python deps)
    python deploy/deploy_printer.py octoprint --yes           # NextGen OctoPrint + ControlCenter + plugins
    python deploy/deploy_printer.py touchui   --yes --retire-legacy   # X on tty1 -> ControlCenter at boot
    python deploy/deploy_printer.py webcam    --sensor ov5647 --yes   # Pi CSI camera -> MJPEG :8080
    python deploy/deploy_printer.py splash    --yes           # quiet boot + logo
    python deploy/deploy_printer.py commission --model twindragon-600-v2 --serial FW-0421 --yes
    python deploy/deploy_printer.py verify                    # read-only review; "!!" lines are problems

Long steps (octoprint, configs) run on the printer as a transient systemd unit and are followed from
here, so a dropped SSH/Wi-Fi connection does not kill them; the tool reconnects and keeps reading.

Connection: PRINTER_SSH_HOST / PRINTER_SSH_USER (default pi) / PRINTER_SSH_PASSWORD or PRINTER_SSH_KEY,
from the environment or the repo's .env (never committed). Needs: pip install paramiko pyyaml python-dotenv
"""
import argparse
import hashlib
import json
import os
import posixpath
import re
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASE_IMAGE = REPO / "base-image"
REMOTE_SCRIPTS = REPO / "deploy" / "remote"
REPORTS = REPO / "deploy" / "reports"
CACHE = REPO / "deploy" / "cache"          # downloaded release/plugin archives (gitignored)
REMOTE_DIR = "/home/pi/fw-deploy"

GITHUB = "https://github.com/FracktalWorks"
REPOS = {  # folder name -> (clone url, branch to use)
    "Fracktal_OctoPrint_NextGen": (f"{GITHUB}/Fracktal_OctoPrint_NextGen.git", "production"),
    "klipper_IDEX": (f"{GITHUB}/klipper_IDEX.git", "Production"),
    "ControlCenter": (f"{GITHUB}/ControlCenter.git", "production"),
    "OctoprintKlipperPlugin": (f"{GITHUB}/OctoprintKlipperPlugin.git", "production"),
}
LF_SUFFIXES = (".sh", ".py", ".service", ".plymouth", ".script", ".json", ".conf", ".fw")
LF_NAMES = ("fw-health", "fw-updates", "fw-commission", "fw-lock-rootfs", "xinitrc.fw")


def load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO / ".env")
    except ImportError:
        pass


class Printer:
    """Thin paramiko wrapper: run (streaming), detached units, uploads, with dry-run support."""

    def __init__(self, host, user, password, key, apply):
        self.apply, self.host, self.user = apply, host, user
        self._kw = {"hostname": host, "username": user, "timeout": 20, "look_for_keys": True, "allow_agent": True}
        if key and os.path.exists(os.path.expanduser(key)):
            self._kw["key_filename"] = os.path.expanduser(key)
        if password:
            self._kw["password"] = password
        try:
            self._connect()
        except Exception as e:  # Wi-Fi printers often refuse the first attempt
            print(f"   (first connection failed: {type(e).__name__}; retrying)")
            self.reconnect(tries=6, wait=10)

    def _connect(self):
        import paramiko
        self.c = paramiko.SSHClient()
        self.c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.c.connect(**self._kw)
        self.c.get_transport().set_keepalive(15)
        self.sftp = self.c.open_sftp()

    def reconnect(self, tries=40, wait=15):
        """Printers on Wi-Fi drop SSH sessions; keep retrying (about 10 min by default)."""
        for i in range(1, tries + 1):
            try:
                self.c.close()
            except Exception:
                pass
            try:
                self._connect()
                return
            except Exception as e:
                print(f"   (connection lost, retry {i}/{tries}: {type(e).__name__})", flush=True)
                time.sleep(wait)
        raise SystemExit("could not reconnect to the printer")

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

    def quiet(self, cmd, timeout=60):
        _, out, _ = self.c.exec_command(cmd, timeout=timeout)
        return out.read().decode(errors="replace").strip()

    def run_unit(self, unit, cmd, timeout=5400, check=True):
        """Run `cmd` (as root) in a transient systemd unit on the printer and follow its log.

        The unit keeps running when the SSH connection drops; this reconnects and continues
        reading from where it stopped (journal of this invocation only). Returns the exit status.
        """
        if not self.apply:
            print(f"   [dry-run] sudo systemd-run --unit={unit} {cmd}")
            return 0
        self.quiet(f"sudo systemctl stop {unit} 2>/dev/null; sudo systemctl reset-failed {unit} 2>/dev/null")
        started = self.quiet(f"sudo systemd-run --unit={unit} -p RemainAfterExit=yes {cmd} 2>&1")
        print("   " + started)
        inv = self.quiet(f"systemctl show {unit} -p InvocationID --value")
        if "Running as unit" not in started or not inv:
            raise SystemExit(f"could not start {unit}: {started}")
        cursor, t0, props = "", time.time(), {}
        while time.time() - t0 < timeout:
            try:
                after = f" --after-cursor={shlex.quote(cursor)}" if cursor else ""
                text = self.quiet(f"sudo journalctl _SYSTEMD_INVOCATION_ID={inv} -o cat --no-pager --show-cursor{after}")
                for line in text.splitlines():
                    if line.startswith("-- cursor: "):
                        cursor = line[len("-- cursor: "):]
                    elif line.strip() and not re.search(r"pam_unix|COMMAND=|^\s*pi : ", line):
                        print("     " + line, flush=True)
                show = self.quiet(f"systemctl show {unit} -p ActiveState -p SubState -p ExecMainStatus")
                props = dict(l.split("=", 1) for l in show.splitlines() if "=" in l)
                if props.get("SubState") in ("exited", "failed", "dead"):
                    break
            except Exception as e:  # dropped connection: the unit carries on, we reconnect
                print(f"   (lost connection: {type(e).__name__}; the job keeps running on the printer)", flush=True)
                self.reconnect()
                continue
            time.sleep(5)
        else:
            raise SystemExit(f"{unit} still running after {timeout}s: journalctl _SYSTEMD_INVOCATION_ID={inv}")
        rc = int(props.get("ExecMainStatus") or 0)
        self.quiet(f"sudo systemctl stop {unit} 2>/dev/null; sudo systemctl reset-failed {unit} 2>/dev/null")
        if check and rc != 0:
            raise SystemExit(f"FAILED (exit {rc}): {unit}")
        return rc

    def put_dir(self, local: Path, remote: str):
        # uploads go to a scratch folder under /home/pi, so they are harmless even in a dry run
        print(f"   upload {local} -> {remote}")
        self._mkdir(remote)
        for p in sorted(local.rglob("*")):
            rel = p.relative_to(local).as_posix()
            if any(x in rel.split("/") for x in (".git", "__pycache__", "reports", "cache")):
                continue
            r = posixpath.join(remote, rel)
            if p.is_dir():
                self._mkdir(r)
            else:
                data = p.read_bytes()
                if p.suffix in LF_SUFFIXES or p.name in LF_NAMES:
                    data = data.replace(b"\r\n", b"\n")  # never ship CRLF to the Pi
                with self.sftp.open(r, "wb") as f:
                    f.write(data)
                self.sftp.chmod(r, 0o755 if p.suffix in (".sh", ".py") or p.name.startswith("fw-") else 0o644)

    def put_file(self, local: Path, remote: str):
        self._mkdir(posixpath.dirname(remote))
        self.sftp.put(str(local), remote)

    def upload(self, local: Path, remote: str, tries=20):
        """Upload a large file: resume after dropped connections, verify sha256 on both ends."""
        want = hashlib.sha256(local.read_bytes()).hexdigest()
        size = local.stat().st_size
        for attempt in range(1, tries + 1):
            try:
                if self.quiet(f"sha256sum {shlex.quote(remote)} 2>/dev/null | cut -d' ' -f1") == want:
                    print(f"   {remote}: already there ({size / 1e6:.1f} MB, sha256 ok)")
                    return remote
                self._mkdir(posixpath.dirname(remote))
                try:
                    done = self.sftp.stat(remote).st_size
                except IOError:
                    done = 0
                if done >= size:  # same size but wrong content: start over
                    self.sftp.remove(remote)
                    done = 0
                with open(local, "rb") as src, self.sftp.open(remote, "ab" if done else "wb") as dst:
                    dst.set_pipelined(True)
                    src.seek(done)
                    for chunk in iter(lambda: src.read(256 * 1024), b""):
                        dst.write(chunk)
                if self.quiet(f"sha256sum {shlex.quote(remote)} | cut -d' ' -f1") == want:
                    print(f"   uploaded {local.name} -> {remote} ({size / 1e6:.1f} MB, sha256 ok)")
                    return remote
            except Exception as e:
                print(f"   upload {local.name}: attempt {attempt} interrupted ({type(e).__name__}), resuming", flush=True)
                self.reconnect()
        raise SystemExit(f"could not upload {local}")

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


# ── release / plugin archives (downloaded on the PC, uploaded to the printer) ─────────────────

def installer_pins(installer: Path):
    """ControlCenter source and default plugins pinned in fracktal/install-octoprint.sh."""
    text = installer.read_text(encoding="utf-8")
    vars_ = dict(re.findall(r'^([A-Z_]+)="([^"$]*)"', text, re.M))

    def value(name):
        m = re.search(rf'^{name}="([^"]*)"', text, re.M)
        if not m:
            raise SystemExit(f"{name} not found in {installer}")
        return re.sub(r"\$\{(\w+)\}", lambda v: vars_.get(v.group(1), v.group(0)), m.group(1))

    return value("CC_SOURCE"), value("DEFAULT_PLUGINS").split()


def cache_name(url):
    """Stable local file name for a GitHub archive/release URL, keeping pip's view of it intact."""
    m = re.search(r"github\.com/[^/]+/([^/]+)/archive/refs/tags/(.+\.(zip|tar\.gz))$", url)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return url.rstrip("/").rsplit("/", 1)[-1]


def download(url, dest: Path, tries=4):
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "fracktal-deploy"})
            with urllib.request.urlopen(req, timeout=60) as r, open(str(dest) + ".part", "wb") as f:
                for chunk in iter(lambda: r.read(1 << 20), b""):
                    f.write(chunk)
            os.replace(str(dest) + ".part", dest)
            print(f"   downloaded {url} ({dest.stat().st_size / 1e6:.1f} MB)")
            return dest
        except OSError as e:
            print(f"   download {url}: attempt {attempt} failed ({e})")
            time.sleep(5)
    raise SystemExit(f"could not download {url}")


def octoprint_release(version=None):
    """(tag, wheel URL) of a Fracktal_OctoPrint_NextGen release; latest when version is None."""
    api = "https://api.github.com/repos/FracktalWorks/Fracktal_OctoPrint_NextGen/releases/"
    api += f"tags/{version}" if version else "latest"
    with urllib.request.urlopen(urllib.request.Request(api, headers={"User-Agent": "fracktal-deploy"}), timeout=30) as r:
        rel = json.load(r)
    wheels = [a["browser_download_url"] for a in rel.get("assets", []) if a["name"].endswith(".whl")]
    if not wheels:
        raise SystemExit(f"release {rel.get('tag_name')} has no wheel asset")
    return rel["tag_name"], wheels[0]


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
        "mem_total_mb": q("free -m | awk '/Mem:/{print $2}'"),
        "network": q("ip -br addr | grep -v '^lo' | awk '{print $1\" \"$2}' | tr '\\n' ' '"),
        "root_mount": q("findmnt -no OPTIONS / | cut -d, -f1"),
        "octoprint_service": q("grep -h ExecStart= /etc/systemd/system/octoprint.service 2>/dev/null"),
        "octoprint_venv_version": q("/home/pi/OctoPrint/venv/bin/python -c 'import octoprint;print(octoprint.__version__)' 2>/dev/null") or "none",
        "klipper_dir": q("ls -d ~/klipper_IDEX ~/klipper 2>/dev/null | tr '\\n' ' '") or "none",
        "klipper_branch": q("git -C ~/klipper_IDEX branch --show-current 2>/dev/null") or "n/a",
        "klipper_local_changes": q("git -C ~/klipper_IDEX status --porcelain 2>/dev/null | wc -l"),
        "klipper_config": q("grep -oE '\\S+printer\\.cfg' ~/printer_data/systemd/klipper.env 2>/dev/null"),
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
    if "wlan" in info["network"] and "eth0 UP" not in info["network"]:
        problems.append("Printer is on Wi-Fi only: SSH sessions drop. Long steps run as systemd units and the tool "
                        "reconnects, but Ethernet is faster for the 120 MB of uploads.")
    if info["klipper_local_changes"] not in ("", "0"):
        problems.append("~/klipper_IDEX has local edits: the klipper step stops on them (git diff --ignore-cr-at-eol first).")
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


def remote_scripts(p):
    p.put_dir(REMOTE_SCRIPTS, f"{REMOTE_DIR}/remote")
    return f"{REMOTE_DIR}/remote"


def step_base(args, p):
    say("base: hardening overlay + fw-health + helper scripts (apply.sh)")
    p.put_dir(BASE_IMAGE, f"{REMOTE_DIR}/base-image")
    flags = "--user " + args.user
    if args.full_base:
        flags += " --boot-tuning --nftables --hold-kernel --ext4-remount-ro"
    p.run(f"sudo sh {REMOTE_DIR}/base-image/apply.sh {flags}", mutating=True)


def step_configs(args, p):
    say("configs: one config folder (~/printer_data/config) for Klipper, OctoKlipper and ControlCenter")
    rd = remote_scripts(p)
    p.run(f"sudo bash {rd}/configs-layout.sh {args.user}", check=False)   # always prints the plan
    if args.apply:
        p.run_unit("fw-deploy-configs", f"/bin/bash {rd}/configs-layout.sh {args.user} --yes")


def step_can(args, p):
    say("can: CAN boards (UUID + chip) and the UUIDs in printer.cfg")
    rd = remote_scripts(p)
    if args.endstops:
        p.run(f"python3 {rd}/klipper_api.py /home/{args.user} endstops 120", check=False)
        return
    if args.set:
        if len(args.set) not in (2, 3):
            raise SystemExit("--set MCU TOOLHEAD0 [TOOLHEAD1]")
        yes = " --yes" if args.apply else ""
        p.run(f"sudo bash {rd}/can-boards.sh {args.user} set {' '.join(args.set)}{yes}", check=False)
        return
    stop = " --stop-klipper" if args.stop_klipper else ""
    if stop and not args.apply:
        print("   [dry-run] --stop-klipper stops Klipper for ~30 s (heaters off): add --yes")
        stop = ""
    p.run(f"sudo bash {rd}/can-boards.sh {args.user} scan{stop}", check=False)
    print("   Manta = stm32h723 -> [mcu]; rp2040 boards = toolheads. Write them with:\n"
          "   deploy_printer.py can --set <mcu> <toolhead0> <toolhead1> --yes, then check left/right with --endstops")


def step_klipper(args, p):
    say("klipper: klipper_IDEX Production + python deps (MCU firmware is NOT touched)")
    p.run("cd ~/klipper_IDEX && git status --porcelain | head -5", check=False)
    p.run("cd ~/klipper_IDEX && git fetch origin && git checkout Production && git pull --ff-only origin Production", mutating=True)
    p.run("~/klippy-env/bin/pip install -r ~/klipper_IDEX/scripts/klippy-requirements.txt", mutating=True)
    p.run("~/klippy-env/bin/python --version")
    if args.restart:
        p.run("sudo systemctl restart klipper", mutating=True)
        if args.apply:
            rd = remote_scripts(p)
            p.run(f"python3 {rd}/klipper_api.py /home/{args.user} wait-ready 90", check=False)
    else:
        print("   Klipper NOT restarted (add --restart when no print is running).")


def step_octoprint(args, p):
    say("octoprint: NextGen OctoPrint + ControlCenter + plugins (fracktal/install-octoprint.sh)")
    ws = workspace_dir(args)
    src = ws / "Fracktal_OctoPrint_NextGen" / "fracktal"
    if not (src / "install-octoprint.sh").exists():
        raise SystemExit(f"{src} missing: run the 'workspace' step first")
    p.put_dir(src, f"{REMOTE_DIR}/octoprint-fracktal")
    installer = f"{REMOTE_DIR}/octoprint-fracktal/install-octoprint.sh"
    # Always a RELEASE: a branch archive has no version (OctoPrint calls itself 0+unknown).
    op = f"--version {args.op_version}" if args.op_version else ""
    cc = f"--cc-source {args.cc_source}" if args.cc_source else (
        f"--cc-source {GITHUB}/ControlCenter/archive/refs/tags/{args.cc_ref}.zip" if args.cc_ref else "")
    plugins = f' --plugins "{args.op_plugins}"' if args.op_plugins else ""
    p.run(f"bash {installer} {op} {cc}{plugins}", check=False)   # the installer's plan (dry run)
    if not args.apply:
        print("   With --yes the OctoPrint wheel, ControlCenter and the plugins are downloaded HERE and uploaded\n"
              "   (printer Wi-Fi timed out on the 120 MB ControlCenter archive); --online lets the printer fetch them.")
        return
    if not args.online:
        tag, wheel_url = octoprint_release(args.op_version)
        print(f"   OctoPrint release {tag}")
        pkgs = f"{REMOTE_DIR}/pkgs"
        op = "--source " + p.upload(download(wheel_url, CACHE / cache_name(wheel_url)), f"{pkgs}/{cache_name(wheel_url)}")
        cc_url, plugin_urls = installer_pins(src / "install-octoprint.sh")
        if not (args.cc_source or args.cc_ref):
            cc = "--cc-source " + p.upload(download(cc_url, CACHE / cache_name(cc_url)), f"{pkgs}/{cache_name(cc_url)}")
        local = [p.upload(download(u, CACHE / cache_name(u)), f"{pkgs}/{cache_name(u)}") for u in plugin_urls]
        plugins += f' --default-plugins "{" ".join(local)}"'
    rd = remote_scripts(p)
    p.run_unit("fw-deploy-octoprint", f"/bin/bash {rd}/octoprint-install.sh {args.user} {installer} {op} {cc}{plugins} --yes")
    print("   Next: deploy_printer.py verify")


def step_touchui(args, p):
    say("touchui: X on tty1 -> ControlCenter at boot (fw-touchui.service)")
    p.put_dir(BASE_IMAGE / "touchui", f"{REMOTE_DIR}/touchui")
    retire = " --retire-legacy" if args.retire_legacy else ""
    p.run(f"sudo bash {REMOTE_DIR}/touchui/install-touchui.sh --user {args.user}{retire}" + (" --yes" if args.apply else ""))
    if args.apply:
        print("   Installed. Reboot (or 'sudo systemctl start fw-touchui'). Logs: journalctl -u fw-touchui -b")


def step_webcam(args, p):
    say("webcam: Pi CSI camera -> MJPEG on :8080 (fw-webcam.service)")
    if not args.sensor:
        raise SystemExit("--sensor required: ov5647 (Camera v1.x), imx219 (v2), imx708 (v3), imx477 (HQ)")
    p.put_dir(BASE_IMAGE / "webcam", f"{REMOTE_DIR}/webcam")
    opts = f"--user {args.user} --sensor {args.sensor}" + (" --cam0" if args.cam0 else "")
    if args.webcam_args:
        opts += f" --args {shlex.quote(args.webcam_args)}"
    rc, plan = p.run(f"sudo bash {REMOTE_DIR}/webcam/install-webcam.sh {opts}", check=False)   # dry run
    if args.apply:  # apt install over the printer's network: run as a unit so a dropped SSH session is harmless
        p.run_unit("fw-deploy-webcam", f"/bin/bash {REMOTE_DIR}/webcam/install-webcam.sh {opts} --yes")
        if "REBOOT REQUIRED" in plan:
            print("   config.txt changed: reboot the printer (ask first), then 'verify'.")


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
    print("   CAN UUIDs are per board: deploy_printer.py can (list) / can --set ... --yes (write).")


def step_verify(args, p):
    say("verify (read-only review; '!!' lines are problems)")
    rd = remote_scripts(p)
    rc, out = p.run(f"bash {rd}/review.sh {args.user}", check=False)
    problems = [l.strip() for l in out.splitlines() if l.strip().startswith("!!")]
    print(f"\n   {len(problems)} problem(s)" + (":" if problems else "."))
    for x in problems:
        print("   " + x)
    return problems


STEPS = {"workspace": step_workspace, "preflight": step_preflight, "inspect-ui": step_inspect_ui, "base": step_base,
         "configs": step_configs, "can": step_can, "klipper": step_klipper, "octoprint": step_octoprint,
         "touchui": step_touchui, "webcam": step_webcam, "splash": step_splash, "commission": step_commission, "verify": step_verify}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=STEPS)
    ap.add_argument("--yes", action="store_true", help="really do it (default: dry run)")
    ap.add_argument("--host", default=None)
    ap.add_argument("--user", default=None, help="SSH/session user (default PRINTER_SSH_USER or pi)")
    ap.add_argument("--workspace", help="folder holding the cloned repos (default: parent of this repo)")
    ap.add_argument("--full-base", action="store_true", help="base: also boot tuning, nftables, kernel hold, ext4 remount-ro")
    ap.add_argument("--restart", action="store_true", help="klipper: restart the service afterwards (and wait for ready)")
    ap.add_argument("--op-version", help="octoprint: install this release (e.g. 1.11.8.post3); default: the latest release")
    ap.add_argument("--online", action="store_true", help="octoprint: let the printer download OctoPrint/plugins itself")
    ap.add_argument("--cc-ref", help="octoprint: install ControlCenter from this tag instead of the installer's pin")
    ap.add_argument("--cc-source", help="ControlCenter pip source (URL or path on the printer); overrides --cc-ref")
    ap.add_argument("--op-plugins", help='octoprint: extra pip plugins, e.g. ones the old venv had (installer lists them)')
    ap.add_argument("--retire-legacy", action="store_true", help="touchui: switch off tty1 autologin + startx in profiles")
    ap.add_argument("--stop-klipper", action="store_true", help="can: stop Klipper while scanning (claimed boards stay silent)")
    ap.add_argument("--set", nargs="+", metavar="UUID", help="can: write MCU TOOLHEAD0 [TOOLHEAD1] UUIDs into printer.cfg")
    ap.add_argument("--endstops", action="store_true", help="can: watch X endstops 2 min to tell left/right toolhead apart")
    ap.add_argument("--sensor", help="webcam: camera sensor overlay (ov5647 = Camera v1.x, imx219, imx708, imx477)")
    ap.add_argument("--cam0", action="store_true", help="webcam: camera on the CM4's CAM0 port (default CAM1 = Manta M8P)")
    ap.add_argument("--webcam-args", help='webcam: fw-webcam options, e.g. "--width 1296 --height 972 --fps 15 --rotate 180"')
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
