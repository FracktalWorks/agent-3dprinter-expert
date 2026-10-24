#!/bin/bash
# Read-only review of a printer's OctoPrint / Klipper setup (deploy_printer.py verify).
# Lines starting with "!!" are problems.
U=${1:-pi}
H=$(getent passwd "$U" | cut -d: -f6); V=$H/OctoPrint/venv; B=$H/.octoprint; L=$B/logs/octoprint.log
CFG=$H/printer_data/config
echo "## OctoPrint"
echo "service: $(systemctl is-active octoprint) | $(grep -h ExecStart= /etc/systemd/system/octoprint.service)"
grep -q "$V/bin/octoprint" /etc/systemd/system/octoprint.service || echo "!! octoprint.service does not run the NextGen venv $V"
echo "api: HTTP $(curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:5000/api/version)"
S=$(grep -an "Starting OctoPrint" "$L" 2>/dev/null | tail -1 | cut -d: -f1)
if [ -n "$S" ]; then
    sed -n "${S}p" "$L" | cut -c1-90
    sed -n "$S,\$p" "$L" | grep -aq "SAFE MODE" && echo "!! OctoPrint is in SAFE MODE (third-party plugins off): sudo systemctl restart octoprint"
    sed -n "$S,\$p" "$L" | grep -aE ' - ERROR - ' | grep -av "health_check" | cut -c1-160 | sort -u | head -5 | sed 's/^/!! /'
fi
$V/bin/pip list 2>/dev/null | grep -iE "^octoprint |controlcenter|restore|octoklipper"
$V/bin/pip list 2>/dev/null | grep -qi octoklipper || echo "!! OctoKlipper is not installed in the NextGen venv"
echo "## Printer profile and config.yaml"
$V/bin/python - "$B" <<'PY'
import sys, yaml
B = sys.argv[1]
p = yaml.safe_load(open(B + "/printerProfiles/_default.profile"))
print("profile:", p["name"], "| extruders", p["extruder"]["count"],
      "| volume %sx%sx%s" % (p["volume"]["width"], p["volume"]["depth"], p["volume"]["height"]))
if p["name"] == "Default" or p["volume"]["width"] == 200.0:
    print("!! factory default printer profile (1.11.8.post2 bug or ControlCenter not configured)")
c = yaml.safe_load(open(B + "/config.yaml"))
def g(*k):
    d = c
    for x in k:
        d = d.get(x, {}) if isinstance(d, dict) else {}
    return d
if g("accessControl", "localNetworks") == ["0.0.0.0/0"]:
    print("!! accessControl.localNetworks is 0.0.0.0/0 (auto-login from anywhere; ControlCenter's template?)")
missing = {"tracking", "errortracking", "achievements"} - set(g("plugins", "_disabled") or [])
if missing:
    print("!! not disabled:", sorted(missing))
k = g("plugins", "klipper", "configuration") or {}
for key in ("config_path", "klipper_path", "logpath", "baseconfig"):
    if key in k:
        print("   OctoKlipper override %s = %s (the fork's default is the Fracktal layout)" % (key, k[key]))
if str(k.get("logpath", "")).endswith(".log"):
    print("!! OctoKlipper logpath must be a folder")
print("OctoPrint update check override:", g("plugins", "softwareupdate", "checks", "octoprint") or "none (FracktalWorks NextGen)")
PY
echo "## Klipper configs"
real=$(find "$CFG" -maxdepth 1 -name '*.cfg' ! -name 'printer-*_*.cfg' 2>/dev/null | wc -l)
echo "$CFG: $real config files, $(ls "$CFG" 2>/dev/null | grep -c 'printer-[0-9]\{8\}_') SAVE_CONFIG backups"
echo "$H symlinks: $(find "$H" -maxdepth 1 -name '*.cfg' -type l | wc -l), broken: $(find "$H" -maxdepth 1 -name '*.cfg' -xtype l | wc -l), real cfg left in $H: $(find "$H" -maxdepth 1 -name '*.cfg' -type f ! -name 'printer-*' | wc -l)"
[ "$(find "$H" -maxdepth 1 -name '*.cfg' -xtype l | wc -l)" = 0 ] || echo "!! broken config symlinks in $H"
grep -E "^\[include PRINTER_|^canbus_uuid" "$CFG/printer.cfg" 2>/dev/null | tr '\n' ' '; echo
python3 - "$H" <<'PY'
import json, socket, sys
def q(m, p=None):
    s = socket.socket(socket.AF_UNIX); s.connect(sys.argv[1] + "/printer_data/comms/klippy.sock"); s.settimeout(10)
    s.sendall(json.dumps({"id": 1, "method": m, "params": p or {}}).encode() + b"\x03"); b = b""
    while b"\x03" not in b:
        b += s.recv(65536)
    return json.loads(b.split(b"\x03")[0])["result"]
try:
    i = q("info")
except Exception as e:
    print("!! Klipper API not reachable:", e); sys.exit()
print("## Klipper:", i["state"], "|", i.get("config_file"))
if i["state"] != "ready":
    print("!!", (i.get("state_message") or "").splitlines()[0])
    sys.exit()
objs = q("objects/list")["objects"]
want = {o: ["mcu_version"] for o in objs if o.startswith("mcu")}
want.update({o: ["temperature", "target"] for o in objs if o.startswith(("extruder", "heater_bed")) and " " not in o})
st = q("objects/query", {"objects": want})["status"]
print("MCUs:", ", ".join("%s %s" % (k, v["mcu_version"]) for k, v in st.items() if k.startswith("mcu")))
print("heaters:", ", ".join("%s %.1f/%.0f" % (k, v["temperature"], v["target"]) for k, v in st.items() if not k.startswith("mcu")))
PY
echo "klipper_IDEX: $(git -C "$H/klipper_IDEX" rev-parse --short HEAD) on $(git -C "$H/klipper_IDEX" rev-parse --abbrev-ref HEAD), local changes: $(git -C "$H/klipper_IDEX" status --porcelain | wc -l)"
echo "## Touchscreen"
echo "fw-touchui: $(systemctl is-active fw-touchui)"
for p in $(pgrep -f "[p]ython3 main[.]py"); do echo "ControlCenter pid $p from $(readlink /proc/$p/cwd 2>/dev/null || sudo -n readlink /proc/$p/cwd)"; done
pgrep -f "[p]ython3 main[.]py" | while read -r p; do readlink /proc/$p/cwd 2>/dev/null || sudo -n readlink /proc/$p/cwd; done | grep -q "/oprint/" && echo "!! the touchscreen runs ControlCenter from the OLD venv ~/oprint: run the touchui step"
[ "$(pgrep -c Xorg)" -gt 1 ] && echo "!! $(pgrep -c Xorg) X servers (legacy startx and the plugin's sudo startx both running): touchui --retire-legacy"
echo "## Power"
vcgencmd get_throttled 2>/dev/null
