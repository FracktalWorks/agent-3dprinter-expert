#!/bin/sh
# slim.sh -- strip packages/files a shipping printer image does not need. Run as root ON the Pi.
#   sudo sh slim.sh            # dry run (apt simulation + sizes)
#   sudo sh slim.sh --yes      # do it
# What it removes (all verified unused on the Debian 13 reference unit; see README §9.6):
#   unused Xorg GPU/input drivers (the touchscreen UI uses fbdev+modesetting+libinput),
#   mesa-vulkan-drivers, Bluetooth stack (disabled by dtoverlay=disable-bt), rpi-connect-lite,
#   mkvtoolnix, orphaned kernel leftovers, non-English locales, package docs (copyright kept).
# What it KEEPS on purpose: Xorg + xinit + PyQt5 + python3-opencv (ControlCenter), the firmware
# toolchains (gcc-arm-none-eabi, gcc-avr, build-essential), wifi firmware.
# Idempotent. Not applied to older printers by apply.sh -- opt-in only.
set -eu
DO=0; [ "${1:-}" = "--yes" ] && DO=1
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
O="$(cd "$(dirname "$0")" && pwd)/overlay"
export DEBIAN_FRONTEND=noninteractive

PKGS="xserver-xorg-video-all xserver-xorg-video-amdgpu xserver-xorg-video-ati
xserver-xorg-video-nouveau xserver-xorg-video-radeon xserver-xorg-input-wacom
mesa-vulkan-drivers bluez bluez-firmware rpi-connect-lite mkvtoolnix"
TODO=""
for p in $PKGS; do dpkg -s "$p" >/dev/null 2>&1 && TODO="$TODO $p"; done

# the touchscreen UI depends on these; make sure autoremove can never take them
apt-mark manual xserver-xorg-video-fbdev xserver-xorg-input-libinput xserver-xorg-core xserver-xorg-legacy >/dev/null 2>&1 || true

echo "packages to purge:${TODO:- (none)}"
if [ "$DO" = 0 ]; then
    [ -n "$TODO" ] && apt-get -s purge $TODO | grep '^Purg' | awk '{print "  would purge", $2}'
    apt-get -s autoremove | grep '^Remv' | awk '{print "  autoremove would drop", $2}'
    du -sh /usr/share/locale /usr/share/doc 2>/dev/null
    echo "dry run -- add --yes"; exit 0
fi

[ -n "$TODO" ] && apt-get -y purge $TODO
apt-get -y autoremove --purge
apt-get clean

install -D -m 0644 "$O/etc/dpkg/dpkg.cfg.d/90-fw-slim" /etc/dpkg/dpkg.cfg.d/90-fw-slim
find /usr/share/locale -mindepth 1 -maxdepth 1 ! -name en ! -name en_GB ! -name locale.alias -exec rm -rf {} +
find /usr/share/doc -mindepth 2 \( -type f -o -type l \) ! -name copyright -delete
find /usr/share/doc -mindepth 1 -type d -empty -delete
echo "done. root usage:"; df -h / | tail -1
