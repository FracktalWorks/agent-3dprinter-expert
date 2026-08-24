# MANDEL's KlipperScreen — what is local, and what would destroy it

`~/KlipperScreen` on the Pi is an ordinary upstream clone at
**`v0.4.7-149-ged40799`** with **four tracked files patched in place** and two
untracked files added. None of it is committed anywhere upstream, so

> **any KlipperScreen update — `git pull`, or the Moonraker update manager —
> will overwrite or refuse the local changes.** Re-apply
> `local-modifications.patch` afterwards and put `clay.py` and `colorized.css`
> back.

## Contents

| File | What it is |
|---|---|
| `local-modifications.patch` | `git diff` of the four patched tracked files. Apply with `git apply` from `~/KlipperScreen` |
| `upstream-commit.txt` | the exact commit the patch applies to |
| `KlipperScreen.conf` | `~/printer_data/config/KlipperScreen.conf` |
| `colorized.css` | untracked style added to `styles/` |
| *(the panel itself)* | `../panels/clay.py` — kept beside the other machine files, since it is edited far more often than any of this |

A full 7.3 MB tarball of the tree (minus editor droppings and `.git`) is at
`~/backups/KlipperScreen-full-<date>.tar.gz` on the Pi, and a copy is at
`~/mandel-backups/` on the workstation. It is deliberately **not** committed —
too large and almost entirely upstream code. The patch plus `clay.py` is what
actually needs preserving.

## What the four patches do

All of them serve the **CO₂ readout**, plus one line for the clay panel:

- `ks_includes/config.py` — registers `clay_speeds` as a valid config section
  (without it KlipperScreen rejects the clay panel's settings)
- `panels/base_panel.py` — puts the `co2_chamber` sensor in the title bar and
  suffixes it `PPM` instead of `°`
- `panels/main_menu.py`, `panels/temperature.py` — relabel "Temperature (°C)"
  as "CO₂ (ppm)" throughout

> **Note the awkward fact:** three of these four patches decorate a subsystem
> that does not work. The CO₂ plumbing is entirely dead — macros never included,
> bridge not running, and the ppm value is a **floating ADC pin**. The title bar
> is displaying noise in units of PPM. See §10 of
> [`../../mandel_clay_printer.md`](../../mandel_clay_printer.md). Preserved
> as-is because removing them is a separate decision, not a backup's job.

## Housekeeping found while backing this up

`~/KlipperScreen/panels/` contains `base_panel.py.save`, `.save.1` … `.save.10`,
`.swp`, `.bak`, `.ksbak` — editor droppings from live edits on the machine.
Harmless, excluded from the tarball, but a reminder that **`base_panel.py` has
been hand-edited on the printer many times.** Check `git diff` there before
assuming it matches upstream.
