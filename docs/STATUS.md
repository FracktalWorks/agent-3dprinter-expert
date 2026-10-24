# New-generation printer software: status and handoff (updated 2026-10-24)

**Bottom line:** the stack now runs on a real printer. The reference unit (192.168.0.184, TwinDragon 600 V2) runs NextGen OctoPrint with every Fracktal component from FracktalWorks repos, and the deploy tool carries all of that deployment's lessons (`docs/DEPLOYMENT.md` section 8). What is left on that unit: `splash` and a test print (the touchscreen boot was switched over and proven on 2026-10-24). The next printer: follow `docs/DEPLOYMENT.md` / the `deploy-printer` skill from step 1.

## Where everything is

| Component | Repo / branch | State |
|---|---|---|
| Deploy tool, docs, base image, provisioning | `FracktalWorks/agent-3dprinter-expert` · `main` | `deploy/deploy_printer.py` (+ `deploy/remote/*` run on the printer), `docs/DEPLOYMENT.md`, `base-image/` (overlay, `apply.sh`, `touchui/`, `splash/`, `provision.py`, `build-image.sh`), skill `.claude/skills/deploy-printer/` |
| OctoPrint (new generation) | `FracktalWorks/Fracktal_OctoPrint_NextGen` · `production`, **release 1.11.8.post4** | 1.11.8 + Fracktal patches (heaters, filament, branding, profile migration fix). Installer `fracktal/install-octoprint.sh` (installs ControlCenter + TwinDragonPrintRestore + OctoKlipper; restores the old OctoPrint on any failure; `--default-plugins` for uploaded archives), config template `fracktal/config/config.yaml`, release workflow on tag push. |
| OctoPrint (old generation) | `FracktalWorks/Fracktal_OctoPrint` · `master` | 1.7.x, maintenance only. Its branding commit `42e774f89` is the origin of NextGen's images. |
| ControlCenter | `FracktalWorks/ControlCenter` · `production`, **release 1.1.8** | Works on both generations. 1.1.7 and older do **not** work on NextGen printers. |
| Print restore plugin | `FracktalWorks/TwinDragonPrintRestore` · `main`, **release 1.0.6** | Python 3.12+ / pip-isolation build fixes. |
| OctoKlipper plugin | `FracktalWorks/OctoprintKlipperPlugin` · `production` (fork of thelastWallE, `upstream` remote in the clone), **release 0.4.2** | Software Update from FracktalWorks; defaults = Fracktal layout (`~/printer_data/config`, `~/klipper_IDEX/`, logs folder `~/printer_data/logs`); Klipper Update removed; "Klipper Configuration" settings tab; `setup.py` builds under pip isolation. |
| Klipper | `FracktalWorks/klipper_IDEX` · `Production` | `fracktal_config/` templates + Z resonance backport. No release tags (OctoKlipper shows `Production@<sha>`). |

## Reference unit 192.168.0.184 (as of 2026-10-24 15:30)

| | State |
|---|---|
| OS / power | Debian 13, kernel 6.18, CM4 1 GB, **Wi-Fi only** (`eth0` down), no undervoltage. `base` applied (hardware watchdog 15 s). |
| Klipper | `klipper_IDEX` `Production` @ `bd6a517e`, clean (old CRLF-only edits in `git stash`). `ready`; config `~/printer_data/config/printer.cfg` (TwinDragon 600 V2). |
| CAN | `[mcu]` `8e73c0160b99` (Manta, stm32h723), `toolhead0` `7cb976b83a03`, `toolhead1` `3ec1b8773dd7` (RP2040, 1 Mbit/s; left/right checked by endstop and swapped). |
| Configs | 25 files in `~/printer_data/config`, symlinks in `/home/pi` for ControlCenter. Old unused set: `~/printer_data/config.old-20261024-140739`. |
| OctoPrint | 1.11.8.post3 in `~/OctoPrint/venv`, ControlCenter 1.1.8, TwinDragonPrintRestore 1.0.6, OctoKlipper 0.4.2; printer profile Twin Dragon 600 V2 (2 extruders, 660×620×414); config aligned with the template. Old 1.11.7 still in `~/oprint` (rollback). |
| Touchscreen | `fw-touchui.service` (2026-10-24 16:20, `touchui --retire-legacy`): rootless X as `pi` on tty1 → ControlCenter 1.1.8 from `~/OctoPrint/venv`. Legacy autologin overrides, `startx` in `~/.bashrc` and the old `~/.xinitrc` kept as `*.pre-touchui-20261024-162029`. `verify`: 0 problems after reboot. |
| Webcam | Set up by hand by another session (ustreamer `webcamd.service` :8080, nftables rule): not in the repos, unverified (no camera attached). |
| Leftovers (safe to delete) | `~/OctoPrint/venv.old-*`, `venv.failed-*`, `~/fw-deploy/pkgs/`, `~/octoprint-backup-*.tar.gz` (keep the newest), `config.yaml.pre-*`. |

## Verified vs not

| Verified | Not yet verified |
|---|---|
| Reference unit: `base`, `klipper`, NextGen OctoPrint + all plugins, config layout, CAN UUIDs, OctoKlipper settings tab + editor, branding, both toolhead temperatures, heating to 200 °C, `touchui --retire-legacy` (rootless X as `pi`, survives a reboot) | `splash`, `commission`, `fw-lock-rootfs`, image build, first-boot ordering |
| OctoPrint NextGen test suite in CI on every release tag (incl. profile-migration test) | A real print on Python 3.13; power-loss restore on NextGen |
| Deploy tool: 30 unit tests (no printer needed); `deploy/remote/*.sh` syntax | The new `deploy_printer.py octoprint` path (upload + unit) end to end on a fresh printer |

## Known risks

1. **ControlCenter "Restore print settings to default"** (touchscreen) replaces OctoPrint's `config.yaml` with ControlCenter's template (auto-login from any address, tracking on, old commands). Run `verify` after anyone uses it. Real fix: ControlCenter's template (`octoprint_ControlCenter/config/`), which `CLAUDE.md` marks reference-only: team lead decision.
2. **Old installs' Software Update** offers upstream OctoPrint and ControlCenter 1.1.7: decline both.
3. **`M500` → `SAVE_CONFIG` after every Klipper start** leaves a `printer-<date>.cfg` backup each time (the old folder had ~1,480). Caller is ControlCenter or a macro: not traced yet.
4. Rootless X may be refused on some hardware: fallback in `docs/DEPLOYMENT.md` section 3.
5. Undervoltage mimics software faults: `pi_system_diagnostics.py --check power` before blaming code.

## Next steps (in order)

1. Reference unit: ~~`touchui`~~ done; `splash`; reboot; `verify` (expect 0 problems); confirm on the screen: logo → ControlCenter loading screen → home screen (ControlCenter 1.1.8).
2. Reference unit: test print; temperatures, pause/resume, power-loss restore screen. Then `octoprint --yes` once more to prove the new upload/unit path (installs 1.11.8.post4).
3. Trace the `M500` caller (risk 3) and decide on ControlCenter's config template (risk 1).
4. Next printer: full procedure from `workspace`; fix whatever differs in the repo first, then re-run.
5. Image: on the finished reference unit `seal-image.sh`, read the card, `build-image.sh` on Linux, boot a spare card, `base-image/README.md` §9.5, `provision.py` + first boot.
