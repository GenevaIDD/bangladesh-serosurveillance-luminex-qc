# Uvira Luminex QC Tool — Specification
# Version 0.9.0-uvira

## Overview

Standalone quality control tool for **200-plex Luminex immunoassays** run on a Luminex **Intelliflex** instrument. Processes the xPONENT plate-run CSV (and optionally the Intelliflex input-file CSV and a barcode-map XLSX), runs the QC pipeline, fits 4PL standard curves per antigen, and renders a self-contained interactive HTML report.

Distributed as a macOS `.app` or Windows `.exe` requiring no Python installation or internet connection.

## Assay Panel

The Uvira pilot panel is **~200 antigens** across families (ARB, FLU, HCoV, SARS, HEP, HHV, MAL, NTD, POX, RES, STI, TBD, VPD, plus a handful of `BAC_`, `CHO_`, `CTRL_`, `ENT_`, `HAN_`, `OTH_`, `TOXO_`). The full default panel lives in `src/config.py::ANTIGENS`; on every plate ingest the panel is **re-derived from the CSV's `Median` block header** so the per-plate panel is always authoritative.

Three bead regions are flagged as **excluded** (added in error during plate setup) and rendered visually muted everywhere but never dropped from the data:

- `FLU_B_HA_Maryland_1959`
- `FLU_B_NP_Brisbane_2008`
- `VPD_Tet_tox`

The excluded list is editable from the Settings page.

## Plate Layout

Standard 96-well plate, Intelliflex convention used in the Uvira pilot:

- **A1 – A10** — Standard1 .. Standard10 (10-point, 4-fold serial dilution from `62.5` to `16,384,000`).
- **A11 – A12** — Background wells (plate blanks, used by Background QC).
- **B1 onward** — Specimen wells, named by on-plate barcode (e.g. `FD22124871`).

Variations handled:

- Missing Background wells (Background QC section renders an empty-state banner).
- Plates that include named NC samples (`NC*`, `Negative*`, or `Control*` — patterns editable on the Settings page) — they are classified as a separate well type and reported in a dedicated NC QC section, distinct from Background.

Pool-based standard curves (the MagPix-era `ITM PC` / `ITM PC2` concept) are not used; a single `PC` pool is fit per plate. The per-pool dict structure is preserved internally for forward-compat.

## Input Files

### xPONENT plate-run CSV (required)

Multi-block CSV exported from the Intelliflex xPONENT software. The parser handles both Intelliflex and legacy MagPix headers (`Program` line, `Build`, `Date`, `SN`, `Batch`, `BatchDescription`, `PanelName`, `BatchStopTime`) plus the expanded Intelliflex `DataType:` set (Median, Mean, Count, %CV, Peak, Std Dev, Trimmed Peak / SD / Mean, Net MFI, Avg Net MFI, Units, Dilution Factor). Only the `Median` and `Count` blocks are used today.

The plate ID is taken from `BatchDescription` verbatim on Intelliflex (e.g. `PLATE_05112026_RUN000`); the legacy MagPix `-Plate\d+` regex is kept as a fallback.

### Intelliflex input-file CSV (optional)

Plate input file (`*_inputfile.csv`) with columns `Location, Plate Type, Type, Description, Dilution`. Used to map wells to plate-well type and the on-plate barcode (`Description`). The pipeline merges this onto the parsed plate data via `parse_layout.build_layout()`.

### Barcode-map XLSX (optional)

One of the `RENAMED-Box{N}_Uvira_*.xlsx` files (one per Box). Provides `Container Id`, `Barcode`, `ID` (patient ID) and others. The pipeline joins on `Barcode` to add `patient_id` and `box_id` to every specimen well. The picker plate-label uses the leading `Box\d+` portion of the Container Id (e.g. `Box1_Uvira_sera_2023` → `Box1`).

## QC Checks

### 1. Bead counts

Three-tier classification per well-analyte:

