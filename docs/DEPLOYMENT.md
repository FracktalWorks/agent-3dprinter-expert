# Deploying the Fracktal software stack on a printer

**Bottom line:** open this repo in Claude Code on your PC, tell it *"deploy the printer at 192.168.x.x as a TwinDragon 600 V2, serial FW-0421"*, and it follows `.claude/skills/deploy-printer/SKILL.md`: it runs the scripts in `deploy/` one step at a time, shows you a dry run of each, and applies only when you say go. This page explains what each step does so you can check it, and what to do by hand.

> **Verified status (read this first).** Tested on a PC only: NextGen OctoPrint (full test suite on Python 3.13), ControlCenter's client and the print-restore plugin against it, the installer (install/upgrade/rollback, stubbed system). **Nothing has run on a real printer yet.** Treat the first deployment as the test and do the *Check* line of each step. Current state, known risks and the ordered to-do list: [`docs/STATUS.md`](STATUS.md).

---

## 1. What you need

| Item | Notes |
|---|---|
| A PC (Windows/Linux/macOS) with Python 3.10+, git, Claude Code | Same network as the printer. |
| This repo, plus its siblings | The `workspace` step clones `Fracktal_OctoPrint_NextGen`, `klipper_IDEX`, `ControlCenter`, `OctoprintKlipperPlugin` next to it. |
| `pip install -r requirements.txt` | Installs paramiko (SSH), python-dotenv, pyyaml. |
| `.env` in the repo root (never committed) | `PRINTER_SSH_HOST=192.168.x.x`, `PRINTER_SSH_USER=pi`, and `PRINTER_SSH_PASSWORD=...` or `PRINTER_SSH_KEY=path`. Ask the team lead for the fleet password. |
| A printer with the Debian 13 base image | Raspberry Pi OS Lite arm64 (trixie), user `pi`, SSH on, internet access (GitHub, apt). See `base-image/README.md`. Older printers (Debian 10-12, OctoPrint 1.7.x) are a different generation: do not use these scripts on them without the team lead. |
| The printer on stable power and **not printing** | Undervoltage corrupts installs. |

Which OctoPrint goes where:

| Printer generation | OctoPrint | Repo it updates from |
|---|---|---|
| Old (Debian 10-12) | 1.7.x | `FracktalWorks/Fracktal_OctoPrint` |
| New (Debian 13) | 1.11.x | `FracktalWorks/Fracktal_OctoPrint_NextGen` (branch `production`) |

Never install one on the other's printers.

## 2. The steps

Always: run a step **without** `--yes` first (dry run), read it, then add `--yes`.

