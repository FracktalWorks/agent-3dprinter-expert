#!/bin/sh
# Apply the Fracktal Works base-image overlay to a printer Pi. Run as root, ON the Pi,
# from a copy of this directory.   sudo ./apply.sh [options]
#
# Safe set (always): sysctl hardening, journald cap, watchdog, fw-health, fw-updates
#   (auto-updates stay OFF), SSH hardening (only if sshd supports drop-ins).
# Opt-in (these can change behaviour on older/other printers):
#   --user NAME        SSH login to allow-list (default: pi). Must exist or the SSH step is skipped.
#   --boot-tuning      remove force_turbo/sd_overclock, fsck.mode=skip -> auto (backs up first)
#   --nftables         install the port-80 -> 5000 redirect rules (loopback-only output rule)
#   --hold-kernel      apt-mark hold the Raspberry Pi kernel packages
#   --ext4-remount-ro  tune2fs -e remount-ro on the root device
# Idempotent: safe to run repeatedly. Docs: base-image/README.md
set -eu

FW_USER=pi; BOOT_TUNING=0; NFT=0; HOLD=0; EXT4=0
while [ $# -gt 0 ]; do
    case "$1" in
        --user) FW_USER=$2; shift ;;
        --boot-tuning) BOOT_TUNING=1 ;;
        --nftables) NFT=1 ;;
        --hold-kernel) HOLD=1 ;;
        --ext4-remount-ro) EXT4=1 ;;
        *) echo "unknown option $1" >&2; exit 2 ;;
    esac; shift
done
[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo)" >&2; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd); O="$HERE/overlay"
log() { echo "[apply] $*"; }
put() { # put <mode> <relative path>
    install -D -m "$1" "$O/$2" "/$2"; log "installed /$2"
}

. /etc/os-release
log "target: ${PRETTY_NAME:-unknown} ($(uname -r)), user=$FW_USER"

# --- always-safe set -------------------------------------------------------
put 0644 etc/sysctl.d/99-fw-hardening.conf
sysctl -q --system >/dev/null 2>&1 || true
put 0644 etc/systemd/journald.conf.d/10-fw-journal.conf
put 0644 etc/systemd/system.conf.d/99-fw-watchdog.conf
systemctl restart systemd-journald || true
systemctl daemon-reexec || true

if command -v python3 >/dev/null 2>&1; then
    put 0755 usr/local/bin/fw-health
    put 0644 etc/systemd/system/fw-health.service
    systemctl daemon-reload
    systemctl enable --now fw-health || log "WARN: fw-health failed to start (see journalctl -u fw-health)"
else
    log "WARN: python3 missing; skipping fw-health"
fi

# --- unattended updates: installed, OFF by default -------------------------
if ! dpkg -s unattended-upgrades >/dev/null 2>&1; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq unattended-upgrades || log "WARN: could not install unattended-upgrades"
fi
put 0755 usr/local/sbin/fw-updates
put 0644 etc/apt/apt.conf.d/52fw-unattended-upgrades
install -d /etc/fw
if [ ! -f /etc/fw/auto-updates ]; then   # never flip an existing unit's choice
    put 0644 etc/apt/apt.conf.d/20auto-upgrades
    echo disabled > /etc/fw/auto-updates
fi
put 0644 etc/systemd/system/apt-daily-upgrade.timer.d/fw-window.conf
systemctl daemon-reload

# --- SSH hardening (password login stays ON) -------------------------------
if grep -qE '^\s*Include\s+/etc/ssh/sshd_config.d/' /etc/ssh/sshd_config && id "$FW_USER" >/dev/null 2>&1; then
    install -d /etc/ssh/sshd_config.d
    sed "s/@FW_USER@/$FW_USER/" "$O/etc/ssh/sshd_config.d/50-fw-hardening.conf" > /etc/ssh/sshd_config.d/50-fw-hardening.conf
    if sshd -t; then systemctl reload ssh 2>/dev/null || systemctl reload sshd; log "SSH hardening applied"
    else rm -f /etc/ssh/sshd_config.d/50-fw-hardening.conf; log "WARN: sshd -t failed, SSH change rolled back"; fi
else
    log "SKIP ssh hardening: sshd has no sshd_config.d Include, or user '$FW_USER' does not exist"
fi

# --- opt-in ------------------------------------------------------------------
if [ "$NFT" = 1 ]; then
    [ -f /etc/nftables.conf ] && cp -a /etc/nftables.conf "/etc/nftables.conf.bak-$(date +%Y%m%d)"
    put 0644 etc/nftables.conf
    nft -c -f /etc/nftables.conf && systemctl enable --now nftables && systemctl restart nftables
fi
if [ "$HOLD" = 1 ]; then
    apt-mark hold linux-image-rpi-v8 linux-image-rpi-2712 linux-headers-rpi-v8 linux-headers-rpi-2712 2>/dev/null || true
fi
if [ "$EXT4" = 1 ]; then
    tune2fs -e remount-ro "$(findmnt -no SOURCE /)" || log "WARN: tune2fs failed"
fi
if [ "$BOOT_TUNING" = 1 ]; then
    B=/boot/firmware; [ -f "$B/config.txt" ] || B=/boot
    D=$(date +%Y%m%d)
    cp -an "$B/config.txt" "$B/config.txt.bak-$D"; cp -an "$B/cmdline.txt" "$B/cmdline.txt.bak-$D"
    sed -i -e '/^force_turbo=1$/d' -e '/^dtparam=sd_overclock=[0-9]*$/d' "$B/config.txt"
    sed -i 's/fsck\.mode=skip/fsck.mode=auto/' "$B/cmdline.txt"
    log "boot tuning applied in $B (backups: *.bak-$D); reboot to take effect"
fi
log "done. Verify: python .github/skills/3d-printer-expert/scripts/pi_system_diagnostics.py --check base-image"