- **Red**: count `<` `bead_count_min` (default 30). Bead loss / aspiration issue.
- **Yellow**: `bead_count_min ≤` count `<` `bead_count_warn` (default 50).
- **Green**: count `≥` `bead_count_warn`.

The report renders the matrix as a Plotly heatmap with dotted vertical separators between well-type groups (Standards / Background / NC / specimen), and a summary card pair counting:

- Antigens where `≥ problem_fraction_threshold` (default 0.20 = 20 %) of wells are red or yellow.
- Specimens where `≥ problem_fraction_threshold` of antigens are red or yellow.

Both axes export problem CSVs (`bead_problem_antigens_<plate>.csv`, `bead_problem_samples_<plate>.csv`).

### 2. Standard curve fitting (4PL)

Model: `y = d + (a - d) / (1 + (x / c)^b)`

| Parameter | Meaning |
|-----------|---------|
| a | Minimum asymptote (high dilution → low MFI) |
| b | Hill slope |
| c | Inflection point (IC50) |
| d | Maximum asymptote (low dilution → high MFI) |

Fits run **on log10(MFI)** so the noise floor and the high-signal upper plateau contribute comparably to the residuals. Linear-residual fitting let the upper plateau dominate and pushed `d` to 0 on faint-signal antigens.

Implementation: `scipy.optimize.curve_fit` with bounds; degenerate-input guard (max-MFI floor, flat-response check); `maxfev=10000`.

**Fit quality criteria** (all must pass for `fit_ok = True`):

| Check | Criterion | Rationale |
|-------|-----------|-----------|
| R² | ≥ 0.95 (log space) | Goodness of fit |
| IC50 (c) | Within `[min_dil / 3, max_dil × 3]` | Inflection inside the tested dilution range |
| Hill slope (b) | `0.3 ≤ b ≤ 5.0` | Prevents flat or step-function fits |
| Dynamic range | `max / min asymptote ≥ 3×` | Adequate signal separation |

If the initial fit converges but fails any criterion, an optional **leave-one-out retry** drops a single standard point (any of the 10) and re-fits. The retry is gated on the initial scipy call having converged (i.e. `params is not None`) so all-zero / flat antigens don't burn 10× the fit time.

### 3. Range classification per (specimen × antigen)

For every specimen well × antigen the parsed MFI is compared to the antigen's LLOQ-MFI and ULOQ-MFI (derived from the fitted 4PL at the LLOQ / ULOQ dilutions). Status:

| Status | Meaning |
|--------|---------|
| `IN_RANGE` | `LLOQ-MFI ≤ MFI ≤ ULOQ-MFI` |
| `BELOW_RANGE` | `MFI < LLOQ-MFI` |
| `ABOVE_RANGE` | `MFI > ULOQ-MFI` |
| `NO_FIT` | antigen has no usable reportable range |

LLOQ / ULOQ are the highest / lowest dilutions whose Obs/Exp recovery sits inside `recovery_tolerance` (default ±30 %).

The report renders the range table as:

- **Standard-Curve Range Matrix** — (specimen × antigen) heatmap, colour-blind-safe palette (BELOW = blue, IN = teal, ABOVE = orange, NO_FIT = yellow).
- **Range summary cards** — antigens / samples that exceed `problem_fraction_threshold` (default 20 %) below or above, with downloadable CSVs (`range_problem_antigens_*.csv`, `range_problem_samples_*.csv`).

### 4. Background QC

For each antigen we look across the Background wells (Row A `^Background`) and compute:

- `n_wells` — number of contributing Background wells.
- `mean_mfi` — mean MFI.
- `sd_mfi` — sample SD (ddof = 1).
- `cv = sd / mean` — coefficient of variation.
- `max_mfi` — single highest Background MFI.
- `cv_flag` — `cv > bg_cv_threshold` (default 0.25).
- `max_flag` — `max_mfi > bg_max_mfi` (default 100).

The section renders three summary cards (CV-flagged count, max-flagged count, antigens with data) and a per-antigen table. Exported as `background_qc_<plate>.csv`. Mirrors the legacy MPOX NC-bead checks, applied to the plate blanks when no named NC sample is present.

