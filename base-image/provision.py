#!/usr/bin/env python3
"""Personalise a flashed Fracktal printer SD card (Windows/Linux/macOS, no root needed).

After flashing the golden image, the card's FAT boot partition shows up as a drive. Point this at it:

    python provision.py --boot E:\\ --serial FW-0421 --model twindragon-600-v2 \\
                        --wifi-ssid Workshop --wifi-pass 's3cret'
    python provision.py --list-models
    python provision.py --boot E:\\ --serial FW-0421 --model dragon-400 --dry-run

It writes three cloud-init NoCloud files plus a commissioning record; on first boot cloud-init applies
them and `fw-commission` (installed on the image) activates the model config and gives the printer its
own OctoPrint API key. The existing user-data (fleet password hash etc.) is MERGED, never replaced.
Docs: base-image/README.md ("Commissioning").
"""
import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML is required:  pip install pyyaml")

MODELS_FILE = Path(__file__).with_name("commissioning") / "models.json"
SERIAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{2,30}$")
HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$")
COMMISSION_CMD = "/usr/local/sbin/fw-commission"
RECORD_NAME = "fw-commission.json"


def load_models(path=MODELS_FILE):
    return json.loads(Path(path).read_text(encoding="utf-8"))["models"]


def build(args, models, existing_user_data=None):
    """Return {filename: text}. Pure function so it can be unit tested."""
    if not SERIAL_RE.match(args.serial):
        raise ValueError("serial must be 3-31 chars of letters, digits, '-' (e.g. FW-0421)")
    if args.model not in models:
        raise ValueError(f"unknown model '{args.model}'. Known: {', '.join(models)}")
    hostname = (args.hostname or f"fw-{args.serial}").lower()
    if not HOST_RE.match(hostname):
        raise ValueError(f"invalid hostname '{hostname}'")
    if bool(args.wifi_ssid) != bool(args.wifi_pass is not None and args.wifi_ssid):
        pass  # ssid without pass = open network, allowed
    if args.wifi_pass and not args.wifi_ssid:
        raise ValueError("--wifi-pass given without --wifi-ssid")
    if args.wifi_pass and not (8 <= len(args.wifi_pass) <= 63):
        raise ValueError("Wi-Fi passphrase must be 8-63 characters")

    model = models[args.model]

    # meta-data: a NEW instance-id is what makes cloud-init re-apply the seed on this card
    meta = f"instance-id: fw-{args.serial}\nlocal-hostname: {hostname}\n"

    # user-data: merge into whatever the image already carries
    ud = dict(existing_user_data or {})
    ud["hostname"] = hostname
    ud["manage_etc_hosts"] = True
    if args.timezone:
        ud["timezone"] = args.timezone
    runcmd = [c for c in (ud.get("runcmd") or []) if COMMISSION_CMD not in str(c)]
    runcmd.append([COMMISSION_CMD])
    ud["runcmd"] = runcmd
    user_data = "#cloud-config\n" + yaml.safe_dump(ud, sort_keys=False, default_flow_style=False)

    # network-config (netplan v2): Ethernet DHCP always, Wi-Fi if given
    net = {"network": {"version": 2, "ethernets": {"eth0": {"dhcp4": True, "optional": True}}}}
    if args.wifi_ssid:
        ap = {"password": args.wifi_pass} if args.wifi_pass else {}
        net["network"]["wifis"] = {"wlan0": {"dhcp4": True, "optional": True,
                                             "access-points": {args.wifi_ssid: ap}}}
    network = yaml.safe_dump(net, sort_keys=False, default_flow_style=False)

    record = {
        "serial": args.serial, "model": args.model, "model_name": model["name"],
        "printer_cfg_include": model["include"], "toolheads": model["toolheads"],
        "hostname": hostname,
    }
    return {
        "meta-data": meta,
        "user-data": user_data,
        "network-config": network,
        RECORD_NAME: json.dumps(record, indent=2) + "\n",
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--boot", help="mounted boot (FAT) partition of the flashed card, e.g. E:\\ or /media/x/bootfs")
    ap.add_argument("--serial", help="unique printer serial, e.g. FW-0421")
    ap.add_argument("--model", help="model id, see --list-models")
    ap.add_argument("--hostname", help="default: fw-<serial>")
    ap.add_argument("--wifi-ssid")
    ap.add_argument("--wifi-pass")
    ap.add_argument("--timezone", default="Asia/Kolkata")
    ap.add_argument("--list-models", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print the files, write nothing")
    args = ap.parse_args(argv)

    models = load_models()
    if args.list_models:
        for k, v in models.items():
            print(f"{k:20} {v['name']:20} {v['include']}")
        return 0
    if not (args.boot and args.serial and args.model):
        ap.error("--boot, --serial and --model are required")

    boot = Path(args.boot)
    existing = None
    ud_path = boot / "user-data"
    if ud_path.exists():
        existing = yaml.safe_load(ud_path.read_text(encoding="utf-8")) or {}
    try:
        files = build(args, models, existing)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if not args.dry_run:
        if not (boot.is_dir() and ((boot / "cmdline.txt").exists() or (boot / "config.txt").exists())):
            print(f"ERROR: {boot} does not look like a Raspberry Pi boot partition (no cmdline.txt/config.txt)",
                  file=sys.stderr)
            return 2
    for name, text in files.items():
        if args.dry_run:
            print(f"--- {name}\n{text}")
        else:
            (boot / name).write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote {boot / name}")
    if not args.dry_run:
        print("Done. Eject the card, put it in the printer and power on; first boot applies this "
              "(allow a few minutes: it resizes the root partition and restarts services).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
