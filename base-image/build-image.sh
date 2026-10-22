#!/usr/bin/env bash
# Build the production image (README §9) from a sealed golden image file.
#
#   sudo bash build-image.sh golden.img fw-printer.img            # DRY RUN: prints the plan, changes nothing
#   sudo bash build-image.sh golden.img fw-printer.img --yes      # build (Linux/WSL2, needs root, loop devices)
#   options: --data-size 16G   size of the writable data partition (default 16G)
#            --margin 256M     free space left in root so it can be edited
#
# Input : whole-card image of the sealed golden unit (seal-image.sh already run on it):
#         p1 FAT boot, p2 ext4 root (last).
# Output: p1 boot (unchanged) | p3 FWDATA ext4 (/home, /var/log, ... ) | p2 root (LAST, so Raspberry Pi's own
#         `resize` hook grows it on first boot). Root + boot are mounted read-only in production.
#
# STATUS: written from the §9 design and NOT YET RUN end to end. First run it on a copy, boot the result on a
# SPARE card, and walk the checklist in README §9.5 before trusting it. It only ever touches image FILES via
# loop devices (it refuses real block devices).
set -euo pipefail

IN="${1:-}"; OUT="${2:-}"; shift 2 2>/dev/null || true
DATA_SIZE=16G; MARGIN=256M; DO=0
while [ $# -gt 0 ]; do case "$1" in
  --yes) DO=1;; --data-size) DATA_SIZE="$2"; shift;; --margin) MARGIN="$2"; shift;;
  *) echo "unknown option $1" >&2; exit 2;; esac; shift; done