### 5. Negative Control QC (when present)

NC wells are identified by `well_type == "nc"` after sample-name pattern matching (`^NC`, `^Negative`, or `^Control` — editable on the Settings page; distinct from Background). When present:

- **Per-plate NC heatmap** — MFI per (NC well × antigen) on a Purples ramp.
- **Cross-plate NC history heatmap** — mean NC MFI per antigen, one row per plate, with the current plate suffixed `(current)`. Populated from `nc_well_history.json` which accumulates per-(plate, well, analyte) rows on every run.
- Exported as `nc_levels_<plate>.csv`.

The Uvira pilot plate has only Background wells and no NC samples, so the heatmap renders an empty-state banner and a "to track NCs name a future well `NC1` / `Negative_pool` / `Control`" hint.

## Computed Outputs

### AU (Arbitrary Units)

For each specimen well and antigen the 4PL is inverted to find the equivalent dilution factor; AU is anchored so the first (lowest) standard dilution = 1000 AU:

```
AU = (first_dilution / interpolated_dilution) × 1000
```

`au_censored` carries `"none" | "left" | "right"` depending on whether the interpolated value falls below LLOQ / above ULOQ.

### Net MFI

`net_mfi = mfi - mean(NC-bead MFI in same well)` clipped at 0. The "NC" analyte (MagPix kit bead) does not exist on Intelliflex Uvira plates, so `net_mfi` is `NaN` in practice on this assay; the column is kept for legacy compatibility.

## Reports

### Per-Plate HTML QC Report

Self-contained HTML (Plotly.js embedded inline, no CDN, fully offline). Two-column layout: sticky **TOC sidebar** on the left, scrollable content on the right. Every top-level section is a `<details>` block, `open` by default; the sidebar's hash links force-open the targeted section on click.

Section order:

1. **Plate Overview** — metadata table, panel size, Box ID(s) loaded, patient-ID resolution count, excluded-analyte banner.
2. **Background QC** — three summary cards, plain-English explainer (Mean / %CV / Max checks with current thresholds inlined), per-antigen table.
3. **Bead-Count Matrix** — four summary cards (antigens flagged, specimens flagged, red cells, yellow cells), Plotly heatmap with group separators, problem-antigen / problem-specimen / every-cell drill-down tables.
4. **Standard-Curve Summary** — four range summary cards (antigens / specimens flagged BELOW or ABOVE), `Fit OK` explainer banner listing the four pass criteria, per-antigen 4PL parameter table, range-problem drill-down tables.
5. **All Curves Overview** — small-multiples PNG grid of every 4PL fit, panel title coloured green/red/grey for `fit_ok` / fail / excluded.
6. **Standard-Curve Picker** — antigen typeahead; two-panel Plotly figure:
   - Left: standards + current 4PL fit (blue) + grey overlays of every prior plate's 4PL (each is a separate legend entry, click to toggle).
   - Right: rug panel with two columns — "This plate" (specimens stacked, coloured by status) and "Past" (historical specimens in grey).
   - Upper-right of the curve panel: a status-count box showing `BELOW n (%)`, `IN n (%)`, `ABOVE n (%)`, `NO_FIT n (%)` for the selected antigen. Refreshes on antigen pick via `Plotly.relayout("annotations", …)`.
7. **Standard-Curve Range Matrix** — (specimen × antigen) heatmap with the CB-safe palette, out-of-range detail list.
8. **Negative Control QC** — heatmap of NC MFI per (well × antigen) when present, cross-plate NC history heatmap when ≥ 1 plate has history.
9. **Downloads** — grouped by section, every CSV exported with a one-line description.

### Per-Plate CSVs

