# Uvira Luminex QC Tool

<p align="center">
  <img src="gdd_antibody_square_tighter.png" alt="Uvira Luminex QC" width="128">
</p>

<p align="center">
  <strong>Automated quality control for 200-plex Luminex immunoassays on Intelliflex</strong><br>
  <em>Geneva Disease Dynamics Group &middot; University of Geneva</em>
</p>

<p align="center">
  <a href="SPECIFICATION.md">Full Specification</a>
</p>

---

## Overview

Standalone desktop tool for QC of 200-plex Luminex immunoassays run on a Luminex **Intelliflex** instrument. Upload an xPONENT CSV export (plus an optional input-file CSV and barcode-map XLSX) and get back an interactive HTML report with:

- **4-Parameter Logistic (4PL) standard curve fitting** for every antigen on the plate, with `fit_ok` criteria (R² ≥ 0.95 on log10, IC50 in range, Hill slope 0.3–5, dynamic range ≥ 3×).
- **Standard-Curve Range Matrix** — every specimen × antigen classified as `IN_RANGE` / `BELOW_RANGE` / `ABOVE_RANGE` / `NO_FIT`, in a colour-blind-safe palette.
- **Standard-Curve Picker** — type to search any of the 200 antigens; the curve, status-counted specimen rug, and historical-plate overlays all swap interactively.
- **Bead-Count Matrix** — Red / Yellow / Green tier heatmap with dotted-line separators between Standards / Background / NC / specimen well groups, and "≥ X% problematic" summary cards on both axes.
- **Negative Control QC** — heatmap of NC well MFI per antigen plus a cross-plate drift heatmap.
- **Background QC** — mean / SD / %CV / max-MFI per antigen across the Row-A Background wells, with configurable CV and max-MFI flags. Mirrors the legacy MPOX NC checks when no named NC sample is present.
- **Excluded-analyte soft-flagging** — bead regions known to have been added in error stay in every table and plot but are visually muted.
- **Cross-plate history** — standard curves, NC MFI, fit parameters, and specimen MFI are persisted to JSON per output directory. Subsequent plates render past plates' fits + specimens as grey overlays in the curve picker (legend-toggleable).
- **Downloads** — every QC axis exports a per-plate CSV (range table, bead-problem lists per axis, NC levels, Background QC, etc.) for downstream analysis.
- **Settings page** — pattern matching for PC / Background / NC wells, problem-fraction threshold, bead-count tiers, BG CV / max-MFI cutoffs, soft-flag list, and the standard dilution series, all persisted to YAML.

No Python installation or internet connection required — runs as a self-contained macOS `.app` or Windows `.exe`.

## Assay panel

The Uvira pilot panel is **200 antigens** plus the row-A Background wells, with families:

| Family prefix | Examples |
|---|---|
| `ARB_` | DENV1–4, ZIKV, YFV, JEV, WNV, CHIKV, RVFV, USUV, … |
| `FLU_` | H1N1 / H3N2 / H5N1 / B HA + NP across many strains |
| `HCoV_` / `SARS_` | 229E, NL63, OC43, HKU1, SARS-CoV-2 Wuhan + Omicron |
| `HEP_` | HBV, HCV, HEV, HepA |
| `HHV_` | CMV, EBV, HSV1/2, VZV, HHV6B/7 |
| `MAL_` | Pf / Pv / Pm / Po MSP, CSP, AMA1, … |
| `NTD_` | Leishmania, Bm14, cp23, pgp3, VSP3/5, … |
| `POX_` | MpoxV HA, A44R, E8L; Vaccinia |
| `RES_` | RSVA/B, Rhinovirus, mumps, measles, hMPV, … |
| `STI_` | HPV16/18, Chlamydia, Gonorrhea |
| `TBD_` | Borrelia / Lyme antigens |
| `VPD_` | Pertussis, Diphtheria, Tetanus, measles, rubella, NmB |
| Plus | `BAC_`, `CHO_`, `CTRL_`, `ENT_`, `HAN_`, `OTH_`, `TOXO_` |

The full panel is derived from the `Median` block header of each xPONENT CSV on every ingest, so the per-plate panel is always authoritative. The configured default list in `src/config.py` is a fallback for display only.

## Quick Start

### Download

