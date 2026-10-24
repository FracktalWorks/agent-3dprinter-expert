#!/bin/bash
# Run by deploy_printer.py (octoprint --yes) as a transient systemd unit, so a dropped SSH/Wi-Fi
# connection cannot kill the install half way. Stops the touchscreen UI while pip runs (a 1 GB CM4
# with the 15 s hardware watchdog rebooted once under that memory pressure), runs the NextGen
# installer as the printer user, then starts the UI again whatever the result.
#   usage: octoprint-install.sh <user> <installer> [installer args...]
set -u
U=$1; INSTALLER=$2; shift 2

touch_ui=""
if systemctl is-active -q fw-touchui; then touch_ui=fw-touchui
elif systemctl is-active -q getty@tty1; then touch_ui=getty@tty1; fi
if [ -n "$touch_ui" ]; then
    echo "==> stopping the touchscreen UI ($touch_ui) to free memory for pip"
    systemctl stop "$touch_ui"
fi
pkill -f "[p]ython3 main[.]py" || true    # ControlCenter started by the plugin itself (sudo startx)

sudo -u "$U" -H env PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10 bash "$INSTALLER" "$@"
rc=$?

if [ -n "$touch_ui" ]; then
    echo "==> starting the touchscreen UI again ($touch_ui)"
    systemctl start "$touch_ui" || true
fi
exit $rc
