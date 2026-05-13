# Uvira Luminex QC Tool — Specification
# Version 0.9.0-uvira (in progress, 2026-05-13)

> **Migration in progress.** Sections below still describe the legacy
> MPXV 12-plex MagPix behaviour. They will be rewritten as Sections 3–7
> of [UVIRA_TODO.md](UVIRA_TODO.md) land. Foundational changes (panel
> definition, Intelliflex parser, two-file plate-layout reader) have
> been made; the report rendering pipeline is the next milestone.

## Overview

Standalone quality control tool for 12-plex MPXV (monkeypox virus) Luminex immunoassays from Tetracore run on a MagPix instrument. Processes xPONENT CSV exports, performs automated QC checks, fits standard curves, computes 1/RAU (inverse Relative Antibody Units), and generates interactive HTML reports. Distributed as a macOS `.app` (or Windows `.exe`) requiring no installation.

## Assay Panel

### Antigens (8 beads)

| Bead Region | Analyte    | Description                     |
|-------------|------------|---------------------------------|
| 01          | MVA Ag     | Modified Vaccinia Ankara antigen |
| 02          | VACV A33R  | Vaccinia virus A33R protein      |
| 03          | MPXV A35R  | Monkeypox virus A35R protein     |
| 04          | MPXV B6R   | Monkeypox virus B6R protein      |
| 05          | MPXV A27   | Monkeypox virus A27 protein      |
| 06          | MPXV E8L   | Monkeypox virus E8L protein      |
| 07          | MPXV H3L   | Monkeypox virus H3L protein      |
| 08          | MPXV M1R   | Monkeypox virus M1R protein      |

### Kit Control Beads (4 beads)

| Bead Region | Name | Purpose                                                    |
|-------------|------|------------------------------------------------------------|
| 09          | NC   | Negative control bead — monitors non-specific binding       |
| 10          | ScG  | Sample control (goat) — confirms sample was added to well   |
| 11          | FC   | Fluorescent conjugate control — confirms PE reporter added  |
| 12          | IC   | Instrument control — monitors instrument performance        |

## Plate Layout

Standard 96-well plate:

- **Columns 1-2**: PC (positive control) standard curve in duplicate (serial dilution, e.g. 3-fold: 1:100, 1:300, ..., 1:72900). Dilutions are parsed from sample names, not hardcoded.
- **Row H, columns 1-2**: NC (negative control) wells
- **Remaining wells**: Specimen wells (single dilution, no replicates)

Variations handled:
- Single PC replicate (no duplicate in column 2)
- Missing NC wells
- Variable number of specimen wells (up to 80 per plate)
- **Two standard curve pools on one plate** (e.g., ITM PC and ITM PC2) — each pool is fit independently and produces separate AU columns in specimen output

## Input Files

### xPONENT CSV (required)

Multi-block CSV exported from the MagPix xPONENT software. Contains:
- Header metadata (batch ID, run date, operator, protocol, instrument serial number)
- `Median` data block: median fluorescent intensity (MFI) per well per analyte
- `Count` data block: bead count per well per analyte

Filename convention: `A{date}-{batch}-{plate}-{panel}_{timestamp}.csv`

### Plate Layout XLSX (optional)

Excel workbook with a "Sample list" sheet containing columns:
- `well_number`: sequential well number
- `well`: well position (e.g., A1, B2)
- `sample_id`: sample identifier
- `date` or `dt_visit`: visit date

When provided, enriches specimen results with sample IDs and visit dates.

## QC Checks

### 1. Bead Counts

- **Threshold**: minimum 30 beads per well-analyte pair
- **Output**: count of flagged pairs, flagged details table, plate heatmap of median bead counts per well
- **Interpretation**: low bead counts indicate aspiration issues or bead loss; affected results are unreliable

### 2. Standard Curve Fitting (4-Parameter Logistic)

Model: `y = d + (a - d) / (1 + (x / c)^b)`

| Parameter | Meaning                                |
|-----------|----------------------------------------|
| a         | Minimum asymptote (high dilution → low MFI) |
| b         | Hill slope                              |
| c         | Inflection point (IC50)                 |
| d         | Maximum asymptote (low dilution → high MFI) |

- Fit independently for each antigen, per standard curve pool
- Supports one or two standard curve pools per plate (e.g., ITM PC / ITM PC2); when both are present each is fit independently
- Uses mean of PC duplicates at each dilution point
- Fitted via `scipy.optimize.curve_fit` with bounds
- Reports fit success/failure, all 4 parameters, and quality issues per analyte

**Fit quality checks** (all must pass for `fit_ok = True`):

| Check          | Criterion                    | Rationale                                    |
|----------------|------------------------------|----------------------------------------------|
| R²             | ≥ 0.95                       | Goodness of fit                              |
| IC50 (c)       | Within [min_dil/3, max_dil×3] | Inflection point within the tested dilution range |
| Hill slope (b) | Between 0.3 and 5.0          | Prevents step-function or flat fits           |
| Dynamic range  | max/min asymptote ≥ 3-fold   | Ensures adequate signal separation            |

If any check fails, `fit_ok` is `False`, 1/RAU is not computed for that analyte, and the specific issues are reported in the QC table.

### 3. PC Replicate Variability

- **Metric**: Coefficient of Variation (CV) between duplicate PC wells at each dilution
- **Threshold**: CV ≤ 25%
- **Skipped**: when only a single PC replicate is present

