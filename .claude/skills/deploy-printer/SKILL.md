---
name: deploy-printer
description: >
  Deploy or update the full Fracktal software stack (hardening, config folder layout, CAN UUIDs,
  Klipper_IDEX, NextGen OctoPrint + ControlCenter + plugins, touchscreen UI via startx, boot splash,
  model commissioning) on a printer over SSH, and publish fixes to the FracktalWorks repos. Use when
  asked to set up, commission, provision, reinstall, upgrade or review a printer's software.
---

# Deploy a printer (Claude Code runbook)

Read `docs/STATUS.md` (current state, next steps) and `docs/DEPLOYMENT.md` (the guide; section 8 lists
everything that went wrong on the first real deployment) first. This file is the operating procedure.

## Rules
1. **Every step is a dry run until `--yes`.** Run the dry run, show the user its output, get a "go", then re-run with `--yes`. Never batch several steps under one approval.
2. Run steps in order, **one at a time**, and check the result before the next (`verify` is cheap: run it after every mutating step). Stop on the first surprise and report it (outcome first).
3. Never run `base --full-base`, `configs`, `can --set`/`--stop-klipper`, `splash`, `touchui`, `commission` or `klipper --restart` on a printer that is mid-print or that the user did not name. Ask which printer (host/IP) and its model first. Klipper restarts switch the heaters off: say so.
4. `commission` changes which `PRINTER_*.cfg` is active: only on a new/blank unit or when the user explicitly asks. CAN UUIDs come from `can` (chip type tells the Manta from the toolheads); left/right only from the `--endstops` test. Never guess.
5. Do not read or print `.env`, passwords, API keys or `users.yaml`. The scripts read them. Talk to Klipper through its socket (`deploy/remote/klipper_api.py`), not OctoPrint's API (that needs the key).
6. Fix problems **in the repos** (deploy tool, installer, plugin forks), test, release, then apply: not by hand on the printer. Record what was learned in `docs/DEPLOYMENT.md` section 8 and `docs/STATUS.md`.

## Procedure
```
pip install -r requirements.txt                     # once (paramiko, python-dotenv, pyyaml)
python deploy/deploy_printer.py workspace --yes      # clone/update the 4 repos next to this one
python deploy/deploy_printer.py preflight            # Wi-Fi only? local Klipper edits? which config path?
python deploy/deploy_printer.py inspect-ui           # READ deploy/reports/<host>-*/ before touchui/splash
python deploy/deploy_printer.py base       [--yes]
python deploy/deploy_printer.py configs    [--yes]   # ~/printer_data/config + /home/pi symlinks
python deploy/deploy_printer.py can        [--stop-klipper --yes]   then  --set MCU T0 T1 [--yes], --endstops
python deploy/deploy_printer.py klipper    [--yes] [--restart]
python deploy/deploy_printer.py octoprint  [--yes]   # latest release; uploads packages; runs as a unit
python deploy/deploy_printer.py touchui    [--yes] [--retire-legacy]
python deploy/deploy_printer.py splash     [--yes]
python deploy/deploy_printer.py commission --model <id> --serial <FW-xxxx> [--yes]
python deploy/deploy_printer.py verify               # "!!" lines are problems; expect "0 problem(s)"
```
Models: `python base-image/provision.py --list-models`. After `touchui` and `splash`, reboot once (ask first), `verify`, then confirm on the screen with the user: logo during boot, ControlCenter loading screen, home screen.

## Publishing (GitHub)
- Releases are cut by pushing a tag; CI tests and publishes. NextGen OctoPrint: tag `1.11.8.postN` on `production`. OctoKlipper fork: bump `plugin_version` in `setup.py`, tag the same version. Plugins are always installed from **tags**, never branch archives.
- `git push` works with the VS Code/Git Credential Manager login. For API calls (fork, release, settings) use the GitHub CLI with that login, never printing it:
  `export GH_TOKEN="$(printf 'protocol=https\nhost=github.com\n\n' | git credential fill | sed -n 's/^password=//p')"` then `"/c/Program Files/GitHub CLI/gh.exe" api ...`. (`gh auth login --with-token` refuses this token: no `read:org`.)
- Commit only the files you changed (other sessions may have work in progress in the same checkout: check `git status` first).

## Harness pitfalls (Windows PC)
- **PowerShell 5.1** mangles quotes in arguments to native programs: run SSH helpers from the **Bash** tool.
- **Git Bash rewrites `/home/pi/...` arguments** into Windows paths: prefix `MSYS_NO_PATHCONV=1` when passing printer paths to a local Python script.
- **`pkill -f "python3 main.py"` matches its own command line** and kills the shell running it: use `pkill -f "[p]ython3 main[.]py"`.
- `Printer.quiet()` reads for at most 60 s: anything longer goes through `run_unit()` (or `run()`), not `quiet()`.
- The printer is often on Wi-Fi: connections drop. `run_unit()`/`upload()` reconnect; ad-hoc commands need a retry loop.
- `git archive` on Windows converts text files to CRLF (`core.autocrlf`): use `git -c core.autocrlf=false archive` when hashing or shipping.
- OctoPrint writes `config.yaml` while running: stop it before editing the file, start it after.