Download the latest release for your platform from the [Releases](https://github.com/GenevaIDD/uvira-luminex-qc/releases) page:

- **macOS**: `Uvira Luminex QC.app`
- **Windows**: `Uvira-Luminex-QC/` folder with `.exe`

### Run

1. **macOS**: Double-click `Uvira Luminex QC.app`. If macOS blocks it, right-click → Open, or run in Terminal:
   ```bash
   xattr -cr "Uvira Luminex QC.app"
   open "Uvira Luminex QC.app"
   ```

2. **Windows**: Double-click `Uvira-Luminex-QC.exe` inside the extracted folder.

3. Your browser opens automatically to the upload page.

4. Upload the three files (the last two are optional but recommended) and click **Generate Report**.

### Input Files

| File | Required | Description |
|------|----------|-------------|
| **xPONENT CSV** | Yes | Intelliflex plate-run export (`PlateRunResults_*.csv`) with `Median`, `Count`, and the other DataType blocks. MagPix CSVs also parse for legacy use. |
| **Input-file CSV** | Optional | Intelliflex plate input file (`*_inputfile.csv`) mapping wells to plate-well type, barcode, and dilution. When provided the report shows the on-plate barcode for every specimen. |
| **Barcode-map XLSX** | Optional | One of the Box-N `RENAMED-Box{N}_Uvira_*.xlsx` files. Joins barcode → patient_id and box_id so the report carries patient IDs and the picker labels plates by box. |

## QC Checks

### Standard Curve Fit Quality

Each antigen's 10-point 4-fold standard curve is fit to a 4PL:

```
y = d + (a - d) / (1 + (x / c)^b)
```

`fit_ok = True` only when all four of the following pass:

| Check | Criterion | Rationale |
|-------|-----------|-----------|
| R² | ≥ 0.95 on log10(MFI) | Goodness of fit (log-residual fit; matches standard immunoassay practice) |
| IC50 | Within tested dilution range × 3 | Inflection point inside the curve's reach |
| Hill slope | 0.3 ≤ b ≤ 5.0 | Prevents flat or step-function fits |
| Dynamic range | upper / lower asymptote ≥ 3× | Adequate signal separation |

If the initial fit fails, a leave-one-out retry drops a single standard point and re-tries (configurable on the Settings page).

### Range classification

Per (specimen × antigen):

- `IN_RANGE` — MFI between LLOQ-MFI and ULOQ-MFI on that antigen's 4PL.
- `BELOW_RANGE` — MFI < LLOQ-MFI.
- `ABOVE_RANGE` — MFI > ULOQ-MFI.
- `NO_FIT` — that antigen has no usable curve (fit failed or no reportable range).

LLOQ / ULOQ come from a ±30 % (configurable) Obs/Exp recovery check on the standard points.

### Summary thresholds

The bead-count and range summaries flag antigens / specimens that exceed a **problem-fraction threshold** (default 20 %, editable on the Settings page). Both axes get a downloadable CSV listing exactly which (antigen × sample) pairs caused each flag.

### Other QC

- **Bead counts** — `bead_count_min` (red below) and `bead_count_warn` (yellow below) thresholds.
- **Excluded analytes** — soft-flag list editable on the Settings page (defaults to `FLU_B_HA_Maryland_1959`, `FLU_B_NP_Brisbane_2008`, `VPD_Tet_tox`).
- **Background QC** — per-antigen mean / SD / %CV / max-MFI across the Row-A Background wells. Antigens with %CV > 25 % (`bg_cv_threshold`) or max-MFI > 100 (`bg_max_mfi`) are flagged.
- **NC QC** — when a future plate adds a sample named `NC*`, `Negative*`, or `Control*`, its MFI is rendered as a heatmap and persisted to a cross-plate history JSON.

## Output

All persistent data is stored under `~/uvira-luminex-qc-results/`:

```
~/uvira-luminex-qc-results/
  <output dir>/
    QC_<plate_id>.html              # main interactive report
    specimens_<plate_id>.csv        # per-(specimen × antigen) MFI + AU
    in_range_<plate_id>.csv         # IN/BELOW/ABOVE/NO_FIT status per (specimen × antigen)
    pct_in_range_<plate_id>.csv     # per-antigen %-in-range summary
    bead_problems_<plate_id>.csv    # red/yellow bead-count list
    bead_problem_antigens_*.csv     # antigens with ≥ X% problematic wells
    bead_problem_samples_*.csv      # samples with ≥ X% problematic antigens
    range_problem_antigens_*.csv    # antigens with ≥ X% below/above
    range_problem_samples_*.csv     # samples with ≥ X% below/above
    background_qc_<plate_id>.csv    # Background QC per antigen
    nc_levels_<plate_id>.csv        # only when an NC well is present
    history/                        # cross-plate JSON (auto-updated)
      fit_history_PC.json
      std_curve_history_PC.json
      specimen_mfi_history.json
      nc_well_history.json
  uploads/                          # uploaded CSVs / xlsx kept for re-runs
  plate_registry.json               # plate order + upload manifest
  config.yaml                       # user overrides
```

Uploaded CSVs are retained so that **Regenerate All** can re-run the pipeline without re-upload.

## Development

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Setup

```bash
git clone https://github.com/GenevaIDD/uvira-luminex-qc.git
cd uvira-luminex-qc
uv sync
```

### Run in dev mode

```bash
uv run python -m src.main
```

### Build standalone app

**macOS:**
```bash
uv run python -m PyInstaller uvira-luminex-qc.spec --clean -y
codesign --force --deep --sign - "dist/Uvira Luminex QC.app"
```

**Windows:**
```bash
python -m PyInstaller uvira-luminex-qc-win.spec --clean -y
```

### Regenerate app icons

```bash
uv run python scripts/make_icon.py
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Data | pandas ≥ 2.0 |
| Curve fitting | scipy ≥ 1.11 (`curve_fit` on log10 MFI) |
| Visualization | plotly ≥ 5.18 + matplotlib (for the small-multiples curve grid) |
| Web UI | Flask ≥ 3.0 |
| Reports | Jinja2 ≥ 3.1 |
| Configuration | PyYAML ≥ 6.0 |
| Excel I/O | openpyxl ≥ 3.1 |
| Packaging | PyInstaller ≥ 6.0 |

## Contact

**Andrew Azman** — [andrew.azman@unige.ch](mailto:andrew.azman@unige.ch)

Geneva Disease Dynamics Group, Institute of Global Health, University of Geneva

## License

This project is developed for internal use by the Geneva Disease Dynamics Group (and friends).
