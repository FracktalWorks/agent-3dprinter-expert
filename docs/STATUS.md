# New-generation printer software: status and handoff (2026-10-22)

**Bottom line:** everything that can be built and tested without a printer is done and pushed. Nothing has run on a real printer yet. The next session starts at **"Next steps"** below, on the reference unit (192.168.0.184, CM4 + Manta M8P, Debian 13), driven by `docs/DEPLOYMENT.md` / the `deploy-printer` skill.

## Where everything is

| Component | Repo / branch | State |
|---|---|---|
| Deploy tool, docs, base image, provisioning | `FracktalWorks/agent-3dprinter-expert` · `main` | `deploy/deploy_printer.py`, `docs/DEPLOYMENT.md`, `base-image/` (overlay, `apply.sh`, `touchui/`, `splash/`, `provision.py`, `build-image.sh`), skill `.claude/skills/deploy-printer/` |
| OctoPrint (new generation) | `FracktalWorks/Fracktal_OctoPrint_NextGen` · `production` (default branch; renamed from `OctoPrintUpdates-`) | OctoPrint 1.11.8 + Fracktal patches. Installer `fracktal/install-octoprint.sh`, config template `fracktal/config/config.yaml`, release workflow `.github/workflows/fracktal-release.yml`. **No release published yet.** |
| OctoPrint (old generation) | `FracktalWorks/Fracktal_OctoPrint` · `master` | 1.7.x, maintenance only; README banner says so. Untouched otherwise. |
| ControlCenter | `FracktalWorks/ControlCenter` · **`feat/octoprint-1.11-compat`**, tag **`1.1.8rc1`** | Not merged to `production`, no GitHub release. The installer pins the `1.1.8rc1` tag. Latest release 1.1.7 is **not** NextGen-compatible. |
| Print restore plugin | `FracktalWorks/TwinDragonPrintRestore` · `main`, tag **`1.0.6rc1`** | Build fixes for Python 3.12+; the installer pins the `1.0.6rc1` tag. Latest release 1.0.5 does **not** install on Python 3.13. |
| Klipper | `FracktalWorks/klipper_IDEX` · `Production` | Fast-forwarded to include `fracktal_config/` templates + Z resonance backport. Not upgraded to newer upstream (toolboards). |

## What changed, per component

**OctoPrint NextGen** (1.11.8 base): heated filament (`F:`, `M142/M192`, `/api/printer/filament`), secondary heaters `H0..Hn` (`M104 H<n>`, `/api/printer/heater/<n>`), chamber/filament in temperature profiles, PNG sibling delete, branding, update source = this repo (Stable=`production`, Beta=`beta`). Old 1.7 `firstRun` bypass deliberately **not** ported. Default config: LAN auto-login as `admin`, CORS open, `/tmp/printer`, checksums off, wizard skipped; unique API key + secretKey per printer generated at install.
Installer: dry run by default; backs up `~/.octoprint` and the old `octoprint.service`; keeps the old venv (`venv.old-*`); installs ControlCenter `1.1.8rc1` + TwinDragonPrintRestore `1.0.6rc1` (tags) by default; never overwrites an existing `config.yaml`; `--rollback` restores venv, service file and config.

**ControlCenter** (`feat/octoprint-1.11-compat`): API key read from OctoPrint's `config.yaml` (`$OCTOPRINT_API_KEY` → `~/.octoprint` → `/home/pi/.octoprint` → legacy key); `/api/tool`,`/api/bed` → `/api/printer/tool|bed`; config template schema-valid for 1.11; per-printer secrets preserved when applying templates; failsafe restore keeps the key in use and gives the files back to `pi`; skips rewriting `/etc/X11/xinit/xinitrc` when `/etc/fw/touchui-managed` exists; `setup.py` builds without OctoPrint importable (pip isolation).

**TwinDragonPrintRestore** (`main`): versioneer fixed for Python 3.12+; `setup.py` builds under pip isolation.