| File | Contents |
|------|----------|
| `specimens_<plate>.csv` | Long-form per (well × analyte) with MFI, net MFI, AU, censoring flag |
| `in_range_<plate>.csv` | Per (specimen × antigen) status (IN / BELOW / ABOVE / NO_FIT) + MFI bounds + optional layout columns (sample_id, barcode, patient_id, box_id) |
| `pct_in_range_<plate>.csv` | Per-antigen rollup (`n_in_range`, `n_below_range`, `n_above_range`, `n_no_fit`, `pct_in_range`) |
| `bead_problems_<plate>.csv` | Long-form red / yellow cell list |
| `bead_problem_antigens_<plate>.csv` | Per-antigen problem fraction + list of problem wells |
| `bead_problem_samples_<plate>.csv` | Per-specimen problem fraction + list of problem antigens |
| `range_problem_antigens_<plate>.csv` | Per-antigen below / above fractions + lists of problem specimens |
| `range_problem_samples_<plate>.csv` | Per-specimen below / above fractions + lists of problem antigens |
| `background_qc_<plate>.csv` | Per-antigen Background mean / SD / %CV / max MFI + flags |
| `nc_levels_<plate>.csv` | Per (NC well × antigen) MFI (written only when NC present) |

## Historical Tracking

JSON files in `<output-dir>/history/` accumulate data across plates for trend monitoring:

| File | Dedup key | Used by |
|------|-----------|---------|
| `std_curve_history_PC.json` | `(plate_id, analyte, dilution)` | report (currently unused in the live picker but available for trend plots) |
| `fit_history_PC.json` | `(plate_id, analyte)` | curve picker — past-plate 4PL overlays |
| `specimen_mfi_history.json` | `(plate_id, well, analyte)` | curve picker — past-plate specimen rug |
| `nc_well_history.json` | `(plate_id, well, analyte)` | NC QC — cross-plate NC heatmap |

Re-processing a plate overwrites its previous history entries (same dedup key). History is **per output directory**; to start fresh, delete the corresponding `history/` folder.

## Application Architecture

### Web Interface (Flask)

- Local-only web server (binds to `127.0.0.1` on a random free port).
- Browser auto-opens on launch.
- Upload form: plate-run CSV (required) + input-file CSV + Box xlsx (both optional).
- Past Reports table with view / download links and per-plate delete button.
- **Regenerate All** — re-runs the full pipeline for every plate in the saved order, rebuilding history overlays.
- Drag-and-drop plate reordering (vendored SortableJS) + Save Order.
- Settings page for thresholds / patterns / panel / soft-flags (persisted to YAML, importable / exportable).
- Quit Application button for graceful shutdown.

### Data Storage

```
~/uvira-luminex-qc-results/
  <output dir>/                       # one per "Generate Report" run
    QC_<plate_id>.html
    *.csv                              # per-plate exports
    history/
      fit_history_PC.json
      std_curve_history_PC.json
      specimen_mfi_history.json
      nc_well_history.json
  uploads/                             # original CSVs / xlsx retained
  plate_registry.json                  # plate order + upload manifest
  config.yaml                          # user overrides (created on first save)
```

### Distribution

- **macOS**: `.app` bundle via PyInstaller (`uvira-luminex-qc.spec`).
- **Windows**: folder with `.exe` via PyInstaller (`uvira-luminex-qc-win.spec`, built on a Windows machine).
- No Python installation required on target machine.
- No internet connection required — Plotly.js is embedded inline on the first chart of each report.

## Technology Stack

| Component     | Technology              | Purpose                        |
|---------------|------------------------|--------------------------------|
| Language      | Python 3.11+           | Core logic                     |
| Data          | pandas ≥ 2.0           | Data manipulation              |
| Curve fitting | scipy ≥ 1.11           | 4PL fitting (`curve_fit` on log10 MFI) |
| Visualization | plotly ≥ 5.18 + matplotlib | Interactive Plotly figures + the small-multiples PNG curve grid |
| Templating    | Jinja2 ≥ 3.1           | HTML report generation         |
| Excel I/O     | openpyxl ≥ 3.1         | Layout reading                 |
| Web server    | Flask ≥ 3.0            | Local web UI                   |
| Packaging     | PyInstaller ≥ 6.0      | Standalone executable          |
