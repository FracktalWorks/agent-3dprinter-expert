#!/usr/bin/env bash
# Pi CSI camera -> MJPEG webcam on :8080 for OctoPrint/ControlCenter (fw-webcam.service).
#   sudo bash install-webcam.sh --sensor ov5647            # dry run
#   sudo bash install-webcam.sh --sensor ov5647 --yes
#   --sensor NAME   camera sensor overlay: ov5647 (Camera v1.x), imx219 (v2), imx708 (v3), imx477 (HQ)
#   --cam0          the camera is on the CM4's CAM0 port (default CAM1; the Manta M8P connector is CAM1)
#   --user NAME     printer user (default pi)
#   --args "..."    fw-webcam options (default "--width 1296 --height 972 --fps 15"; --rotate 180 etc.)
# What it changes (each file backed up as *.pre-webcam-<time>):
#   config.txt: dtoverlay=<sensor>[,cam0], camera_auto_detect=0, and gpu_mem >= 64 -- gpu_mem=16 loads the
#     cut-down firmware (start4cd.elf) that has no camera ISP and no JPEG/H.264 encoder: libcamera then
#     reports "rpicam-apps currently only supports the Raspberry Pi platforms"
#   apt: python3-picamera2 (no recommends); /usr/local/bin/fw-webcam + fw-webcam.service (enabled)
#   a ustreamer webcamd.service (USB cameras only) is stopped and disabled: it grabs /dev/video0 otherwise
#   OctoPrint classicwebcam stream/snapshot URLs -> http://<LAN IP>:8080/?action=stream|snapshot
#     ("/webcam/?action=stream" only works behind OctoPi's haproxy, which these printers do not have)
# A config.txt change needs a reboot; the script says so.
set -euo pipefail
DO=0; U=pi; SENSOR=""; PORT_OPT=""; ARGS="--width 1296 --height 972 --fps 15"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; TS="$(date +%Y%m%d-%H%M%S)"
while [ $# -gt 0 ]; do case "$1" in
  --yes) DO=1;; --user) U="$2"; shift;; --sensor) SENSOR="$2"; shift;; --cam0) PORT_OPT=",cam0";;
  --args) ARGS="$2"; shift;; *) echo "unknown $1" >&2; exit 2;; esac; shift; done
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 2; }
case "$SENSOR" in ov5647|imx219|imx708|imx477|imx296|imx500) ;; *) echo "--sensor ov5647|imx219|imx708|imx477 required" >&2; exit 2;; esac
run() { if [ "$DO" = 1 ]; then "$@"; else echo "   [dry-run] $*"; fi; }
H="$(getent passwd "$U" | cut -d: -f6)"
C=/boot/firmware/config.txt; [ -f "$C" ] || C=/boot/config.txt
REBOOT=0

echo "== $C"
want="dtoverlay=${SENSOR}${PORT_OPT}"
grep -nE "^(camera_auto_detect|gpu_mem|dtoverlay=(ov5647|imx[0-9]+))" "$C" || true
need_cfg=0
grep -qx "$want" "$C" || need_cfg=1
grep -qE "^dtoverlay=(ov5647|imx[0-9]+)" "$C" && ! grep -qx "$want" "$C" && need_cfg=1
grep -q "^camera_auto_detect=1" "$C" && need_cfg=1
gm=$(sed -n 's/^gpu_mem=\([0-9]*\).*/\1/p' "$C" | tail -1)
[ -n "$gm" ] && [ "$gm" -lt 64 ] && need_cfg=1
if [ "$need_cfg" = 1 ]; then
  echo "   -> $want, camera_auto_detect=0, gpu_mem=${gm:-<default>} -> $([ -n "$gm" ] && [ "$gm" -lt 64 ] && echo 64 || echo "${gm:-<default>}")"
  run cp -p "$C" "$C.pre-webcam-$TS"
  run sed -i -E '/^dtoverlay=(ov5647|imx[0-9]+)/d' "$C"
  run sed -i 's/^camera_auto_detect=1/camera_auto_detect=0/' "$C"
  if [ -n "$gm" ] && [ "$gm" -lt 64 ]; then
    # config.txt has no trailing comments: the note goes on its own line
    run sed -i "s/^gpu_mem=$gm\$/# gpu_mem >= 64: full firmware with camera ISP + JPEG encoder (fw-webcam)\ngpu_mem=64/" "$C"
  fi
  if [ "$DO" = 1 ]; then printf '\n# Pi CSI camera (fw-webcam)\n%s\n' "$want" >> "$C"; else echo "   [dry-run] append '$want' to $C"; fi
  REBOOT=1
else
  echo "   ok"
fi

echo "== packages"
dpkg -s python3-picamera2 >/dev/null 2>&1 && echo "   python3-picamera2 installed" || run apt-get install -y --no-install-recommends python3-picamera2

echo "== service"
if systemctl list-unit-files webcamd.service >/dev/null 2>&1 && systemctl cat webcamd 2>/dev/null | grep -q ustreamer; then
  echo "   webcamd (ustreamer, USB cameras) would grab /dev/video0: stopping + disabling it"
  run systemctl disable --now webcamd
fi
run install -m 755 "$HERE/fw-webcam.py" /usr/local/bin/fw-webcam
run sed "s#^User=.*#User=$U#" "$HERE/fw-webcam.service" > /tmp/fw-webcam.service.$$
[ "$DO" = 1 ] && install -m 644 /tmp/fw-webcam.service.$$ /etc/systemd/system/fw-webcam.service; rm -f /tmp/fw-webcam.service.$$
[ "$DO" = 1 ] && echo "FW_WEBCAM_ARGS=\"$ARGS\"" > /etc/default/fw-webcam || echo "   [dry-run] /etc/default/fw-webcam: FW_WEBCAM_ARGS=\"$ARGS\""
run systemctl daemon-reload
run systemctl enable fw-webcam.service
[ "$REBOOT" = 0 ] && run systemctl restart fw-webcam.service

echo "== OctoPrint webcam URLs"
IP=$(hostname -I | tr ' ' '\n' | grep -E '^(10|172\.(1[6-9]|2[0-9]|3[01])|192\.168)\.' | head -1)
STREAM="http://${IP}:8080/?action=stream"; SNAP="http://127.0.0.1:8080/?action=snapshot"
echo "   stream $STREAM  snapshot $SNAP  (stream URL uses the LAN IP: give the printer a fixed DHCP lease)"
if [ "$DO" = 1 ]; then
  systemctl stop octoprint
  cp -p "$H/.octoprint/config.yaml" "$H/.octoprint/config.yaml.pre-webcam-$TS"
  sudo -u "$U" "$H/OctoPrint/venv/bin/python" - "$H/.octoprint/config.yaml" "$STREAM" "$SNAP" <<'PY'
import sys, yaml
p, stream, snap = sys.argv[1:4]
c = yaml.safe_load(open(p))
w = c.setdefault("plugins", {}).setdefault("classicwebcam", {})
w.update(stream=stream, snapshot=snap, streamRatio="4:3")
yaml.safe_dump(c, open(p, "w"), sort_keys=False, default_flow_style=False)
PY
  systemctl start octoprint
fi

if [ "$REBOOT" = 1 ]; then echo "REBOOT REQUIRED (config.txt changed): sudo reboot"; else echo "Done: curl -s -o /dev/null -w '%{http_code}' 'http://127.0.0.1:8080/?action=snapshot'"; fi