**Linux / base image**: hardening overlay + `fw-health` + `fw-updates` (existing); new `fw-commission` (first-boot model + key), `fw-lock-rootfs` (read-only root after commissioning, opt-in `apply.sh --lock-rootfs`), `touchui/` (`fw-touchui.service`: startx on tty1 as `pi` → `~/.xinitrc` → ControlCenter with the venv's Python), `splash/` (Plymouth theme, quiet cmdline, `disable_splash`), `provision.py` + `commissioning/models.json` (SD-card personalisation), `build-image.sh` (ro root + FWDATA layout).

## Verified vs not

| Verified on the PC | Not yet verified (needs the printer) |
|---|---|
| OctoPrint NextGen: full test suite (1047) on Python 3.13; heater/filament/profile API live against the virtual printer (11/11) | Anything on real hardware |
| ControlCenter's REST + websocket client against live 1.11.8, incl. print-restore endpoints (16/17, the miss is a test bug) | ControlCenter on the touchscreen; rootless X as `pi` |
| ControlCenter + TwinDragonPrintRestore load as plugins in 1.11.8 | Plymouth splash on the real display |
| Plugin wheels identical with/without OctoPrint at build time | `fw-commission`, `fw-lock-rootfs` on a booted card |
| Installer install/upgrade/rollback in WSL with stubbed sudo/systemctl | `build-image.sh` end to end |
| Klipper host: pinned deps install, chelper compiles, 162 modules import on 3.13 | Klipper regression suite (needs MCU dictionaries); a real print on 3.13 |
| `provision.py`, `fw-commission`/`fw-lock-rootfs` logic, deploy tool: 22 unit tests | First-boot ordering cloud-init → fw-commission → fw-touchui |

## Known risks to handle on the printer

1. **Reference unit's `~/klipper_IDEX` has 3 uncommitted edits** (`resonance_tester.py`, `shaper_calibrate.py`, untracked `scripts/elf2uf2.py`). The `klipper` step stops on them (by design). `Production` already contains the resonance backport "as running on the reference unit": diff the local edits against it (`git diff`, `git stash`), keep `elf2uf2.py` (commit it or copy it off), then re-run.
2. **Its OctoPrint lives in `~/oprint`** (not `~/OctoPrint/venv`). The installer leaves `~/oprint` in place, points the service at the new venv, and saves the old service file, so `--rollback` returns to `~/oprint`.
3. **Plugins in the old venv are not migrated.** The installer prints them; reinstall the ones still needed with `deploy_printer.py octoprint --op-plugins "..."`. TwinDragonPrintRestore is installed automatically.
4. **Install from tags, never branch zips.** A branch archive has no usable version (the `feat/octoprint-1.11-compat` name was even parsed as a version and broke the build), and an unversioned plugin is offered the old releases (ControlCenter 1.1.7, which breaks the API key) as "updates". The installer pins tags `1.1.8rc1` / `1.0.6rc1`, which are newer than the releases, so no downgrade is offered. For any new test build: tag it (`1.1.8rc2`), don't point at a branch.
5. Rootless X may be refused on this hardware: fallback in `docs/DEPLOYMENT.md` section 3.
6. Undervoltage mimics software faults: `pi_system_diagnostics.py --check power` before blaming code.

## Next steps (in order)

1. `deploy_printer.py workspace --yes`, `preflight`, `inspect-ui`; read the report (how the unit boots to its UI today).
2. `pi_system_diagnostics.py --host 192.168.0.184 --check octoprint`: which OctoPrint/plugins are on it now.
3. Steps `base`, `klipper` (risk 1), `octoprint` (risks 2-3), `touchui`, `splash`; reboot; `verify`; confirm on the screen: logo → ControlCenter loading screen → home screen.
4. Print a test file; check temperatures, pause/resume, power-loss restore screen.
5. If anything differs from the docs, fix the scripts in the repo (not by hand on the printer) and re-run.
6. ControlCenter: merge `feat/octoprint-1.11-compat` → `production`, publish GitHub release **1.1.8**; TwinDragonPrintRestore: publish release **1.0.6** from `main`. Then point the installer defaults (`CC_SOURCE`, `DEFAULT_PLUGINS` in `fracktal/install-octoprint.sh`) at those releases (or `CC_SOURCE=latest`), and `REPOS["ControlCenter"]` in `deploy_printer.py` at `production`.
7. OctoPrint NextGen: tag `1.11.8.post1` on `production` and push the tag (workflow publishes the release); check the printer sees it under Software Update.
8. Image: on the finished reference unit `seal-image.sh`, read the card, `build-image.sh` on Linux, boot on a spare card, walk `base-image/README.md` §9.5, try `provision.py` + first boot.
