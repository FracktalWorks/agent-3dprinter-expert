---
name: deploy-printer
description: >
  Deploy or update the full Fracktal software stack (hardening, Klipper_IDEX, NextGen OctoPrint,
  ControlCenter touchscreen UI via startx, boot splash, model commissioning) on a printer over SSH.
  Use when asked to set up, commission, provision, reinstall or upgrade a printer's software.
---

# Deploy a printer (Claude Code runbook)

Read `docs/STATUS.md` (current state, known risks, next steps) and `docs/DEPLOYMENT.md` (the guide) first. This file is the operating procedure for you.

## Rules
1. **Every step is a dry run until `--yes`.** Run the dry run, show the user its output, get a "go", then re-run with `--yes`. Never batch several steps under one approval.
2. Run steps in the documented order, **one at a time**, and check the result before the next. Stop on the first surprise and report it (BLUF: outcome first).
3. Never run `base --full-base`, `splash`, `touchui`, `commission` or `klipper --restart` on a printer that is mid-print or that the user did not name. Ask which printer (host/IP) and its model first.
4. `commission` changes which `PRINTER_*.cfg` is active: only on a new/blank unit or when the user explicitly asks. CAN UUIDs/MCU serials are per board and are edited by hand, never guessed.
5. Do not read or print `.env`, passwords, API keys or `users.yaml`. The scripts read them themselves.
6. Several parts are written but **not yet proven on hardware** (listed in docs/DEPLOYMENT.md "Verified status"). Say so when you reach them and confirm the result with `verify`.

## Procedure
```
pip install -r requirements.txt            # once (paramiko, python-dotenv, pyyaml)
python deploy/deploy_printer.py workspace --yes      # clone/update the repos next to this one
python deploy/deploy_printer.py preflight
python deploy/deploy_printer.py inspect-ui           # READ deploy/reports/<host>-*/ before touchui/splash
python deploy/deploy_printer.py base       [--yes]
python deploy/deploy_printer.py klipper    [--yes] [--restart]
python deploy/deploy_printer.py octoprint  [--yes]
python deploy/deploy_printer.py touchui    [--yes]
python deploy/deploy_printer.py splash     [--yes]
python deploy/deploy_printer.py commission --model <id> --serial <FW-xxxx> [--yes]
python deploy/deploy_printer.py verify
```
Models: `python base-image/provision.py --list-models`. Connection settings come from `.env` (`PRINTER_SSH_HOST`, `PRINTER_SSH_USER`, `PRINTER_SSH_PASSWORD` or `PRINTER_SSH_KEY`).

After `touchui` and `splash`, the printer must be rebooted once (ask first), then `verify`, then physically confirm with the user: logo during boot, then the ControlCenter loading screen, then the home screen.
