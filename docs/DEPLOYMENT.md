# Deploying the Fracktal software stack on a printer

**Bottom line:** open this repo in Claude Code on your PC, tell it *"deploy the printer at 192.168.x.x as a TwinDragon 600 V2, serial FW-0421"*, and it follows `.claude/skills/deploy-printer/SKILL.md`: it runs `deploy/deploy_printer.py` one step at a time, shows you a dry run of each, and applies only when you say go. This page explains what each step does so you can check it, and what is still done by hand.

> **Verified status.** The first real deployment was the reference unit (192.168.0.184, CM4 1 GB + Manta M8P + 2 RP2040 CAN toolheads, Debian 13, Wi-Fi only) on 2026-10-22..24. Proven there: `base`, `klipper`, NextGen OctoPrint (1.11.8.post3), ControlCenter 1.1.8, TwinDragonPrintRestore 1.0.6, OctoKlipper 0.4.2 (Fracktal fork), the config folder layout, CAN UUIDs, `touchui --retire-legacy` (rootless X as `pi`), `verify`. **Not yet proven on hardware:** `splash`, `commission`, the image build. Every hard-won lesson is in [section 8](#8-what-went-wrong-on-the-first-deployment-and-what-prevents-it-now). Current state and next steps: [`docs/STATUS.md`](STATUS.md).

---

## 1. What you need

| Item | Notes |
|---|---|
| A PC (Windows/Linux/macOS) with Python 3.10+, git, Claude Code | Same network as the printer. Ethernet on the printer helps: it uploads ~130 MB. |
| This repo, plus its siblings | The `workspace` step clones `Fracktal_OctoPrint_NextGen`, `klipper_IDEX`, `ControlCenter`, `OctoprintKlipperPlugin` next to it. |
| `pip install -r requirements.txt` | paramiko (SSH), python-dotenv, pyyaml. |
| `.env` in the repo root (never committed) | `PRINTER_SSH_HOST=192.168.x.x`, `PRINTER_SSH_USER=pi`, and `PRINTER_SSH_PASSWORD=...` or `PRINTER_SSH_KEY=path`. Ask the team lead for the fleet password. |
| A printer with the Debian 13 base image | Raspberry Pi OS Lite arm64 (trixie), user `pi`, SSH on, internet access (GitHub, PyPI/piwheels, apt). See `base-image/README.md`. Older printers (Debian 10-12, OctoPrint 1.7.x) are a different generation: do not use these scripts on them without the team lead. |
| The printer on stable power and **not printing** | Undervoltage corrupts installs. |

Which OctoPrint goes where:

| Printer generation | OctoPrint | Repo it updates from |
|---|---|---|
| Old (Debian 10-12) | 1.7.x | `FracktalWorks/Fracktal_OctoPrint` |
| New (Debian 13) | 1.11.x | `FracktalWorks/Fracktal_OctoPrint_NextGen` (releases from branch `production`) |

Never install one on the other's printers.

## 2. The steps

Always: run a step **without** `--yes` first (dry run), read it, then add `--yes`. `verify` can be run at any time; lines starting with `!!` are problems.

| # | Command (`python deploy/deploy_printer.py ...`) | What it does | Check |
|---|---|---|---|
| 1 | `workspace --yes` | Clones/updates the four repos next to this one on the right branches. | Each repo listed with a commit id. |
| 2 | `preflight` | Read-only: OS, Python, RAM, network (Wi-Fi only?), OctoPrint service/venv, Klipper branch + local edits, Klipper config path, power, services. | No `!!` lines, or you understand each. |
| 3 | `inspect-ui` | Read-only: saves how the unit boots to its UI today to `deploy/reports/<host>-<time>/`. | `profile-startx.txt`, `getty-override.txt`, `xinitrc-*.txt`: what step 9 replaces. |
| 4 | `base --yes` | `base-image/apply.sh`: sysctl/journald/watchdog hardening, `fw-health`, update switch (auto-updates OFF), SSH hardening, `fw-commission`/`fw-lock-rootfs` (not enabled). `--full-base` adds boot tuning, firewall, kernel hold: **new images only**. | `pi_system_diagnostics.py --check base-image` green. |
| 5 | `configs --yes` | One config folder, section 5: real files in `~/printer_data/config`, symlinks in `/home/pi` for ControlCenter, Klipper started from the real path. Idempotent; stops if it finds two different config sets. | `verify`: N config files, 0 broken symlinks. |
| 6 | `can` | Lists the CAN boards with chip type and the UUIDs in `printer.cfg`, section 6. `--set MCU T0 T1 --yes` writes them; `--endstops` tells left from right. | `verify`: Klipper `ready`, all MCUs listed. |
| 7 | `klipper --yes --restart` | `klipper_IDEX` to `Production`, Klipper's Python packages into `~/klippy-env`, restart and wait for `ready` (sends `FIRMWARE_RESTART` if an MCU was left shut down). **MCU firmware is not touched.** Stops on local edits in `~/klipper_IDEX`. | `ready`, Python 3.13. |
| 8 | `octoprint --yes` | Downloads the latest NextGen **release** wheel, ControlCenter and the plugins **on the PC**, uploads them, then runs `fracktal/install-octoprint.sh` on the printer **as a systemd unit** with the touchscreen stopped (section 8, rows 1-4). The installer backs up `~/.octoprint`, keeps the old venv for rollback, installs OctoPrint + ControlCenter + TwinDragonPrintRestore + OctoKlipper (Fracktal fork) into `~/OctoPrint/venv`, keeps an existing `config.yaml`, installs `octoprint.service`; **any failure puts the old OctoPrint back**. `--op-version X` pins a release, `--online` lets the printer download everything itself. | "OctoPrint is up"; `verify` shows the versions and the printer profile. |
| 9 | `touchui --yes --retire-legacy` | `fw-touchui.service` + `~/.xinitrc`: X on tty1 runs ControlCenter from the NextGen venv. `--retire-legacy` switches off the old tty1 autologin and `startx` in `~/.bashrc` (backups `*.pre-touchui-<time>`). Section 3. | After reboot the screen shows ControlCenter 1.1.8; `verify` has no touchscreen `!!`. |
| 10 | `splash --yes` | Quiet boot, no rainbow screen, Fracktal logo. Section 4. | After reboot: logo, no scrolling text. |
| 11 | `commission --model <id> --serial FW-xxxx --yes` | Activates the model's `PRINTER_*.cfg` and gives OctoPrint its own API key. Models: `python base-image/provision.py --list-models`. | One active `[include PRINTER_*.cfg]`. |
| 12 | Reboot, then `verify` | The full review: services, versions, safe mode, errors since start, printer profile, config.yaml vs template, config folder + symlinks, Klipper state + MCUs + heaters, touchscreen, power. | `0 problem(s)`. |

**By hand (per printer):** calibration (Z offset, bed mesh, IDEX offsets: the `SAVE_CONFIG` block of a template is someone else's), touchscreen calibration, webcam.

**Rollback:** OctoPrint: `bash ~/fw-deploy/octoprint-fracktal/install-octoprint.sh --rollback --yes`. Configs: the `configs` step prints its rollback. Boot files: every change leaves `*.pre-splash-<time>`, `*.pre-commission-<time>`, `*.pre-touchui-<time>` backups next to the original. Touch UI: `sudo systemctl disable --now fw-touchui` and remove `/etc/fw/touchui-managed`.

## 3. Booting to ControlCenter (startx)

Chain at power-on: **Pi firmware** → **kernel** → **systemd** → `octoprint.service` and `klipper.service` → `fw-touchui.service` → `startx` on tty1 → `~/.xinitrc` → ControlCenter (`main.py`).

- `fw-touchui.service` runs as user `pi` on `tty1` with a login session (`PAMName=login`), so Xorg gets the display and touchscreen without root. It runs `startx /home/pi/.xinitrc -- :0 vt1 -nocursor`, restarts X if the UI exits (`Restart=always`) and `Conflicts=getty@tty1`.
- `~/.xinitrc` disables screen blanking, finds ControlCenter's folder with the **OctoPrint venv's** Python, `cd`s there (relative imports) and runs `main.py` with that Python. The venv sees apt's PyQt5/OpenCV (system site packages).
- The service creates `/etc/fw/touchui-managed`. Without it, ControlCenter's OctoPrint plugin rewrites `/etc/X11/xinit/xinitrc` and runs `sudo startx` on **every OctoPrint start**, which gives a second X server next to the legacy one (seen on the reference unit). ControlCenter 1.1.8+ skips this when the marker exists.
- The legacy way (autologin getty on tty1 + `startx` in `~/.bashrc` + a `~/.xinitrc` pointing at `~/oprint`) keeps running the OLD ControlCenter from the old venv until it is removed: use `--retire-legacy`, or remove it by hand. `inspect-ui` saved what was there.

**If the screen stays black or shows a console:**
1. `journalctl -u fw-touchui -b --no-pager | tail -50` (X errors, Python tracebacks).
2. `systemctl status fw-touchui` (restart loop?). `ls /var/log/Xorg*` or `~/.local/share/xorg/Xorg.0.log`.
3. Is ControlCenter installed in the venv? `/home/pi/OctoPrint/venv/bin/pip list | grep -i controlcenter`.
4. Rootless X refused (`no screens found`, `Permission denied` on `/dev/dri` or `/dev/input`)? Confirm `pi` is in groups `video input tty render` (reboot after `touchui`). Last resort: `User=root` in `/etc/systemd/system/fw-touchui.service` and `sudo` before the Python in `~/.xinitrc`; `daemon-reload` and restart. Tell the team lead (ControlCenter's files become root-owned).
5. Wrong or no display: `inspect-ui` saved `display.txt`. SPI TFT panels need a framebuffer copy service (like MANDEL's `fbcp`) that these scripts do not set up.

## 4. Boot screen and splash

| Stage | Controlled by | Set by `splash` |
|---|---|---|
| Pi rainbow screen | `disable_splash=1` in `config.txt` | yes (also `boot_delay=0`) |
| Kernel logo / log text | `cmdline.txt`: `quiet splash loglevel=3 logo.nologo vt.global_cursor_default=0 plymouth.ignore-serial-consoles consoleblank=0` | yes |
| Fracktal logo | Plymouth theme `fracktal` (black background, logo centred, at most 60% of screen width) in the initramfs | yes |
| Hand-off to X | `fw-touchui.service` starts after Plymouth quits | `touchui` |
| ControlCenter loading screen | ControlCenter itself (`ui/loading_screen`) | already part of the app |

The logo defaults to ControlCenter's `octoprint_ControlCenter/ui/resources/img/splash.png`; `--logo path.png` for another. It installs Plymouth if needed and rebuilds the initramfs, so it needs a **writable root** (`sudo fw-rw on` on a read-only unit). Revert: restore the `*.pre-splash-*` files, `sudo plymouth-set-default-theme -R <old theme>`. Needs a normal framebuffer/KMS display (HDMI/DSI); if the logo does not show, nothing else breaks.

## 5. Config files: one folder for Klipper, OctoKlipper and ControlCenter

| Who | Reads/writes |
|---|---|
| Klipper | `~/printer_data/config/printer.cfg` (path in `~/printer_data/systemd/klipper.env`) |
| OctoKlipper (Fracktal fork ≥ 0.4.2) | `~/printer_data/config` by default: the **Klipper Configuration** settings tab and the editor list every file |
| ControlCenter | `/home/pi/<name>.cfg` (hard-coded): symlinks to the files above |

- The real files must be in `~/printer_data/config`: Klipper's `SAVE_CONFIG` renames the exact path it was started with, so a symlinked `printer.cfg` would be replaced by a plain file. ControlCenter writes with `open('w')`/`shutil.copy2`, which go through a symlink.
- Edit in OctoKlipper (or anywhere under `printer_data/config`). Do not replace a `/home/pi/*.cfg` link with a copy.
- Do not point OctoKlipper at `/home/pi`: it registers its folder as an OctoPrint file storage and would index the ~50,000 files of the venvs.
- `printer.cfg` is the only per-printer file: exactly one `[include PRINTER_*.cfg]` and the board UUIDs. The canonical templates are `klipper_IDEX/fracktal_config/templates` (= ControlCenter's `firmware/`). Never edit the included files.
- ControlCenter **Settings → Restore print settings to default** (touchscreen) rewrites `printer.cfg` from its template (keeps MCU + `SAVE_CONFIG`) **and replaces OctoPrint's whole `config.yaml`** with ControlCenter's template (auto-login from anywhere, tracking on, old commands). The OctoKlipper locations survive (they are the plugin's defaults); re-run `verify` and fix the rest.

## 6. CAN boards

1. `can` lists the boards that answer on `can0` with their chip: `stm32h723` = the Manta → `[mcu]`; `rp2040` = toolheads. Boards Klipper is connected to stay silent: `can --stop-klipper --yes` (heaters off for ~30 s).
2. `can --set <mcu> <toolhead0> <toolhead1>` shows the `printer.cfg` change; add `--yes` to write it (backup `printer.cfg.pre-can-<time>`) and restart Klipper.
3. Left/right cannot be read from software: `can --endstops`, press the **left** carriage's X endstop, then the right one. Left must show as `stepper_x` (toolhead0); if it shows `dual_carriage`, swap the two toolhead UUIDs with `--set`.
4. The bus bitrate is in the board firmware: the reference unit's RP2040 toolheads run at 1 Mbit/s and `can0` at 1M. A board that never answers is a bitrate, wiring or termination problem, not a UUID problem.

## 7. Making an SD card image instead (many printers)

Build one unit with steps 4-10, `seal-image.sh`, read the card to `golden.img`, build the production layout with `base-image/build-image.sh` (Linux, root; not yet run end to end), flash, then on the PC: `python base-image/provision.py --boot <drive> --serial FW-0421 --model twindragon-600-v2 [--wifi-ssid ... --wifi-pass ...]`. First boot applies identity and model. Details and unproven items: `base-image/README.md` sections 9-10. `apply.sh --lock-rootfs` only on the image build, never on a live printer.

## 8. What went wrong on the first deployment, and what prevents it now

| # | What happened on the reference unit | Now |
|---|---|---|
| 1 | Wi-Fi dropped the SSH session mid-install twice; the installer died with it. | Long steps run as transient systemd units; the tool reconnects and keeps reading the log. |
| 2 | The printer timed out downloading ControlCenter (a 120 MB archive: wizard GIFs) from GitHub. | `octoprint` downloads releases/plugins on the PC and uploads them (resumable, sha256-checked). |
| 3 | A plugin failed after OctoPrint had been stopped: the printer was left without OctoPrint. | The installer puts the previous venv back and starts the old service on any failure. |
| 4 | The CM4 (1 GB, 15 s hardware watchdog) rebooted during a pip install. | The touchscreen UI (~370 MB) is stopped while pip runs. |
| 5 | Installing from `production.zip` gives OctoPrint version `0+unknown` (no tag in a branch archive). | Always a release; never a branch archive. Same rule for every plugin. |
| 6 | Upstream OctoKlipper's `setup.py` needs OctoPrint importable: `pip install` fails under build isolation. | FracktalWorks fork (`setup.py` fixed), installed by default. |
| 7 | 1.11.8.post2 reset the printer profile to "Default, 1 extruder": only one toolhead temperature. | Fixed in 1.11.8.post3 (`hasSecondaryHeaters` migration). `verify` flags a factory profile. |
| 8 | Klipper read an old Dragon 400 set in `printer_data/config` while ControlCenter used `/home/pi`; OctoKlipper showed an empty folder. | `configs` step (section 5). |
| 9 | Replaced boards: none of the `canbus_uuid`s matched (`mcu 'mcu': Serial connection closed`). | `can` step (section 6). |
| 10 | After the UUID fix the Manta reported "MCU ... is shutdown". | `klipper --restart` and `can --set` send `FIRMWARE_RESTART` once. |
| 11 | OctoPrint came up in **safe mode** (all plugins off) after an interrupted start. | `verify` flags it; `sudo systemctl restart octoprint`. |
| 12 | The old OctoPrint's Software Update replaced it with **upstream** OctoPrint 1.11.8 and offered ControlCenter 1.1.7. | NextGen updates only from FracktalWorks. On old installs: decline those updates. |
| 13 | OctoKlipper's Klipper Update would `git reset --hard origin/master` the IDEX fork. | Removed in the fork (0.4.2). Klipper is updated only by the `klipper` step. |
| 14 | `logpath` set to `.../klippy.log`: OctoKlipper expects a folder. | Template fixed; the fork defaults to `~/printer_data/logs` and accepts either. |
| 15 | Two touchscreen sessions (legacy `startx` + the plugin's `sudo startx`). | `touchui --retire-legacy`; `verify` flags it. |
| 16 | `M500` (= `SAVE_CONFIG`) runs after each Klipper start and adds a `printer-<date>.cfg` backup each time. | Not fixed yet (ControlCenter/macro); `verify` counts them. |

## 9. Updating a printer later

| What | How |
|---|---|
| OctoPrint (NextGen) | *Software Update* offers new `Fracktal_OctoPrint_NextGen` releases (Stable = `production`, Beta = `beta`). Publish: merge to `production`, tag `1.11.8.postN`, push the tag; CI runs the tests and publishes. Or re-run `octoprint --yes`. |
| ControlCenter | *Software Update* from `FracktalWorks/ControlCenter` releases. Never 1.1.7 or older on NextGen (fixed old API key). |
| OctoKlipper | *Software Update* from `FracktalWorks/OctoprintKlipperPlugin` releases (branch `production`). Publish: bump `plugin_version` in `setup.py`, commit, tag the same version, push the tag. Upstream fixes: `git fetch upstream` in the clone and merge into `production`. |
| TwinDragonPrintRestore | *Software Update* from `FracktalWorks/TwinDragonPrintRestore` releases. |
| Klipper | `klipper --yes --restart` (host only). MCU/toolboard firmware is a separate, deliberate job. |
| Base image tweaks | `base --yes` (idempotent). |

## 10. Escalate to the team lead when

- `preflight` says the OS is not Debian 13, or finds OctoPrint 1.7.x on a printer meant to stay on the old generation.
- `configs` reports two config sets, or `can` finds a board that never answers.
- Klipper reports MCU/CAN errors after the `klipper` step (`pi_system_diagnostics.py --check can` and `--check power`; undervoltage mimics many bugs).
- Any step fails twice, or you are unsure which `--model` a machine is.
