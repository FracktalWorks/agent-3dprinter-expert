#!/bin/bash
# CAN boards: list them (with chip type) and optionally write their UUIDs into printer.cfg.
#   can-boards.sh <user> scan                        read-only (stops Klipper briefly only with --stop-klipper)
#   can-boards.sh <user> scan --stop-klipper         boards Klipper already claimed only answer when it is stopped
#   can-boards.sh <user> set <mcu> <toolhead0> [<toolhead1>] [--yes]
# Manta M8P/M5P = stm32h723 (the [mcu]); RP2040 toolheads = rp2040. Which RP2040 is left (T0) and which is
# right (T1) cannot be read from software: after `set`, press each carriage's X endstop and check that the
# left one shows as stepper_x (deploy_printer.py can --endstops), else swap the two toolhead UUIDs.
set -u
U=$1; CMD=$2; shift 2
H=$(getent passwd "$U" | cut -d: -f6); K=$H/klipper_IDEX; PY=$H/klippy-env/bin/python
CFG=$H/printer_data/config/printer.cfg; [ -f "$CFG" ] || CFG=$(readlink -f "$H/printer.cfg")

case "$CMD" in
scan)
    stopped=0
    if [ "${1:-}" = "--stop-klipper" ]; then systemctl stop klipper; stopped=1; sleep 2; fi
    echo "can0: $(ip -details link show can0 2>/dev/null | grep -oE 'state [A-Z-]+|bitrate [0-9]+' | tr '\n' ' ')"
    uuids=$(timeout 20 "$PY" "$K/scripts/canbus_query.py" can0 2>&1 | grep -oE 'canbus_uuid=[0-9a-f]+' | cut -d= -f2)
    [ -n "$uuids" ] || echo "no unassigned boards answered (Klipper holds the ones it is connected to: add --stop-klipper)"
    for u in $uuids; do
        chip=$( (sleep 6) | timeout 12 "$PY" "$K/klippy/console.py" -c can0 "$u" 2>&1 | grep -oE 'MCU=[a-z0-9]+' | head -1 | cut -d= -f2)
        echo "board $u ${chip:-?}"
    done
    [ "$stopped" = 1 ] && systemctl start klipper
    echo "printer.cfg ($CFG):"; grep -A1 '^\[mcu' "$CFG" | grep -E '^\[|canbus_uuid' | paste - - | sed 's/^/  /'
    ;;
set)
    MCU=$1; T0=$2; T1=${3:-}; DO=0
    [ "${T1:-}" = "--yes" ] && { T1=""; DO=1; }; [ "${4:-}" = "--yes" ] && DO=1
    for u in $MCU $T0 $T1; do echo "$u" | grep -qE '^[0-9a-f]{12}$' || { echo "not a CAN uuid: $u"; exit 2; }; done
    python3 - "$CFG" "$MCU" "$T0" "$T1" "$DO" <<'PY'
import re, sys, time, shutil
cfg, mcu, t0, t1, do = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5] == "1"
s = old = open(cfg).read()
def put(section, uuid):
    global s
    pat = re.compile(r"^#?\[" + re.escape(section) + r"\]\n#?canbus_uuid:.*$", re.M)
    if not pat.search(s):
        sys.exit("no [%s] block (with a canbus_uuid line) in %s" % (section, cfg))
    s = pat.sub("[%s]\ncanbus_uuid: %s" % (section, uuid), s, count=1)
put("mcu", mcu); put("mcu toolhead0", t0)
if t1:
    put("mcu toolhead1", t1)
for a, b in zip(old.splitlines(), s.splitlines()):
    if a != b:
        print("  - %s\n  + %s" % (a, b))
if not do:
    print("dry run; add --yes"); sys.exit()
import os
st = os.stat(cfg)
bak = cfg + ".pre-can-" + time.strftime("%Y%m%d-%H%M%S")
shutil.copy2(cfg, bak)
os.chown(bak, st.st_uid, st.st_gid)
open(cfg, "w").write(s)   # keeps the file's owner
print("written (backup next to it)")
PY
    [ "$DO" = 1 ] && { systemctl restart klipper; sudo -u "$U" python3 "$(dirname "$0")/klipper_api.py" "$H" wait-ready 90; }
    ;;
*) echo "usage: $0 <user> scan [--stop-klipper] | set <mcu> <toolhead0> [<toolhead1>] [--yes]"; exit 2 ;;
esac
