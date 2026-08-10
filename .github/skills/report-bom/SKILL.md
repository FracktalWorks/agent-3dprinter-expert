---
name: report-bom
description: >
  Generate professional PDF reports, Bill of Materials (BOMs), and clean
  Excel spreadsheets. Use templates from agent-data/templates/ for consistent
  formatting. Supports printer diagnostics reports, calibration reports,
  firmware configuration summaries, and parts BOMs.
when_to_use: "User asks to generate/create a report/BOM/PDF/Excel/sheet"
authority: write
cost_tier: 1
version: 0.1.0
---

# Report & BOM Skill

Generate professional PDF reports, BOMs, and structured Excel sheets for printer diagnostics, calibrations, firmware configs, and parts inventories.

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/report_bom_generator.py` | Generate PDF reports and Excel BOMs from data |

## Usage

```bash
# Generate a diagnostic report from fix record
python .github/skills/report-bom/scripts/report_bom_generator.py --type report --input outputs/_memory/fixes/20260702_CR10.json --output outputs/reports/

# Generate a BOM from parts list
python .github/skills/report-bom/scripts/report_bom_generator.py --type bom --input inputs/parts.csv --output outputs/boms/
```

## Outputs

- PDF reports in `outputs/reports/`
- Excel BOMs in `outputs/boms/`
- CSV data files in `outputs/`
