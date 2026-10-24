#!/usr/bin/env bash
# Quiet, branded boot: no rainbow splash, no kernel logo/log spam, Plymouth logo until X takes over.
#   sudo bash install-splash.sh --logo splash.png            # dry run
#   sudo bash install-splash.sh --logo splash.png --yes
# Changes: Plymouth theme "fracktal"; cmdline.txt (+quiet splash ...); config.txt (disable_splash=1, boot_delay=0).
# Backs up both files. Rebuilds the initramfs (needs a writable root: run on the golden unit BEFORE sealing,
# or after `fw-rw on`). Idempotent.
set -euo pipefail
DO=0; LOGO=""; HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
while [ $# -gt 0 ]; do case "$1" in --yes) DO=1;; --logo) LOGO="$2"; shift;; *) echo "unknown $1" >&2; exit 2;; esac; shift; done
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 2; }
[ -f "$LOGO" ] || { echo "--logo <png> required (default in deploy_printer.py: base-image/splash/fracktal-boot-logo.png)" >&2; exit 2; }
run() { if [ "$DO" = 1 ]; then "$@"; else echo "   [dry-run] $*"; fi; }
B=/boot/firmware; [ -f $B/cmdline.txt ] || B=/boot
T=/usr/share/plymouth/themes/fracktal; TS=$(date +%Y%m%d-%H%M%S)
touch /etc/.rwtest 2>/dev/null && rm -f /etc/.rwtest || { echo "root is read-only: run 'fw-rw on' first" >&2; exit 2; }

dpkg -s plymouth >/dev/null 2>&1 || run apt-get install -y --no-install-recommends plymouth plymouth-themes
run install -d $T
run install -m 644 "$HERE/fracktal.plymouth" "$HERE/fracktal.script" $T/
run install -m 644 "$LOGO" $T/logo.png
run plymouth-set-default-theme -R fracktal      # also rebuilds the initramfs

echo "== $B/cmdline.txt"
cur=$(cat $B/cmdline.txt); new="$cur"
for w in quiet splash plymouth.ignore-serial-consoles logo.nologo vt.global_cursor_default=0 loglevel=3 consoleblank=0; do
  case " $new " in *" $w "*) continue;; esac
  # key=value: keep an existing value (e.g. loglevel=0 is quieter than 3; a second loglevel would win)
  case "$w" in *=*) case " $new " in *" ${w%%=*}="*) continue;; esac;; esac
  new="$new $w"; done
echo "   before: $cur"; echo "   after:  $new"
if [ "$DO" = 1 ]; then cp $B/cmdline.txt $B/cmdline.txt.pre-splash-$TS; printf '%s\n' "$new" > $B/cmdline.txt; fi

echo "== $B/config.txt"
[ "$DO" = 1 ] && cp -p $B/config.txt $B/config.txt.pre-splash-$TS
for kv in disable_splash=1 boot_delay=0; do
  k=${kv%%=*}
  if grep -qxE "$kv" $B/config.txt; then echo "   $kv already set"
  elif grep -qE "^$k=" $B/config.txt; then run sed -i -E "s/^$k=.*/$kv/" $B/config.txt
  else echo "   add $kv"; [ "$DO" = 1 ] && printf '%s\n' "$kv" >> $B/config.txt; fi
done
echo "Reboot to see it. Revert: restore $B/cmdline.txt.pre-splash-$TS / config.txt.pre-splash-$TS and run 'plymouth-set-default-theme -R <old>'."
