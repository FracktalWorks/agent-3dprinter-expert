#!/bin/sh
# seal-image.sh -- LAST step on the golden printer before you copy the SD card (and PiShrink it).
# Removes everything that must be unique per printer or must not ship, then (optionally)
# powers off. Run as root ON the golden unit:
#
#   sudo sh seal-image.sh              # dry run: prints what it would do
#   sudo sh seal-image.sh --yes        # do it
#   sudo sh seal-image.sh --yes --poweroff
#   options: --keep-wifi   keep saved Wi-Fi profiles (default: delete -- they hold your Wi-Fi password)
#
# DESTRUCTIVE for this unit: after sealing it has no SSH host keys, machine-id, Wi-Fi or history.
# Do not run it on a printer you still need to reach over the network. Each per-printer
# personalisation (hostname, Wi-Fi, password hash, instance-id) is written to the boot partition's
# cloud-init seed when the image is flashed -- see base-image/README.md "Deployment".
set -eu

DO=0; POWEROFF=0; KEEP_WIFI=0
for a in "$@"; do
    case "$a" in
        --yes) DO=1 ;; --poweroff) POWEROFF=1 ;; --keep-wifi) KEEP_WIFI=1 ;;
        *) echo "unknown option $a" >&2; exit 2 ;;
    esac
done
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
[ "$DO" = 1 ] || echo "== DRY RUN (add --yes to execute) =="

B=/boot/firmware; [ -d "$B" ] || B=/boot
UHOME=${SUDO_USER:+/home/$SUDO_USER}; UHOME=${UHOME:-/home/pi}

step() { echo; echo "## $*"; }
run() {
    if [ "$DO" = 1 ]; then echo "+ $*"; sh -c "$*" || echo "  (non-fatal failure: $*)"; else echo "  [would run] $*"; fi
}

step "Stop services that write logs/state"
run "systemctl stop klipper octoprint fw-health 2>/dev/null || true"

step "Package caches"
run "apt-get clean"
run "rm -rf /var/lib/apt/lists/*"

step "Logs"
run "journalctl --rotate"
run "journalctl --vacuum-time=1s"
run "rm -rf /var/log/journal/*"
run "find /var/log -type f \\( -name '*.gz' -o -name '*.[0-9]' -o -name '*.old' \\) -delete"
run "find /var/log -type f -name '*.log' -exec truncate -s 0 {} +"
run "rm -f $UHOME/printer_data/logs/* $UHOME/.octoprint/logs/* 2>/dev/null || true"
run "rm -rf /var/lib/systemd/coredump/* /var/crash/* 2>/dev/null || true"

step "Shell history / caches (may contain secrets)"
run "rm -f $UHOME/.bash_history /root/.bash_history $UHOME/.python_history $UHOME/.viminfo $UHOME/.lesshst /root/.viminfo"
run "rm -rf $UHOME/.cache/* /root/.cache/* 2>/dev/null || true"

step "Per-unit identity: SSH host keys + machine-id (regenerated on first boot)"
# regenerate_ssh_host_keys.service has ConditionFirstBoot=yes: it runs only when machine-id is
# empty, so BOTH must be reset together or clones will share host keys.
run "rm -f /etc/ssh/ssh_host_*"
run ": > /etc/machine-id"
run "rm -f /var/lib/dbus/machine-id && ln -s /etc/machine-id /var/lib/dbus/machine-id"
run "echo fw-printer > /etc/hostname"
run "sed -i 's/^127\\.0\\.1\\.1.*/127.0.1.1\\tfw-printer/' /etc/hosts"

step "Network state"
if [ "$KEEP_WIFI" = 1 ]; then echo "  (keeping Wi-Fi profiles: --keep-wifi)"; else
    run "rm -f /etc/NetworkManager/system-connections/*.nmconnection"
fi
run "rm -f /var/lib/NetworkManager/*.lease /var/lib/NetworkManager/secret_key /var/lib/dhcp/*.leases 2>/dev/null || true"

step "cloud-init: re-arm so the per-printer seed on the boot partition is applied at first boot"
run "rm -f /etc/cloud/cloud-init.disabled"
run "cloud-init clean --logs --seed"
run "printf 'instance-id: fw-golden-template\\n' > $B/meta-data"
# Wi-Fi is injected per printer at flash time; the template only brings up Ethernet.
run "printf 'network:\\n  version: 2\\n  ethernets:\\n    eth0:\\n      dhcp4: true\\n      optional: true\\n' > $B/network-config"

step "Boot partition leftovers"
run "rm -f $B/*.bak-* ; rm -rf $B/backup-*"

step "Secrets this script does NOT touch (handle in the Klipper/OctoPrint pass)"
echo "  - $UHOME/.octoprint/config.yaml : api key + server.secretKey are identical on every clone"
echo "  - $UHOME/printer_data/config/printer.cfg : CAN UUIDs / [mcu] serials are per-printer"
echo "  - $B/user-data : holds the fleet password HASH (and hostname) -- anyone with the card can read it"

step "Flush"
run "sync"
run "fstrim -v / 2>/dev/null || true"
if [ "$DO" = 1 ]; then
    echo; echo "== sealed. state check =="
    printf 'machine-id bytes: %s (expect 0)\n' "$(wc -c < /etc/machine-id)"
    printf 'ssh host keys   : %s (expect 0)\n' "$(ls /etc/ssh/ssh_host_* 2>/dev/null | wc -l)"
    printf 'wifi profiles   : %s\n' "$(ls /etc/NetworkManager/system-connections 2>/dev/null | wc -l)"
    [ "$POWEROFF" = 1 ] && { echo "powering off -- now copy the SD card"; sleep 2; poweroff; }
else
    echo; echo "dry run complete."
fi
