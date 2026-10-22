# Fracktal Works printer base image (Debian 13 "trixie")

The Linux layer under Klipper/OctoPrint on every new printer: what is configured, **why**,
how to re-apply it, and how to debug it. First built and verified on a CM4 + Manta M8P
unit (192.168.0.184, Oct 2026). Source of truth is `overlay/` + `apply.sh`; this file is the
explanation. Older printers (Debian 10-12) are **not** modified unless you opt in — see
[Older printers](#older-printers-compatibility).

## 1. Baseline decisions

| Decision | Choice | Why |
|---|---|---|
| Distro | Debian 13 "trixie" (Raspberry Pi OS Lite, arm64) | Current stable, newest release, longest support (security to ~2028, Debian LTS to ~2030 — confirm dates at debian.org/security before quoting to customers). |
| Kernel | Raspberry Pi `6.18.x` LTS series, **held** (`apt-mark hold linux-image-rpi-* linux-headers-rpi-*`) | 6.18 is a kernel.org longterm series. Held so a kernel never changes under a printer outside a tested image release. Rollback: boot files of the previous kernel are kept in `/boot/firmware/backup-6.12.75/`. |
| Auto-updates | Installed, **OFF by default**, per-printer switch | See §4. Security-only, no kernel/Pi repo, never reboots. |
| Login | `pi` + **one fleet password**, password SSH stays on | Chosen for supportability. Trade-off: one leaked password opens every unit reachable on the same network. Revisit (per-unit passwords / VPN / support keys) before exposing printers beyond a customer LAN. |
| CPU | `isolcpus=3 nohz_full=3 rcu_nocbs=3`, Klipper `CPUAffinity=3`, FIFO 99; governor `performance` | Pre-existing deliberate Klipper design (`klipper.service.d/override.conf`, `cpu-performance.service`). Kept. |
| Overclock | **None**: no `force_turbo`, no `sd_overclock` | `sd_overclock=100` risks SD corruption; `force_turbo` pins voltage/clock and idles hot (56 °C). |

## 2. What is applied (all under `overlay/`)

| File | Effect |
|---|---|
| `etc/sysctl.d/99-fw-hardening.conf` | `kernel.panic=10`, `panic_on_oops=1` (self-reboot on kernel crash); `kptr_restrict=2`, `dmesg_restrict=1`; `sysrq=176`; rp_filter / no redirects; `dirty_ratio=5`, `dirty_background_ratio=2`, `dirty_expire=1500` (less data at risk on power cut). Named `99-` so it loads **after** Debian's `50-default.conf` (which sets sysrq=438). |
| `etc/systemd/journald.conf.d/10-fw-journal.conf` | Persistent journal, capped 50 MB / 1 month, so undervoltage/thermal events survive a reboot. |
| `etc/systemd/system.conf.d/99-fw-watchdog.conf` | Hardware watchdog 15 s (Pi default drop-in is 1 min). Named `99-` to win over `/usr/lib/.../40-rpi-enable-watchdog.conf`. |
| `etc/ssh/sshd_config.d/50-fw-hardening.conf` | Password login ON; no root login; no X11; `AllowUsers <user>`; `MaxAuthTries 3`; `LoginGraceTime 30`. OpenSSH ≥9.8 also throttles repeat offenders (`PerSourcePenalties`) by default. |
| `etc/nftables.conf` | **NAT:** port 80 → OctoPrint :5000 for incoming traffic. The `output` rule is restricted to loopback — the original redirected *all outbound* port 80 to OctoPrint, which made `apt update` fail with "no longer has a Release file" (HTTP mirrors got OctoPrint 404s). **Firewall (`inet fw_filter`):** inbound default-deny; allows loopback, established/related, rate-limited ping, DHCP replies, and from private LAN ranges only: SSH 22 (≤20 new/min), web 80/5000, mDNS 5353 + SSDP 1900. Outbound unrestricted. Moonraker/Mainsail printers must uncomment the 443/7125 line. Test any change with a dead-man switch: `systemd-run --on-active=180 nft delete table inet fw_filter`, load, confirm a *new* SSH session works, then make permanent. |
| `usr/local/bin/fw-health` + `etc/systemd/system/fw-health.service` | Health monitor, see §3. |
| `usr/local/sbin/fw-updates` + `etc/apt/apt.conf.d/{20auto-upgrades,52fw-unattended-upgrades}` + `etc/systemd/system/apt-daily-upgrade.timer.d/fw-window.conf` | Update switch, see §4. |

Not in `overlay/` (done by flags in `apply.sh`, or manually):

* `config.txt`: removed `force_turbo=1`, `dtparam=sd_overclock=100`, a duplicate `disable_splash`.
* `cmdline.txt`: `fsck.mode=skip` → `fsck.mode=auto` (the old value contradicted `fsck.repair=yes`). Root `fsck` runs in the initramfs; systemd's own `systemd-fsck-root` is then skipped by design.
* ext4: `tune2fs -e remount-ro` (was `continue`) — a filesystem error now stops writes and shows up in `fw-health` instead of corrupting silently.

### Apply to a printer
```sh
# from the repo, copy base-image/ to the Pi (scp/sftp), then on the Pi:
sudo sh base-image/apply.sh --user pi                       # safe set
sudo sh base-image/apply.sh --user pi --boot-tuning --nftables --hold-kernel --ext4-remount-ro   # full new-image set
```
Idempotent. Verify from your PC:
```sh
python .github/skills/3d-printer-expert/scripts/pi_system_diagnostics.py --host <ip> --check base-image
python .github/skills/3d-printer-expert/scripts/pi_system_diagnostics.py --host <ip> --check fw-health
```

## 3. Health reporting (`fw-health`) — for debugging now, ControlCenter later

Reports only; **never powers off or pauses anything**. Every 5 s it writes `/run/fw-health/status.json`,
serves it at `http://127.0.0.1:8765/health` (localhost only), and logs each level change:
`journalctl -t fw-health`.

| Check | warn | critical | Notes |
|---|---|---|---|
| `temperature` | ≥ 70 °C | ≥ 80 °C | Firmware soft limit is `temp_limit=75` in config.txt; kernel emergency shutdown is at 110 °C (far away). |
| `throttle_flags` | freq-capped / throttled / soft-temp now, undervoltage since boot | undervoltage **now** | `vcgencmd get_throttled` bits. |
| `undervoltage_alarm` | – | alarm = 1 | `/sys/class/hwmon/*/in0_lcrit_alarm` (`rpi_volt`). **Unverified on this carrier board** — force a brown-out test with a bench supply before trusting a `0`. |
| `disk_free` | ≤ 15 % | ≤ 5 % | |
| `memory_available` | ≤ 80 MiB | ≤ 40 MiB | 1 GB RAM units. |
| `root_filesystem` | – | became read-only after boot | |
| `storage_errors` | – | any EXT4/I-O/mmc error in kernel log since boot | |
| `can0` | not up | – | |

Planned: ControlCenter polls `/health` (or follows the journal tag) and shows warnings; acting on a level
(e.g. pause the print on `critical` thermal) is the *consumer's* decision. Thresholds are constants at the
top of `fw-health` — make them per-printer via the commissioning manifest.

## 4. Updates policy

`sudo fw-updates status | on | off | dry-run | run-now` (default **off**; state in `/etc/fw/auto-updates`).
When on: nightly ~03:00-03:30, Debian **security** origin only. Excluded: `linux-image-*`, `linux-headers-*`,
`raspi-firmware`, `rpi-eeprom`, `rpi-swap`, `octoprint*`, `klipper*`, and the entire Raspberry Pi repo. **Never
auto-reboots**; `fw-updates status` shows "REBOOT REQUIRED". Kernel/firmware/Klipper move only with an image release.

## 5. Debug runbook (symptom → first command)

| Symptom | Look at |
|---|---|
| `apt update` → "no longer has a Release file" / 404 on mirrors | `sudo nft list ruleset` — an outbound `dport 80 redirect` must be loopback-only. |
| Klipper "Timeout on connect" / "Unable to connect" on a CAN printer | `pi_system_diagnostics.py --check can` — compare the UUIDs it prints with `[mcu] canbus_uuid` in printer.cfg. A copied config carries another printer's UUIDs. |
| Random reboots | `journalctl -b -1 -n 50`; `journalctl -t fw-health`; `--check power`. Watchdog (15 s) or `kernel.panic=10` reboots leave a journal trail (journal is persistent). |
| Undervoltage / throttling | `--check fw-health`, `--check power`. |
| Printer stops saving files / read-only | `--check storage` and `fw-health` `root_filesystem`/`storage_errors`; ext4 now remounts read-only on error. |
| Boot slow / stuck | `systemd-analyze blame`; `/boot/firmware/*.bak-*` hold the pre-change config. |
| SSH refuses a login | `AllowUsers` limits to one account; check `/etc/ssh/sshd_config.d/50-fw-hardening.conf`. Recovery: SD card → boot partition → cloud-init `user-data`/`meta-data` (change `instance-id` to force re-apply), or edit on the root partition. |

## 6. Facts about this image worth knowing

* USB-to-CAN bridge: the Manta M8P enumerates as `1d50:606f` ("Klipper stm32h723xx") using the `gs_usb` driver → `can0`. There is **no** `/dev/ttyACM*` / `serial/by-id` device — that is normal.
* CAN bitrate on this unit is **1,000,000** (`/etc/network/interfaces.d/can0`, RP2040 firmware `CANBUS_FREQUENCY=1000000`). Older docs say 500000 — the diagnostics now read the real value.
* Image provisioning is **cloud-init (NoCloud)** on the boot partition: `user-data` (user, password hash, hostname), `meta-data` (`instance-id`), `network-config` (Wi-Fi). cloud-init applies `user-data` once per `instance-id`; **changing `instance-id` re-applies it**. Only the SHA-512 hash is stored, never the plaintext.
* Klipper fork lives in `~/klipper_IDEX`, venv `~/klippy-env`, OctoPrint in `~/oprint`.
* Known harmless boot noise: `vc_sm_cma_vchi_init` / `bcm2835_mmal_vchiq` errors (legacy camera stack; `camera_auto_detect=0`).

## 7. Golden image: cleanup, sealing, shrinking, deployment

**Already done on the reference unit (Oct 2026):** removed the Pi 5 kernel (`-2712`), the old 6.12 kernel, all
`linux-headers`/`linux-kbuild` and the boot-partition rollback copy (~2 GB freed, 1082 → 1071 packages); apt cache
cleared. **Kept on purpose:** `gcc-arm-none-eabi`, `gcc-avr`, `build-essential`, `libnewlib-*` — printers compile
Klipper/Katapult MCU firmware on board from GitHub updates. Production media is **SD card** (not eMMC), so the
PiShrink + flash-an-image flow applies. Offline clock: `systemd-timesyncd` already restores the last synced time from
`/var/lib/systemd/timesync/clock`; `fake-hwclock` was tried and removed because Raspberry Pi OS masks its restore
service (it would only have added SD writes).

**Seal, copy, shrink:**
```sh
# 1. on the golden unit (DESTRUCTIVE for that unit -- it loses its identity and Wi-Fi):
sudo sh seal-image.sh            # dry run, read the plan
sudo sh seal-image.sh --yes --poweroff
# 2. SD card -> PC: read the whole card to a .img (dd / Win32DiskImager / rpi-imager "custom"), then
sudo pishrink.sh -z golden.img   # SUPERSEDED: owner chose Raspberry Pi's own resize instead -- see §9
```
`seal-image.sh` clears logs, shell history, apt lists, SSH host keys, **machine-id** (empty = systemd "first boot",
which is what makes `regenerate_ssh_host_keys.service` run — reset both together), Wi-Fi profiles, DHCP state, and re-arms
cloud-init with a template seed (`instance-id: fw-golden-template`, Ethernet-only network-config).

**Per-printer deployment (flash, then personalise):** the image boots with **cloud-init (NoCloud)** reading the FAT boot
partition. After flashing a card, write three files there — nothing else needs to change:
* `meta-data` → `instance-id: <unique per printer, e.g. serial>` (cloud-init re-applies the seed only when this changes)
* `user-data` → `hostname`, the `pi` user/password hash, timezone, and later a `runcmd:` that installs the ControlCenter
  client / pulls the release from GitHub, runs `apply.sh`, picks the printer-model config
* `network-config` → Wi-Fi SSID/passphrase (or just Ethernet DHCP)

`base-image/provision.py` (see §10) writes those files and checks them.
Known quirk: the current `user-data` lists `packages: [avahi-daemon]`, so a re-provisioned unit reinstalls avahi (needs
internet at first boot). Drop it from the template if mDNS is not wanted.

**Must be verified on a cloned card before trusting the image (not yet done):**
1. Root partition auto-expands on first boot after PiShrink (this image has Raspberry Pi OS's `rpi-resize.service`,
   currently disabled, and PiShrink adds its own hook — confirm exactly one of them runs).
2. New SSH host keys and a new machine-id appear; two units on one LAN do not collide (DHCP/mDNS).
3. cloud-init applies the per-printer seed and the unit gets the intended hostname/Wi-Fi/password.
4. `--check base-image` / `--check fw-health` are green on the clone.

## 8. Not done yet (roadmap)

1. **Read-only root + writable data partition.** Needs a repartition (this unit has one 59 GB root), so it belongs in the image *build*, not a live retrofit. **Design decided -- see §9** (stock Raspberry Pi resize service, fixed-size data partition, no PiShrink); to be built after the Klipper/OctoPrint pass. Until then: journaled ext4 + `errors=remount-ro` + small dirty-page backlog.
2. **Image build + CI/CD** (pi-gen/CustomPiOS in GitHub Actions; release tag + checksum; post-flash test run of `pi_system_diagnostics.py --check all`).
3. **Commissioning manifest** per printer model (CAN/SPI/display overlays on or off, thresholds, `fw-updates` default) and `provision.py`.
4. **Support access**: support SSH public keys on every unit; a VPN/tunnel for printers behind customer NAT.
5. **Ethernet-first networking** — this unit is Wi-Fi only (`wlan0` default route) and the link dropped SSH several times.
6. **Undervoltage detection test** with a bench supply.
7. **ControlCenter ↔ fw-health** integration.
8. **OctoPrint secrets per printer** (`api key`, `server.secretKey` are identical on every clone) and per-printer Klipper CAN UUIDs -- handled in the Klipper/OctoPrint pass.

## 9. Plan: read-only root + data partition + smallest image (DECIDED, not built yet)

Sequence the owner chose: finish the **OctoPrint + Klipper hardening first**, *then* image the SD card (the owner
images it; nothing is imaged or repartitioned before that). Resize uses Raspberry Pi's **own** first-boot mechanism,
not PiShrink.

### 9.1 How the official resize works (read from this Trixie image, Oct 2026)
* Add the word ` resize` to `cmdline.txt` → initramfs hook `/usr/share/initramfs-tools/scripts/local-premount/resize_early`
  runs `parted resizepart 2 <end of device>`, **only if the root partition is number 2**; then `systemd-growfs-root.service`
  grows the ext4 online and `rpi-resize.service` (a marker, `ConditionFirstBoot=yes`) + `fstrim` finish. It never touches any
  other partition. `raspi-config`'s "expand" likewise refuses unless root is the last partition.
* Consequence for a data partition: the stock service can only grow **root**, and root must be the physically last partition.
  There is **no official tool that shrinks** an image; shrinking is done by us with standard tools (`e2fsck`, `resize2fs`,
  `sfdisk`/`parted`, `truncate`) inside the build script -- no PiShrink.

### 9.2 Layout (stock resize service, unmodified)
```
p1  boot  FAT   ~256 MiB   /boot/firmware   mounted ro in production
p3  data  ext4  fixed (default 16 GiB, build parameter)   label FWDATA   mounted rw, noatime  -> /home, /var/log, ...
p2  root  ext4  last on disk, small in the image, grown to fill the card by the stock service   mounted ro
```
MBR slot numbers are independent of on-disk order, so `p2` can sit physically after `p3` (this is what `resize_early`
needs). Trade-off accepted: on a large card the read-only root grows far beyond what it needs, and data stays at its fixed
size. If data must scale with the card, fallback = copy `resize_early` to a `resize_data_early` hook aimed at the last
partition (~15 lines) -- then it is no longer the stock hook.

### 9.3 What must be writable (measured on the reference unit; everything else is read-only)
| Path | Why | Where |
|---|---|---|
| `/home` (klipper, printer_data, .octoprint, ControlCenter, klippy-env, firmware build trees) | the whole application + user data; firmware is compiled on board | **data** partition mounted on `/home` |
| `/var/log` | persistent journal for post-mortems (undervoltage, thermal) | data (bind) |
| `/var/lib/systemd` | `random-seed`, `timesync/clock` (offline-boot time), rfkill state | data (bind) |
| `/var/lib/NetworkManager`, `/etc/NetworkManager/system-connections` | leases/state; **user-entered Wi-Fi profiles must survive** | data (bind) |
| `/tmp`, `/run`, `/var/tmp` | scratch | tmpfs (already) |
| `/var/swap` (1 GB swapfile on the SD today!) | SD wear + needs rw root | **remove**; run zram-only (check `rpi-swap` config), or move to data |
| `/etc/resolv.conf` | rewritten by NetworkManager | symlink into `/run` |
| `/var/lib/alsa/asound.state`, `wtmp`, Xorg logs | noise | tmpfs / harmless failure |

### 9.4 Provisioning vs production
First boot needs a **writable** root and boot (cloud-init, new SSH host keys, machine-id commit, user/hostname). So the
image ships `rw`; a one-shot `fw-lock-rootfs.service` runs when provisioning has finished, sets `ro` on `/` and
`/boot/firmware` (fstab + `cmdline.txt`) and reboots once. Production boots are read-only for life. Maintenance
(updates, `fw-updates on/off`, config edits under `/etc`): `sudo fw-rw on` → `mount -o remount,rw / /boot/firmware`;
it reverts on reboot or `fw-rw off`. Kernel/firmware updates ship as image releases; auto-updates stay security-only and
wrap themselves in `fw-rw`. `fw-health` already alarms if root flips read-only unexpectedly (that is an ext4 error).

### 9.5 Build steps (WSL2 Ubuntu on the dev PC; it has `e2fsck resize2fs sfdisk losetup xz`, install `parted`)
1. Owner reads the finished SD card to `golden.img` (the whole device).
2. `losetup -fP golden.img`; `e2fsck -f` then `resize2fs -M` the root; `sfdisk` shrinks p2, creates `p3` data **before** root,
   re-places p2 at the end; copy `/home` + the writable `/var` dirs into data; write fstab (`ro` + tmpfs + binds);
   add ` resize` to `cmdline.txt`; run the seal steps (§7) against the mounted copy instead of a live unit; `truncate`
   the file to the end of root; `xz -T0` it.
3. Boot it on a spare card **before** declaring it good (checklist in §7, plus: root really is `ro`, `/home` is the data
   partition, resize grows only root, `fw-health` is green, `fw-rw on` works, a hard power-pull mid-print corrupts nothing).
Not scripted yet: waiting on the application-layer changes, so the layout is built once, against final content.

### 9.6 Slimming
**DONE on the reference unit (Oct 2026) and reproducible with `sudo sh slim.sh --yes`** (dry run by default; opt-in, never
run by `apply.sh`): purged the unused X GPU/input drivers, `mesa-vulkan-drivers`, `bluez*`, `rpi-connect-lite`, `mkvtoolnix`,
kernel leftovers (autoremove), trimmed locales to `en`/`en_GB` and package docs to `copyright` files only (`dpkg` exclude in
`overlay/etc/dpkg/dpkg.cfg.d/90-fw-slim` keeps them out on updates). 1071 → 1045 packages, ~0.5 GB freed; reboot-tested:
Xorg + ControlCenter (`main.py`), Klipper, OctoPrint, fw-health and the firewall all came back, no failed units.
The **firmware toolchain is kept for now** (owner decision; whether to move firmware builds to GitHub-released binaries is
deferred -- recommendation: CI-built signed binaries + a verified `fw-firmware` updater, which would free ~3.3 GB).
Original analysis below (some items remain open):
* **Keep (needed):** Xorg + `xinit` + PyQt5 -- `~/.xinitrc` launches the ControlCenter touchscreen app (`python3 main.py`) under X; there is no
  desktop environment/display manager to remove (target is `multi-user`). `python3-opencv` (ControlCenter camera tool-offset
  calibration uses `cv2`; its VTK/GDAL/LLVM dependencies come with it -- only shrinkable by moving to an OpenCV-headless build
  later). The firmware toolchains (`gcc-arm-none-eabi` 503 MB + `libnewlib-arm-none-eabi` 406 MB + `libstdc++-arm-none-eabi-newlib` **2.1 GB**,
  `gcc-avr` 257 MB, `avr-libc`) -- owner wants on-board firmware builds. *Open: the 2.1 GB newlib C++ library is probably only needed for
  C++ MCU builds; test a Klipper/Katapult build with `libstdc++-arm-none-eabi-newlib` removed.*
* **Safe to remove (simulated, no side effects):** unused X GPU/input drivers `xserver-xorg-video-{amdgpu,ati,nouveau,radeon,all}`,
  `xserver-xorg-input-wacom`; `mesa-vulkan-drivers` (149 MB); `bluez`, `bluez-firmware`, `rpi-connect-lite` (Bluetooth is disabled by `dtoverlay=disable-bt`);
  `mkvtoolnix` (no dependants). Docs/man/locales (~330 MB; keep `en_US`).
* **Decide:** `firmware-atheros/mediatek/realtek` (~200 MB; only needed for USB Wi-Fi dongles -- the CM4 uses the on-board brcm chip).
* **Home directory: DONE (Oct 2026), `/home/pi` 3.3 GB → 1.4 GB.** Removed `~/.cache`, junk logs, duplicate `Katapult` (byte-identical
  `.config` to `katapult`), `canboot` (old name of Katapult), `klipper-scripts` (clean upstream Klipper clone) -- all fully on GitHub; and
  `~/ControlCenter` (971 uncommitted changes + a nested clone), `~/octoprint_ControlCenter` and `~/TD600` (older untracked plugin variants),
  which were **archived first** to the dev PC (`Documents/printer-archives/ref-unit-192.168.0.184/2026-10-16/unique-app-copies.tar.gz`, gzip-tested,
  entry counts matched) and are NOT in this repo. ControlCenter *runs* from the OctoPrint venv (`octoprint_controlcenter 1.1.5`), not from a home clone.
  **Kept for development:** `klipper_IDEX` (Fracktal fork, branch `Production`; **3 uncommitted local edits**: `resonance_tester.py`, `shaper_calibrate.py`,
  untracked `scripts/elf2uf2.py` -- commit or back them up), `katapult` (+ its RP2040 `.config`/`out/`), `klippy-env`, `kiauh`, `make_uf2.py`, all `~/*.cfg`.
  Gap: no STM32H723 (Manta M8P) firmware `.config` exists on this unit -- only the RP2040 toolhead config.
  Lesson: when guarding deletes with git, use `git rev-list --branches --not --remotes` (an in-sync branch prints an empty `track`).

## 10. Application layer and commissioning (OctoPrint NextGen, Oct 2026)

**What runs on a new printer.** Klipper = `klipper_IDEX` branch `Production` (Klipper v0.13-based; deliberately *not* upgraded, the
RP2040 toolboards must keep matching). OctoPrint = **`Fracktal_OctoPrint_NextGen`** 1.11.x (branch `production`), installed by its own
`fracktal/install-octoprint.sh` into `~/OctoPrint/venv` (created with `--system-site-packages` so ControlCenter finds apt's PyQt5/OpenCV).
ControlCenter = `FracktalWorks/ControlCenter` release. Old printers (OctoPrint 1.7.x, `Fracktal_OctoPrint`) are never touched.
Check which generation a unit runs: `pi_system_diagnostics.py --host <ip> --check octoprint`.

**Who does what, and when**

| Step | Where | When | Tool |
|---|---|---|---|
| Build everything common (OS, Klipper, OctoPrint, ControlCenter, hardening, generic config) | the reference unit | once per image release | `apply.sh`, `install-octoprint.sh`, `slim.sh` |
| Seal, read card to `golden.img` | reference unit + PC | once per image release | `seal-image.sh`, `dd`/Imager |
| Re-layout (ro root, FWDATA, root last), compress | PC (WSL2/Linux, root) | once per image release | `build-image.sh` *(written, not yet run)* |
| Flash | PC | per printer | Raspberry Pi Imager / balenaEtcher |
| Personalise: serial, hostname, Wi-Fi, **model** | PC, card still in the reader | per printer, 30 s | `provision.py --boot <drive> --serial FW-0421 --model twindragon-600-v2` |
| First boot: grow root, new SSH keys + machine-id, apply hostname/Wi-Fi (cloud-init), activate the model's `PRINTER_*.cfg`, give OctoPrint its own API key | the printer | automatic, a few minutes | cloud-init + `fw-commission` |
| CAN UUIDs / MCU serials, calibration, touchscreen setup | the printer | by hand | ControlCenter / `agent-data/` runbooks |

So: **everything common is pre-installed on the card; only identity and model are applied after flashing.** `provision.py` merges into the
image's existing `user-data` (the fleet password hash survives), and `fw-commission` runs once (`/etc/fw/commissioned`, `--force` to redo).
Models are listed in `commissioning/models.json` (`provision.py --list-models`).

**Not yet verified on hardware:** `build-image.sh` end to end; `fw-commission` on a booted card; first-boot ordering of cloud-init vs
`fw-commission` vs Klipper; `fw-lock-rootfs` (§9.4, written, logic unit-tested, never booted: it flips `/` and `/boot/firmware` to `ro` and reboots once, and refuses unless FWDATA is mounted); `install-octoprint.sh` on a real unit.

## Older printers (compatibility)

The agent/harness scripts are version-tolerant by design and were checked against these differences:

| Area | Older (Buster/Bullseye/Bookworm) | Handling |
|---|---|---|
| Boot dir | `/boot` (≤ Bullseye) vs `/boot/firmware` (≥ Bookworm) | `pi_system_diagnostics.py`, `display_diagnostics.py`, `apply.sh` probe both. |
| Klipper path | `~/klipper` (stock) vs `~/klipper_IDEX` (Fracktal fork) | `--check can` tries both. |
| CAN bitrate | 500000 on older toolheads, 1000000 here | Diagnostics read the live value rather than asserting one. |
| `fw-health` / `fw-updates` | not installed | `--check fw-health` reports "not installed (older image)" instead of failing. `--check base-image` shows which parts are present. |
| `sshd_config.d` | Bullseye's sshd_config has no `Include` | `apply.sh` skips the SSH step if the Include is missing. |
| `AllowUsers` | older units may not use `pi` | `--user` flag; the step is skipped if the user does not exist (a wrong user would lock everyone out). |
| Python | `fw-health` is stdlib-only, Python ≥ 3.7 (Buster has 3.7) | – |
| Wi-Fi/network stack | NetworkManager (Bookworm+) vs dhcpcd/wpa_supplicant | Diagnostics only read; nothing here changes network config. |
| Boot tuning, nftables, kernel hold | may rely on the overclock / other firewall | **opt-in flags only** (`--boot-tuning`, `--nftables`, `--hold-kernel`). Never applied by default. |
| Package names | `unattended-upgrades` origin pattern `${distro_codename}-security` is right for Bullseye+; Buster uses `${distro_codename}/updates` | Do not apply the update policy to Buster as-is. |

Rule: a read-only diagnostic must work on any generation; anything that **changes** a printer is opt-in per flag
and documented here.
