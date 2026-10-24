#!/usr/bin/env bash
# Install the touchscreen session: systemd unit that starts X on tty1 and runs ControlCenter.
#   sudo bash install-touchui.sh           # dry run
#   sudo bash install-touchui.sh --yes
#   --user NAME       login that owns the session (default: pi)
#   --retire-legacy   also switch off the old boot-to-UI methods (tty1 autologin override, startx in the
#                     shell profile), each backed up as *.pre-touchui-<time>; without it they are only listed
set -euo pipefail
DO=0; U=pi; RETIRE=0; HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; TS="$(date +%Y%m%d-%H%M%S)"
while [ $# -gt 0 ]; do case "$1" in --yes) DO=1;; --user) U="$2"; shift;; --retire-legacy) RETIRE=1;; *) echo "unknown $1" >&2; exit 2;; esac; shift; done
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 2; }
run() { if [ "$DO" = 1 ]; then "$@"; else echo "   [dry-run] $*"; fi; }
H="$(getent passwd "$U" | cut -d: -f6)"; [ -n "$H" ] || { echo "no such user $U" >&2; exit 2; }

echo "== packages"
need=""; for p in xserver-xorg xinit x11-xserver-utils python3-pyqt5; do dpkg -s "$p" >/dev/null 2>&1 || need="$need $p"; done
[ -z "$need" ] || run apt-get install -y --no-install-recommends $need
[ -x /home/pi/OctoPrint/venv/bin/python ] || echo "WARN: OctoPrint venv missing; run its installer first (ControlCenter is installed into it)"

echo "== existing boot-to-UI methods that would fight this service$([ "$RETIRE" = 1 ] && echo ' (retired below)' || echo ' (report only; --retire-legacy switches them off)')"
for f in "$H/.bash_profile" "$H/.profile" "$H/.bashrc"; do grep -Hn "startx" "$f" 2>/dev/null || true; done
ls /etc/systemd/system/getty@tty1.service.d/ 2>/dev/null && cat /etc/systemd/system/getty@tty1.service.d/*.conf 2>/dev/null || true
systemctl list-unit-files 2>/dev/null | grep -iE "lightdm|gdm|sddm|lxdm" && echo "WARN: a display manager is installed; disable it" || true

if [ "$RETIRE" = 1 ]; then
  echo "== retire legacy boot-to-UI"
  for f in "$H/.bash_profile" "$H/.profile" "$H/.bashrc"; do
    grep -q "^[^#]*startx" "$f" 2>/dev/null || continue
    run cp -p "$f" "$f.pre-touchui-$TS"
    run sed -i '/^[^#]*startx/s/^/# disabled by fw-touchui: /' "$f"
  done
  for c in /etc/systemd/system/getty@tty1.service.d/*.conf; do
    [ -f "$c" ] && grep -q -- "--autologin" "$c" || continue
    run mv "$c" "$c.pre-touchui-$TS"    # tty1 goes back to a normal login prompt; fw-touchui owns the display
  done
fi

echo "== install"
if [ "$DO" = 1 ]; then
  command -v fw-rw >/dev/null && ! touch /etc/.rwtest 2>/dev/null && { fw-rw on; RWFLIP=1; } || RWFLIP=0; rm -f /etc/.rwtest
fi
[ -f "$H/.xinitrc" ] && ! cmp -s "$HERE/xinitrc.fw" "$H/.xinitrc" && run cp -p "$H/.xinitrc" "$H/.xinitrc.pre-touchui-$TS"
run install -m 755 -o "$U" -g "$U" "$HERE/xinitrc.fw" "$H/.xinitrc"
run sed "s#^User=.*#User=$U#; s#/home/pi#$H#g" "$HERE/fw-touchui.service" > /tmp/fw-touchui.service.$$
[ "$DO" = 1 ] && install -m 644 /tmp/fw-touchui.service.$$ /etc/systemd/system/fw-touchui.service; rm -f /tmp/fw-touchui.service.$$
run mkdir -p /etc/fw
run touch /etc/fw/touchui-managed
run usermod -aG video,input,tty,render "$U"
run systemctl daemon-reload
run systemctl enable fw-touchui.service
[ "${RWFLIP:-0}" = 1 ] && fw-rw off || true
echo "Done. Start now with:  sudo systemctl start fw-touchui   (logs: journalctl -u fw-touchui -b)"
