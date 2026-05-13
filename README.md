# Uvira Luminex QC Tool

<p align="center">
  <img src="gdd_antibody_square_tighter.png" alt="Uvira Luminex QC" width="128">
</p>

<p align="center">
  <strong>Automated quality control for 200-plex Luminex immunoassays on Intelliflex</strong><br>
  <em>Geneva Disease Dynamics Group &middot; University of Geneva</em>
</p>

> **Migration in progress.** This codebase is being adapted from the
> original 12-plex MPXV MagPix tool to the 200-plex Uvira / Intelliflex
> pilot. The README sections below largely describe the legacy MPXV
> behaviour and will be rewritten as Sections 3–7 of
> [UVIRA_TODO.md](UVIRA_TODO.md) land.

<p align="center">
  <a href="SPECIFICATION.md">Full Specification</a>
</p>

---

## Overview

Standalone desktop tool for QC of Tetracore 12-plex monkeypox (MPXV) Luminex immunoassays run on a MagPix instrument. Upload xPONENT CSV exports and get interactive HTML reports with:

- **4-Parameter Logistic (4PL) standard curve fitting** with automated quality checks
- **Dual standard pool support** — plates with ITM PC and/or ITM PC2 pools are fit independently, with separate AU columns per pool
- **AU quantification** (inverse Relative Antibody Units) for all specimen wells
- **Bead count validation** (minimum 30 beads per well-analyte)
- **PC replicate variability** monitoring (CV threshold)
- **Negative control tracking** across plates
- **Kit control bead QC** (NC, ScG, FC, IC) with sample IDs on flagged wells
- **Historical trend plots** for standard curves, PC MFI, and NC levels across plates
- **Obs/Exp recovery** for standard curve points with reportable range (LLOQ--ULOQ)
- **Plate reordering** — drag and drop plates into any order, save, then regenerate all reports with history plots reflecting that order
- **Excel export** of all data across plates
- **Web-based settings** for QC thresholds, panel definition, and assay configuration (persisted to YAML)

No Python installation or internet connection required &mdash; runs as a self-contained macOS `.app` or Windows `.exe`.

## Assay Panel

| Bead | Analyte | | Bead | Control |
|------|---------|---|------|---------|
| 01 | MVA Ag | | 09 | NC (negative control) |
| 02 | VACV A33R | | 10 | ScG (sample control) |
| 03 | MPXV A35R | | 11 | FC (fluorescent conjugate) |
| 04 | MPXV B6R | | 12 | IC (instrument control) |
| 05 | MPXV A27 | | | |
| 06 | MPXV E8L | | | |
| 07 | MPXV H3L | | | |
| 08 | MPXV M1R | | | |

## Quick Start

### Download

Download the latest release for your platform from the [Releases](https://github.com/GenevaIDD/mpox-luminex-qc/releases) page:

- **macOS**: `MPXV Luminex QC.app` (~138 MB)
- **Windows**: `MPXV-Luminex-QC/` folder with `.exe`

### Run

1. **macOS**: Double-click `MPXV Luminex QC.app`. If macOS blocks it, right-click > Open, or run in Terminal:
   ```bash
   xattr -cr "MPXV Luminex QC.app"
   open "MPXV Luminex QC.app"
   ```

2. **Windows**: Double-click `MPXV-Luminex-QC.exe` inside the extracted folder.

3. Your browser opens automatically to the upload page.

4. Upload one or more xPONENT CSV files (and optionally a plate layout XLSX), then click **Generate Report**.

### Input Files

| File | Required | Description |
|------|----------|-------------|
| xPONENT CSV | Yes | MagPix instrument export with Median and Count data blocks |
| Plate layout XLSX | No | Maps well positions to sample IDs and visit dates |

## QC Checks

### Standard Curve Fit Quality

Each of the 8 antigen standard curves is fit independently per standard pool using a 4PL model:

```
y = d + (a - d) / (1 + (x / c)^b)
```

| Check | Criterion | Rationale |
|-------|-----------|-----------|
| R² | >= 0.95 | Goodness of fit |
| IC50 | Within tested dilution range (±3x) | Inflection point plausibility |
| Hill slope | 0.3 -- 5.0 | Prevents flat or step-function fits |
| Dynamic range | >= 3-fold | Adequate signal separation |

### Standard Recovery (Obs/Exp)

Each standard point is backcalculated through the 4PL to verify accuracy. Points with recovery outside &plusmn;30% (configurable) are flagged as red triangles on the standard curve plot. The **reportable range** (LLOQ--ULOQ) spans standard points with acceptable recovery.

### Other QC Checks

- **Bead counts**: Flag well-analyte pairs with < 30 beads
- **PC replicate CV**: Flag duplicates with CV > 25%
- **Kit control beads**: NC < 150, ScG > 10000, FC 2000--5000, IC 2000--3000

All thresholds are configurable via the Settings page.

## Output

### AU (Arbitrary Units)

For each specimen, the 4PL standard curve is inverted to find the equivalent dilution factor. The AU scale is anchored so that the first (lowest) standard dilution = 1000 AU:

```
AU = (first_dilution / interpolated_dilution) × 1000
```

Higher AU = more antibody. For example, with a standard starting at 1:100, a specimen matching the 1:100 MFI gets AU = 1000, one matching 1:300 gets AU ≈ 333. Values are flagged when extrapolated beyond the observed standard curve range.

### Reports & Exports

| Output | Format | Description |
|--------|--------|-------------|
| QC Report | HTML | Interactive per-plate report with Plotly charts; includes in-report CSV download for specimen results |
| Specimen data | CSV | Per-plate results with AU columns per pool (when multiple pools present) |
| All data export | XLSX | Combined workbook across all plates (specimens, fit params, NC levels) |

All outputs are stored in `~/mpox-luminex-qc-results/`. Uploaded CSV files are retained in `uploads/` to allow **Regenerate All** without re-uploading.

## Development

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Setup

```bash
git clone https://github.com/GenevaIDD/mpox-luminex-qc.git
cd mpox-luminex-qc
uv sync
```

### Run in dev mode

```bash
uv run python -m src.main
```

### Build standalone app

**macOS:**
```bash
uv run python -m PyInstaller mpox-luminex-qc.spec --clean -y
codesign --force --deep --sign - "dist/MPXV Luminex QC.app"
```

**Windows:**
```bash
python -m PyInstaller mpox-luminex-qc-win.spec --clean -y
```

### Regenerate app icons

```bash
uv run python scripts/make_icon.py
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Data | pandas |
| Curve fitting | scipy (curve_fit) |
| Visualization | plotly |
| Web UI | Flask |
| Reports | Jinja2 |
| Configuration | PyYAML |
| Excel I/O | openpyxl |
| Packaging | PyInstaller |

## Contact

**Andrew Azman** &mdash; [andrew.azman@unige.ch](mailto:andrew.azman@unige.ch)

Geneva Disease Dynamics Group, Institute of Global Health, University of Geneva

## License

This project is developed for internal use by the Geneva Disease Dynamics Group (and friends).
