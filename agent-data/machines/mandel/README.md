# MANDEL — live machine files, snapshotted

These are **copies of what is running on the printer**, not the source of truth.
The machine at `192.168.0.34` is authoritative; these exist so that:

- the work survives the Pi's SD card,
- a future session can read and reason about 59 KB of macro logic and a 32 KB
  touchscreen panel **without needing the printer powered on**,
- and a change can be diffed against what is actually deployed before touching
  anything.

| File | Lives on the machine at | Notes |
|---|---|---|
| `config/printer.cfg` | `~/printer_data/config/printer.cfg` | **CRLF line endings — preserve them** |
| `config/clay_macros.cfg` | `~/printer_data/config/clay_macros.cfg` | the entire clay layer; `[idle_timeout]`, `[save_variables]`, the `RESUME` override |
| `panels/clay.py` | `~/KlipperScreen/panels/clay.py` | **this file exists in no other git repo** — KlipperScreen is a plain clone and the panel is untracked there |
| `gcode/gen_cylinder.py` | *(nowhere — runs on the workstation)* | generates the test cylinder; the only g-code author that knows the volumetric convention |
| `COMMISSIONING.md` | *(procedure)* | step-by-step field plan: measure the build volume, correct the axis limits, set up the slicer, acceptance print |
| `klipperscreen/` | `~/KlipperScreen` + `KlipperScreen.conf` | the four locally-patched upstream files, as a diff — **a KlipperScreen update destroys them**. See its README |
| `slicer/` | *(the workstation)* | PrusaSlicer config bundle for the 3/4/5/6 mm nozzles, and why PrusaSlicer rather than Cura. See its README |

Not snapshotted, deliberately: `clay_vars.cfg` (runtime state, changes every time
the operator turns a knob) and the generated `.gcode` (regenerate it instead).

## Before you edit anything

Run the sync check. If it reports drift, **the machine is right and this
directory is stale** — pull first, or you will silently revert someone's work.

```bash
python agent-data/machines/mandel/sync.py --check     # diff repo vs machine
python agent-data/machines/mandel/sync.py --pull      # machine  -> repo
python agent-data/machines/mandel/sync.py --push      # repo -> machine  (asks)
```

Credentials come from the environment or `.env` (`PRINTER_SSH_HOST`,
`PRINTER_SSH_USER`, `PRINTER_SSH_PASS`) — never hard-code them here, and never
commit `.env`.

## Deploying a change by hand

1. `sync.py --check` — confirm no drift.
2. Edit the file **in this directory**, one change at a time.
3. `sync.py --push`.
4. `FIRMWARE_RESTART` for `.cfg`; `sudo systemctl restart KlipperScreen` for
   `clay.py` (compile-check it first: `python3 -m py_compile`).
5. Verify over the Moonraker API before telling anyone it works.

Step 5 is not optional on this machine. Several changes here have looked correct
and been wrong — see the failure log in `../mandel_clay_printer.md`.
