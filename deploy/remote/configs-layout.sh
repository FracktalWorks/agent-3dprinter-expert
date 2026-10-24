#!/bin/bash
# One home for the Klipper configs: ~/printer_data/config holds the real files.
#  - Klipper starts from ~/printer_data/config/printer.cfg (its SAVE_CONFIG renames that exact path,
#    so it must be a real file, never a symlink)
#  - /home/pi/<name>.cfg become symlinks, so ControlCenter (hard-coded /home/pi/) keeps reading and
#    writing the same files (it writes with open('w') / shutil.copy2, which follow symlinks)
#  - OctoKlipper (FracktalWorks fork >= 0.4.2) uses ~/printer_data/config by default
# Anything already in ~/printer_data/config that is not the live set is moved to config.old-<time>.
#   usage: configs-layout.sh <user> [--yes]        (run as root; dry run without --yes)
set -eu
U=$1; DO=0; [ "${2:-}" = "--yes" ] && DO=1
H=$(getent passwd "$U" | cut -d: -f6); NEW=$H/printer_data/config; ENV=$H/printer_data/systemd/klipper.env
TS=$(date +%Y%m%d-%H%M%S)
log() { echo "==> $*"; }
asu() { sudo -u "$U" "$@"; }

live=$(grep -oE '\S+printer\.cfg' "$ENV" 2>/dev/null | head -1 || true)
log "Klipper starts from: ${live:-<unknown, no $ENV>}"
real_in_home=$(find "$H" -maxdepth 1 -name '*.cfg' -type f ! -name 'printer-*' | wc -l)
if [ "$live" = "$NEW/printer.cfg" ] && [ "$real_in_home" -gt 0 ]; then
    echo "!! two config sets: Klipper reads $NEW but $H has $real_in_home real .cfg files (ControlCenter's)."
    echo "!! Compare them (versions, PRINTER_* include, canbus_uuid) and decide which is canonical by hand."
    exit 1
fi
if [ "$live" = "$NEW/printer.cfg" ] && [ -f "$NEW/printer.cfg" ] && [ ! -L "$NEW/printer.cfg" ]; then
    log "already on the $NEW layout"
    links=$(find "$H" -maxdepth 1 -name '*.cfg' -type l | wc -l); broken=$(find "$H" -maxdepth 1 -name '*.cfg' -xtype l | wc -l)
    log "  $links symlinks in $H, $broken broken"
    exit 0
fi
[ "$live" = "$H/printer.cfg" ] || { echo "!! expected Klipper to start from $H/printer.cfg (ControlCenter layout); stopping"; exit 1; }

moving=$(cd "$H" && for f in *.cfg; do case "$f" in printer-*.cfg) ;; *) [ -f "$f" ] && [ ! -L "$f" ] && echo "$f" ;; esac; done)
log "would move $(echo "$moving" | wc -w) config files from $H to $NEW (symlinks left behind):"
echo "$moving" | tr '\n' ' '; echo
[ -d "$NEW" ] && log "existing $NEW ($(ls "$NEW" | wc -l) files) -> $H/printer_data/config.old-$TS"
if [ "$DO" != 1 ]; then log "dry run; add --yes"; exit 0; fi

log "stopping OctoPrint and Klipper (heaters off)"
systemctl stop octoprint klipper
[ -d "$NEW" ] && asu mv "$NEW" "$H/printer_data/config.old-$TS"
asu mkdir -p "$NEW"
for f in $moving; do asu mv "$H/$f" "$NEW/$f"; asu ln -s "$NEW/$f" "$H/$f"; done
asu cp -p "$ENV" "$ENV.pre-layout-$TS"
sed -i "s#$H/printer.cfg#$NEW/printer.cfg#" "$ENV"
log "starting Klipper and OctoPrint"
systemctl start klipper
sudo -u "$U" python3 "$(dirname "$0")/klipper_api.py" "$H" wait-ready 90 || true
systemctl start octoprint
log "done. Rollback: stop klipper+octoprint; remove the symlinks in $H; mv $NEW/*.cfg $H/;"
log "  cp $ENV.pre-layout-$TS $ENV; mv $H/printer_data/config.old-$TS $NEW (after moving the files out)"