[ -f "$IN" ] && [ -n "$OUT" ] || { sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
[ -b "$IN" ] && { echo "refusing a block device as input; read the card to a file first" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "run as root (sudo)" >&2; exit 2; }
for t in losetup sfdisk e2fsck resize2fs mkfs.ext4 tune2fs rsync truncate blkid dd; do
  command -v $t >/dev/null || { echo "missing tool: $t (apt install e2fsprogs fdisk util-linux rsync)" >&2; exit 2; }
done

W="$(mktemp -d /tmp/fwbuild.XXXXXX)"; LOOP_IN=""; LOOP_OUT=""
cleanup() { set +e; for m in "$W/new/boot" "$W/new/root" "$W/new/data" "$W/old/root" "$W/old/boot"; do mountpoint -q "$m" && umount "$m"; done
            [ -n "$LOOP_IN" ] && losetup -d "$LOOP_IN"; [ -n "$LOOP_OUT" ] && losetup -d "$LOOP_OUT"; rm -rf "$W"; }
trap cleanup EXIT
say() { printf '\n==> %s\n' "$*"; }
run() { if [ "$DO" = 1 ]; then "$@"; else printf '   [dry-run] %s\n' "$*"; fi; }

to_bytes() { numfmt --from=iec "$1"; }
DATA_B=$(to_bytes "$DATA_SIZE"); MARGIN_B=$(to_bytes "$MARGIN")

say "Inspect $IN"
sfdisk -d "$IN" | sed 's/^/   /'
LABEL_ID=$(sfdisk -d "$IN" | sed -n 's/^label-id: //p')
SECTOR=512
P1_START=$(sfdisk -d "$IN" | awk -F'[=, ]+' '/img1 /{print $4}'); P1_SIZE=$(sfdisk -d "$IN" | awk -F'[=, ]+' '/img1 /{print $7}')
echo "   boot: start=$P1_START size=$P1_SIZE sectors, disk label-id=$LABEL_ID"
[ -n "$LABEL_ID" ] && [ -n "$P1_START" ] || { echo "cannot parse the partition table (expected an MBR image with p1 boot, p2 root)" >&2; exit 1; }

if [ "$DO" != 1 ]; then
  say "Plan (dry run)"
  cat <<EOF
   1. losetup the input; e2fsck -f + resize2fs -M on p2 to find the minimum root size (+ $MARGIN margin)
   2. new image = boot(p1, same label-id so PARTUUIDs keep working) + FWDATA p3 ($DATA_SIZE) + root p2 LAST
   3. dd boot; mkfs.ext4 -L FWDATA; rsync root -> new p2; move /home,/var/log,/var/lib/systemd,
      /var/lib/NetworkManager,/etc/NetworkManager/system-connections onto FWDATA and bind-mount them back
   4. fstab: / and /boot/firmware read-only, LABEL=FWDATA on /fwdata (rw,noatime), tmpfs for /tmp /var/tmp;
      cmdline.txt: add 'resize', keep root=PARTUUID=<label-id>-02
   5. truncate the image to the end of root, then xz -T0 it (checksum written next to it)
EOF
  exit 0
fi

say "Loop-mount input"
LOOP_IN=$(losetup -fP --show "$IN"); mkdir -p "$W/old/root" "$W/old/boot"
e2fsck -fy "${LOOP_IN}p2" || true
resize2fs -M "${LOOP_IN}p2"
BLOCKS=$(dumpe2fs -h "${LOOP_IN}p2" 2>/dev/null | awk -F: '/Block count/{gsub(/ /,"",$2);print $2}')
BSIZE=$(dumpe2fs -h "${LOOP_IN}p2" 2>/dev/null | awk -F: '/Block size/{gsub(/ /,"",$2);print $2}')
ROOT_B=$(( BLOCKS * BSIZE + MARGIN_B ))
ROOT_S=$(( (ROOT_B + SECTOR - 1) / SECTOR )); DATA_S=$(( DATA_B / SECTOR ))
P3_START=$(( P1_START + P1_SIZE )); P3_START=$(( (P3_START + 2047) / 2048 * 2048 ))
P2_START=$(( P3_START + DATA_S ));  P2_START=$(( (P2_START + 2047) / 2048 * 2048 ))
TOTAL_S=$(( P2_START + ROOT_S + 2048 ))
echo "   root min+margin: $ROOT_B bytes; layout sectors: p1@$P1_START p3@$P3_START p2@$P2_START total=$TOTAL_S"

say "Create output image and partition table"
rm -f "$OUT"; truncate -s $(( TOTAL_S * SECTOR )) "$OUT"
sfdisk "$OUT" <<EOF
label: dos
label-id: $LABEL_ID
unit: sectors

start=$P1_START, size=$P1_SIZE, type=c
start=$P2_START, size=$ROOT_S, type=83
start=$P3_START, size=$DATA_S, type=83
EOF
LOOP_OUT=$(losetup -fP --show "$OUT")

say "Copy boot, create root + data filesystems"
dd if="${LOOP_IN}p1" of="${LOOP_OUT}p1" bs=4M status=none
mkfs.ext4 -q -L rootfs "${LOOP_OUT}p2"
mkfs.ext4 -q -L FWDATA "${LOOP_OUT}p3"
mkdir -p "$W/new/root" "$W/new/data" "$W/new/boot"
mount "${LOOP_IN}p2" "$W/old/root" -o ro; mount "${LOOP_IN}p1" "$W/old/boot" -o ro
mount "${LOOP_OUT}p2" "$W/new/root"; mount "${LOOP_OUT}p3" "$W/new/data"; mount "${LOOP_OUT}p1" "$W/new/boot"

say "Copy system to new root, writable trees to FWDATA"
rsync -aHAX --numeric-ids "$W/old/root/" "$W/new/root/" --exclude=/home --exclude=/var/log --exclude=/var/swap
mkdir -p "$W/new/data"/{home,var-log,var-lib-systemd,var-lib-NetworkManager,nm-system-connections}
rsync -aHAX --numeric-ids "$W/old/root/home/" "$W/new/data/home/"
rsync -aHAX --numeric-ids "$W/old/root/var/log/" "$W/new/data/var-log/" 2>/dev/null || true
rsync -aHAX --numeric-ids "$W/old/root/var/lib/systemd/" "$W/new/data/var-lib-systemd/" 2>/dev/null || true
rsync -aHAX --numeric-ids "$W/old/root/var/lib/NetworkManager/" "$W/new/data/var-lib-NetworkManager/" 2>/dev/null || true
rsync -aHAX --numeric-ids "$W/old/root/etc/NetworkManager/system-connections/" "$W/new/data/nm-system-connections/" 2>/dev/null || true
mkdir -p "$W/new/root"/{home,var/log,var/lib/systemd,var/lib/NetworkManager,etc/NetworkManager/system-connections,fwdata}

say "fstab + cmdline.txt"
cat > "$W/new/root/etc/fstab" <<EOF
PARTUUID=${LABEL_ID#0x}-01  /boot/firmware  vfat  defaults  0  2
PARTUUID=${LABEL_ID#0x}-02  /               ext4  defaults,noatime  0  1
LABEL=FWDATA  /fwdata  ext4  defaults,noatime,nofail  0  2
/fwdata/home                    /home                               none  bind  0  0
/fwdata/var-log                 /var/log                            none  bind  0  0
/fwdata/var-lib-systemd         /var/lib/systemd                    none  bind  0  0
/fwdata/var-lib-NetworkManager  /var/lib/NetworkManager             none  bind  0  0
/fwdata/nm-system-connections   /etc/NetworkManager/system-connections  none  bind  0  0
tmpfs  /tmp      tmpfs  defaults,nosuid,nodev  0  0
tmpfs  /var/tmp  tmpfs  defaults,nosuid,nodev  0  0
EOF
# the data partition is mounted at /fwdata; its subdirectories are what gets bound
mount --bind "$W/new/data" "$W/new/root/fwdata" 2>/dev/null || true
umount "$W/new/root/fwdata" 2>/dev/null || true
CMD="$W/new/boot/cmdline.txt"
grep -qw resize "$CMD" || sed -i 's/$/ resize/' "$CMD"
sed -i 's/\bfsck.mode=skip\b/fsck.mode=auto/' "$CMD"
grep -q 'ro\b' "$CMD" || true
echo "   cmdline: $(cat "$CMD")"

say "Provisioning form: root + boot ship READ-WRITE; fw-lock-rootfs.service flips them to ro after fw-commission (README 9.4)"

say "Finish: shrink file to end of root, checksum, compress"
sync; umount "$W/new/boot" "$W/new/root" "$W/new/data" "$W/old/root" "$W/old/boot"
losetup -d "$LOOP_OUT"; LOOP_OUT=""; losetup -d "$LOOP_IN"; LOOP_IN=""
truncate -s $(( (P2_START + ROOT_S) * SECTOR )) "$OUT"
sha256sum "$OUT" > "$OUT.sha256"
xz -T0 -k -f "$OUT"
ls -lh "$OUT" "$OUT.xz"
echo "Next: boot it on a SPARE card and walk README §9.5 before declaring it good."