### 4. Negative Control Monitoring

- Reports mean MFI per analyte across NC wells
- Tracked historically across plates for drift detection

### 5. Kit Control Bead QC

| Control | Check                          | Threshold              |
|---------|-------------------------------|------------------------|
| NC bead | Non-specific binding          | MFI ≤ 150              |
| ScG     | Sample addition verification   | MFI ≥ 10,000           |
| FC      | Conjugate addition verification | MFI 2,000–5,000       |
| IC      | Instrument consistency         | MFI 2,000–3,000        |

## Computed Outputs

### 1/RAU (Inverse Relative Antibody Units)

For each specimen well and antigen:
1. Invert the fitted 4PL standard curve: given MFI, solve for the equivalent dilution factor
2. Compute 1/RAU = 1 / dilution_factor

**Interpretation**: higher 1/RAU = more antibody. A specimen with 1/RAU = 0.02 produces the same signal as a 1:50 dilution of the positive control standard.

1/RAU is `NaN` when:
- The 4PL fit failed quality checks for that analyte
- The specimen MFI falls outside the standard curve range

## Reports

### Per-Plate HTML QC Report

Self-contained HTML file with embedded interactive Plotly charts. Sections:

1. **Plate Overview** — metadata table, well count summary (total, PC, NC, specimen)
2. **Bead Counts** — flagged pairs count, flagged details table, plate heatmap
3. **Standard Curves** — 4PL parameter table with fit quality issues, 2×4 grid of curve plots with historical overlays (grey) and specimen rug marks
4. **PC Replicate Variability** — 2×4 panel plot of PC MFI across plates (by dilution), with CV bar chart and details table in a fold (conditional: only when duplicates present)
5. **Negative Control Levels** — 2×4 panel plot of NC MFI across plates, with per-plate bar chart and details table in a fold
6. **Kit Control Beads** — flagged wells, 1×4 bar chart per control bead
7. **Specimen Results** — wide-format table with MFI and 1/RAU per antigen

Each report includes a "Back to Menu" button linking to the main upload interface.

### Per-Plate Specimen CSV

Long-format CSV with columns: `well, sample_name, analyte, mfi, count, well_type, dilution, 1/rau`

### Export All Data (Excel workbook)

Combined data across all processed plates. Sheets:

| Sheet                  | Contents                                          |
|------------------------|--------------------------------------------------|
| `specimens`            | All specimen results with `plate_id` column       |
| `standard_curve_params`| 4PL parameters (a, b, c, d) per plate per analyte |
| `standard_curve_data`  | Raw standard curve MFI data points                |
| `nc_levels`            | Negative control MFI per plate per analyte        |

## Historical Tracking

JSON files accumulate data across plates for trend monitoring:

- `std_curve_history.json` — standard curve data points (plate_id, run_date, analyte, dilution, mfi)
- `nc_history.json` — NC MFI per analyte per plate
- `fit_history.json` — 4PL fit coefficients per plate per analyte

History is deduplicated on plate_id — reprocessing a plate overwrites its previous history entry. Historical standard curves appear as grey lines behind the current plate's curves in the report.

When multiple standard curve pools are present, history files are scoped per pool (e.g., `std_curve_history_ITM_PC.json`, `std_curve_history_ITM_PC2.json`).

## Application Architecture

### Web Interface (Flask)

- Local-only web server (binds to `127.0.0.1` on a random free port)
- Browser auto-opens on launch
- Upload form: one or more xPONENT CSVs + optional layout XLSX
- Past reports table with view/download links and per-plate delete button
- "Export All Data" button for combined Excel workbook
- Delete plate: removes report, specimen CSV, history entries, and stored upload file
- **Drag-and-drop plate reordering**: drag rows in the past reports table, then click "Save Order"
- **Regenerate All**: re-runs the full pipeline for all plates in the saved order, rebuilding history trend plots in that order
- "Quit Application" button for graceful shutdown

### Data Storage

All persistent data stored in `~/mpox-luminex-qc-results/`:

```
~/mpox-luminex-qc-results/
  reports/            # Generated HTML QC reports
  specimens/          # Per-plate specimen CSV files
  history/            # JSON history files (accumulate across plates)
  uploads/            # Uploaded CSV/layout files (kept for regeneration)
  plate_registry.json # Plate order and upload file manifest
```

`plate_registry.json` records each plate's CSV filename and sort order. Uploaded files are retained so that "Regenerate All" can re-run the pipeline without requiring re-upload.

### Distribution

- **macOS**: `.app` bundle via PyInstaller (~128 MB)
- **Windows**: folder with `.exe` via PyInstaller (build on Windows machine)
- No Python installation required on target machine
- No internet connection required (all assets embedded)

## Technology Stack

| Component     | Technology              | Purpose                        |
|---------------|------------------------|--------------------------------|
| Language      | Python 3.11+           | Core logic                     |
| Data          | pandas ≥ 2.0           | Data manipulation              |
| Curve fitting | scipy ≥ 1.11           | 4PL fitting (curve_fit)        |
| Visualization | plotly ≥ 5.18          | Interactive HTML charts        |
| Templating    | Jinja2 ≥ 3.1           | HTML report generation         |
| Excel I/O     | openpyxl ≥ 3.1         | Layout reading, Excel export   |
| Web server    | Flask ≥ 3.0            | Local web UI                   |
| Packaging     | PyInstaller ≥ 6.0      | Standalone executable          |