| # | Command (`python deploy/deploy_printer.py ...`) | What it does | Check |
|---|---|---|---|
| 1 | `workspace --yes` | Clones/updates the four repos next to this one on the right branches. | Output lists each repo with a commit id. |
| 2 | `preflight` | Read-only. OS, Python, free space, OctoPrint version, services. | No `!!` warnings, or you understand each. |
| 3 | `inspect-ui` | Read-only. Saves how the unit boots to its UI today (cmdline, config.txt, xinitrc, getty, Plymouth, fstab) to `deploy/reports/<host>-<time>/`. | Open `profile-startx.txt`, `getty-override.txt`, `xinitrc-global.txt`: they show what step 7 will replace. |
| 4 | `base --yes` | Uploads `base-image/` and runs `apply.sh`: sysctl/journald/watchdog hardening, `fw-health`, update switch (auto-updates stay OFF), SSH hardening, installs `fw-commission` and `fw-lock-rootfs` (not enabled). `--full-base` adds boot tuning, firewall, kernel hold: **new images only**. | `pi_system_diagnostics.py --check base-image` is green. |
| 5 | `klipper --yes [--restart]` | `klipper_IDEX` to `Production`, installs Klipper's Python packages into `~/klippy-env`. **MCU firmware is not touched.** Restart only when idle. Stops if `~/klipper_IDEX` has local edits: review them (`git diff`), stash or commit, re-run. | `~/klippy-env/bin/python --version` prints 3.13 on Debian 13; Klipper starts and connects to its MCUs. |
| 6 | `octoprint --yes` | Runs `fracktal/install-octoprint.sh`: backs up `~/.octoprint`, keeps the old venv as `venv.old-<time>` (rollback), installs NextGen OctoPrint, ControlCenter and TwinDragonPrintRestore into `~/OctoPrint/venv`, creates `config.yaml` only if absent (unique API key per printer), installs `octoprint.service` (old one saved for rollback), waits for `/api/version`. Plugins from the old install are listed, not migrated: re-add with `--op-plugins "..."`. | Script ends with "OctoPrint is up". Web UI on `http://<ip>/`. |
| 7 | `touchui --yes` | Installs `fw-touchui.service` + `~/.xinitrc`: X starts on tty1 and runs ControlCenter. See section 3. | After reboot the screen shows ControlCenter. |
| 8 | `splash --yes` | Quiet boot, no rainbow screen, Fracktal logo. See section 4. | After reboot: logo, no scrolling text. |
| 9 | `commission --model <id> --serial FW-xxxx --yes` | Activates the model's `PRINTER_*.cfg` (exactly one) and regenerates this printer's OctoPrint API key. Models: `python base-image/provision.py --list-models`. | `printer.cfg` has one active `[include PRINTER_*.cfg]`. |
| 10 | Reboot, then `verify` | Services active, Xorg and ControlCenter running, OctoPrint answers. | All four services `active`. |

**By hand (not automated, per board):** CAN UUIDs and MCU serials in `printer.cfg` (`~/klipper_IDEX/scripts/canbus_query.py can0`), calibration, touchscreen calibration, webcam.

**Rollback:** OctoPrint: `bash ~/fw-deploy/octoprint-fracktal/install-octoprint.sh --rollback --yes`. Boot files: every change leaves `*.pre-splash-<time>`, `*.pre-commission-<time>` backups next to the original. Touch UI: `sudo systemctl disable --now fw-touchui` and remove `/etc/fw/touchui-managed`.

## 3. Booting to ControlCenter (startx)

Chain at power-on: **Pi firmware** → **kernel** → **systemd** → `octoprint.service` and `klipper.service` → `fw-touchui.service` → `startx` on tty1 → `~/.xinitrc` → ControlCenter (`main.py`).

How it is wired and why:

- `fw-touchui.service` runs as user `pi` on `tty1` with a login session (`PAMName=login`), so Xorg gets the display and touchscreen without root. It runs `startx /home/pi/.xinitrc -- :0 vt1 -nocursor`. It restarts X if the UI exits (`Restart=always`).
- `~/.xinitrc` disables screen blanking, finds ControlCenter's folder with the **OctoPrint venv's** Python, `cd`s there (the app uses relative imports) and runs `main.py` with that Python. The venv is created with system packages visible, so apt's PyQt5/OpenCV are found.
- The service creates `/etc/fw/touchui-managed`. ControlCenter's OctoPrint plugin normally rewrites `/etc/X11/xinit/xinitrc` and runs `sudo startx` every time OctoPrint starts; that would clash with the service and fail on a read-only root, so the plugin skips it when that marker exists (ControlCenter 1.1.8+).
- Do **not** also start X from `~/.bash_profile`, an autologin getty, or a display manager. `touchui` lists any it finds (`inspect-ui` saved them too) and edits nothing; remove them by hand.

