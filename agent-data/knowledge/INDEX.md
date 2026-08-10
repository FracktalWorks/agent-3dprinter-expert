# Knowledge Base — 3D Printing Technologies

Auto-updated by the knowledge-sync skill.
Sources: GitHub, manufacturer docs, community wikis, datasheets.

## Index

| Technology          | File                    | Last Updated |
| ------------------- | ----------------------- | ------------ |
| FDM Printers        | `fdm.json`              | —            |
| SLA/DLP Printers    | `sla.json`              | —            |
| SLS Printers        | `sls.json`              | —            |
| Firmware (Marlin)   | `firmware_marlin.json`  | —            |
| Firmware (Klipper)  | `firmware_klipper.json` | —            |
| Firmware (RRF)      | `firmware_rrf.json`     | —            |
| Stepper Drivers     | `stepper_drivers.json`  | —            |
| Hotends & Extruders | `hotends.json`          | —            |
| Print Surfaces      | `surfaces.json`         | —            |
| Sensors & Probes    | `sensors.json`          | —            |
| Motion Systems      | `motion.json`           | —            |
| Materials           | `materials.json`        | —            |
| Controllers         | `controllers.json`      | —            |

## How to update

```bash
python .github/skills/knowledge-sync/scripts/knowledge_sync.py --all
python .github/skills/knowledge-sync/scripts/knowledge_sync.py --tech klipper
```