**If the screen stays black or shows a console:**
1. `journalctl -u fw-touchui -b --no-pager | tail -50` (X errors, Python tracebacks).
2. `systemctl status fw-touchui` (restart loop?). `ls /var/log/Xorg*` or `~/.local/share/xorg/Xorg.0.log`.
3. Is ControlCenter installed in the venv? `/home/pi/OctoPrint/venv/bin/pip list | grep -i controlcenter`.
4. Rootless X refused (`no screens found`, `Permission denied` on `/dev/dri` or `/dev/input`)? Confirm `pi` is in groups `video input tty render` (log out/in or reboot after `touchui`). Last resort: set `User=root` in `/etc/systemd/system/fw-touchui.service` and `sudo` before the Python in `~/.xinitrc` (that is how the old units ran it); then `daemon-reload` and restart. Tell the team lead, because files ControlCenter writes will then be root-owned.
5. Wrong or no display: `inspect-ui` saved `display.txt`. SPI TFT panels use a framebuffer copy service (like MANDEL's `fbcp`) that is **not** set up by these scripts.

## 4. Boot screen and splash

What you see, in order, and what controls each part:

| Stage | Controlled by | Set by `splash` |
|---|---|---|
| Pi rainbow screen | `disable_splash=1` in `config.txt` | yes (also `boot_delay=0`) |
| Kernel logo / log text | `cmdline.txt`: `quiet splash loglevel=3 logo.nologo vt.global_cursor_default=0 plymouth.ignore-serial-consoles consoleblank=0` | yes |
| Fracktal logo | Plymouth theme `fracktal` (black background, logo centred, at most 60% of screen width) in the initramfs | yes |
| Hand-off to X | `fw-touchui.service` starts after Plymouth quits | `touchui` |
| ControlCenter loading screen | ControlCenter itself (`ui/loading_screen`) | already part of the app |

The logo defaults to ControlCenter's `octoprint_ControlCenter/ui/resources/img/splash.png`; use another with `--logo path.png` (PNG, ideally black or transparent background). It installs Plymouth if needed and rebuilds the initramfs, so it needs a **writable root**: on a read-only production unit run `sudo fw-rw on` first. Revert: restore the `*.pre-splash-*` files and run `sudo plymouth-set-default-theme -R <old theme>`.

Caveats: the splash needs the display to be a normal Pi framebuffer/KMS output (HDMI/DSI). Panels driven by a separate framebuffer-copy service may not show it, and the old optimisation notes disable the GPU driver (`vc4-kms-v3d`) on some units. Confirm on the real screen; if it is blank, the logo is simply not shown and nothing else breaks.

## 5. Making an SD card image instead (many printers)

The same pieces are baked into a golden image so each new printer only needs personalising: build one unit with steps 4-8, `seal-image.sh`, read the card to `golden.img`, build the production layout with `base-image/build-image.sh` (Linux, root; not yet run end to end), flash, then on the PC: `python base-image/provision.py --boot <drive> --serial FW-0421 --model twindragon-600-v2 [--wifi-ssid ... --wifi-pass ...]`. First boot applies identity and model automatically. Details and the unproven items: `base-image/README.md` sections 9-10. Run `apply.sh --lock-rootfs` only on the image build, never on a live printer.

## 6. Updating a printer later

> NextGen printers need **ControlCenter >= 1.1.8** and **TwinDragonPrintRestore >= 1.0.6** (installed by default). Both
> releases also work on old printers. Never install ControlCenter 1.1.7 or older on a NextGen printer (old fixed API key).


| What | How |
|---|---|
| OctoPrint (NextGen printers) | Automatic: OctoPrint's *Software Update* offers new GitHub releases of `Fracktal_OctoPrint_NextGen` (Stable = branch `production`, Beta = `beta`). Publishing: merge to `production`, tag `1.11.8.postN`, push the tag; the release workflow builds and publishes it. |
| ControlCenter | OctoPrint *Software Update* from GitHub releases of `FracktalWorks/ControlCenter`. |
| Klipper | Re-run `klipper --yes` (host only). MCU/toolboard firmware is a separate, deliberate job. |
| Base image tweaks | Re-run `base --yes` (idempotent). |

## 7. Escalate to the team lead when

- `preflight` says the OS is not Debian 13, or finds OctoPrint 1.7.x on a printer that is meant to stay on the old generation.
- Klipper reports MCU/CAN errors after step 5 (`pi_system_diagnostics.py --check can` and `--check power`; undervoltage mimics many bugs).
- Any step fails twice, or you are unsure which `--model` a machine is.
