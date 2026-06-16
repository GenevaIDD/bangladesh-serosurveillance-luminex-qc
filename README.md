---
editor_options: 
  markdown: 
    wrap: 72
---

# Bangladesh Serosurveillance Luminex QC Tool

<p align="center">

<img src="gdd_antibody_square_tighter.png" alt="Bangladesh Serosurveillance Luminex QC" width="128"/>

</p>

<p align="center">

<strong>Automated quality control for the 202-plex Luminex immunoassay
(Intelliflex, 384-well, High PMT) — Bangladesh National
Serosurveillance</strong><br> <em>Geneva Disease Dynamics Group ·
University of Geneva</em>

</p>

<p align="center">

<a href="SPECIFICATION.md">Full Specification</a>

</p>

------------------------------------------------------------------------

## Overview

Standalone desktop tool for QC of the Bangladesh National
Serosurveillance **202-plex** Luminex immunoassay, run on a Luminex
**Intelliflex** instrument in **High PMT** mode on a **384-well** plate.
Upload an xPONENT plate-result CSV and get back a self-contained
interactive HTML report with:

-   **Plate Overview** — a metadata table (Plate ID, Batch, Run date,
    Operator, Instrument, Operating mode, CSV file) and count cards
    (total / PC / NC / specimen / background wells, antigens), plus a
    **shape-coded 384-well plate map** (○ PC, ✕ NC, ■ specimen, ▫
    background) with hover and freeze-pane scroll.
-   **Bead Count** — a freeze-pane antigen × well tier heatmap (red \<
    30, yellow 30–49, green ≥ 50) and "≥ X % flagged" summary cards.
-   **Background QC** — per-antigen spread of the blank wells
    (individual MFIs, SD, %CV) and a cross-plate **IQR-vs-current**
    overview (the current plate's mean against the interquartile range
    of previous plates).
-   **Multi-pool 4PL standard curves** — a 4PL is fit for **every
    antigen against every control pool**. By default (per-pool mode) there
    is no matching: specimen RAU / range are scored against a single
    **scoring pool**, and the master export carries RAU under every pool.
    An optional auto-select mode instead scores each antigen against the
    pool that calibrates it (matched by pathogen, tie-broken by best fit).
-   **Standard-Curve Summary + All-Curves Overview** for the priority
    antigens, with the linear/reportable range drawn as a green square,
    out-of-tolerance standards as red triangles, and a current-plate
    specimen rug.
-   **Standard-Curve Picker** — type to inspect any antigen's curve,
    rug, and cross-plate overlays (review tool; folded by default).
-   **Standard-Curve Range Matrix** — every specimen × antigen
    classified IN / BELOW / ABOVE range / NO_FIT, with a folded
    **Serum-vs-DBS** comparison.
-   **Negative Control QC** — per-antigen NC MFI tracked across plates,
    with each negative control (Negative 0, Negative 49) kept separate.
-   **Downloads** — per-plate CSVs plus a clean master "results" table
    with RAU.

No Python installation or internet connection required — runs as a
self-contained macOS `.app` or Windows `.exe`.

## Download & install

Download the latest build from the
[**Releases**](https://github.com/GenevaIDD/bangladesh-serosurveillance-luminex-qc/releases)
page (no Python or internet connection needed to run it).

**macOS** — download `Bangladesh-Serosurveillance-Luminex-QC-macOS.zip`:

1. Double-click the zip to unzip; you'll get **Bangladesh Serosurveillance
   Luminex QC.app**. Move it to `Applications` (optional).
2. The app is ad-hoc signed, so on first launch macOS will warn it's from an
   unidentified developer. **Right-click the app → Open → Open** (only needed
   the first time). If it's still blocked, open Terminal and run:
   ```bash
   xattr -cr "/Applications/Bangladesh Serosurveillance Luminex QC.app"
   open "/Applications/Bangladesh Serosurveillance Luminex QC.app"
   ```
3. Your browser opens automatically at the upload page.

**Windows** — download `Bangladesh-Serosurveillance-Luminex-QC-Windows.zip`:

1. Right-click the zip → **Extract All** to a folder.
2. Open the extracted `Bangladesh-Serosurveillance-Luminex-QC` folder and
   double-click **Bangladesh-Serosurveillance-Luminex-QC.exe**.
3. On first run, Windows SmartScreen may show "Windows protected your PC" —
   click **More info → Run anyway** (only needed the first time).
4. Your browser opens automatically at the upload page.

**Using it:** on the upload page, select one or more xPONENT plate-result CSVs
and click **Generate Report**. Reports and CSVs are saved under
`~/bangladesh-serosurveillance-luminex-qc-results/` (see [Output](#output)).
To quit, use the **Quit Application** button on the home page.

> If the Releases page is empty, no build has been published yet — see
> [Development](#development) to build locally, or push a `vX.Y.Z` tag to
> trigger the automated build/release workflow.

## Assay panel

The production panel is **202 antigens** (pilot plates ran fewer beads
because some bead-antigen reagents were in short supply). The panel is
**re-derived from the `Median` block header of each xPONENT CSV on every
ingest**, so the per-plate panel is always authoritative; the default
list in `src/config.py` is a display/fallback only. Families include
`ARB_`, `FLU_`, `HCoV_`/`SARS_`, `HEP_`, `HHV_`, `MAL_`, `NTD_`, `POX_`,
`RES_`, `STI_`, `TBD_`, `VPD_`, `CHO_`, `BAC_`, `ENT_`, `HAN_`, `OTH_`,
`TOXO_`, `CTRL_`.

## Plate layout & controls

384-well plate (rows A–P × columns 1–24). Wells are classified from the
`Sample` name in the CSV (no Intelliflex input file is required):

| Type | Sample name | Notes |
|------------------------|------------------------|------------------------|
| Background | `Background0` | Plate blanks |
| Negative control (NC) | `Pilot Control: Negative 0 / 49 , 1:1000` | Pooled pre-2019 North American plasma; two controls, each in duplicate |
| PC / standard | `Pilot Control: <pool> <dilution>` | Multiple pooled controls, each its own dilution series |
| Specimen | `{id}_r3_{Serum\|DBS}` | Each person run as both Serum and DBS |

**Control pools** each carry their dilution in the sample name (`1:N`,
or `N ng/mL` for HlyE) and calibrate specific pathogens:

-   **Anti-OSP & cTxB (± HlyE) pool** → cholera (OSP / CtxB) — and
    typhoid HlyE in the combined pool
-   **HlyE** → *S. typhi* HlyE (concentration series)
-   **Dengue pool** + **ORPAL pool** → DENV antigens
-   **Cholera High / Low** → single-point range markers (not fit)

### Antigen → pool scoring (`pool_mode`, set in Settings)

A 4PL is fit for every (pool × antigen). Two modes control how specimens
are then scored:

-   **per_pool (default)** — "fit every pool × antigen, no matching." RAU
    and range status are computed against a single **scoring pool** (by
    default the pool with the most passing fits; set `scoring_pool` to
    override). The Summary table and All-Curves Overview show one row /
    grid per pool, and the master export lists RAU + status under *every*
    pool so you can pick the right one per antigen.
-   **auto_select** — each antigen is scored against the pool meant to
    calibrate it: the tool parses the antigen's pathogen from its name and
    matches it to the targeting pool(s); when more than one pool targets
    the same pathogen (e.g. Dengue pool vs ORPAL), the **best-fitting
    curve** wins (params present → fit_ok → highest R²). Antigens with no
    name match fall back to the best-fitting pool. You can refine the
    matching with a regex rules field and exact per-antigen overrides in
    Settings.

## QC checks

### Bead counts

`bead_count_min` (red below, default 30) and `bead_count_warn` (yellow
below / green at-or-above, default 50). Antigens and specimens are
flagged when ≥ `problem_fraction_threshold` (default 20 %) of their
cells are red or yellow.

### Standard-curve fit quality

Each antigen's 4PL fit is `fit_ok` only when all of: R² ≥ 0.95 (log10),
IC50 inside the tested dilution range (×3 margin), Hill slope 0.3–5.0,
dynamic range ≥ 3×. A failing fit can retry by dropping a single outlier
point (configurable).

### Range classification

Per (specimen × antigen): `IN_RANGE` / `BELOW_RANGE` / `ABOVE_RANGE` /
`NO_FIT`, using the antigen's selected-pool curve. LLOQ / ULOQ come from
a ±30 % (configurable) Obs/Exp recovery check.

### Background QC

Per-antigen SD / %CV across the blank wells, the individual MFIs, and
the current-plate vs previous-plate IQR. The max-MFI (default 300) and
%CV are tracked as reference thresholds — **formal Background pass/fail
flagging is still in development**.

### Negative control

NC wells (matching `Negative`) are tracked per antigen across plates,
with each negative control kept separate (duplicate wells averaged
within each control). Deeper NC-level flagging is in development.

## Output

All persistent data is stored under
`~/bangladesh-serosurveillance-luminex-qc-results/`:

```         
  reports/
    QC_<plate_id>.html              # interactive report
    results_<plate_id>.csv          # clean master (per_pool: RAU+status per pool; auto_select: single-pool tidy)
    in_range_<plate_id>.csv         # IN/BELOW/ABOVE/NO_FIT per (specimen × antigen)
    pct_in_range_<plate_id>.csv     # per-antigen %-in-range
    bead_problems_*.csv / bead_problem_{antigens,samples}_*.csv
    range_problem_{antigens,samples}_*.csv
    background_qc_<plate_id>.csv
    nc_levels_<plate_id>.csv
  specimens/
    specimens_<plate_id>.csv        # raw + per-pool AU columns
  history/                          # cross-plate JSON (per-pool fit/curve, background, specimen, NC)
  uploads/                          # uploaded CSVs kept for Regenerate All
  config.yaml                       # user settings overrides
```

The home page **Export All Processed Data (.xlsx)** combines every plate
into a workbook. Its headline `results` sheet is the clean master table:
in the default **per_pool** mode it carries RAU + range status under
**every** control pool (so each antigen's cholera / dengue / typhoid
pool RAU sit side by side, `NO_FIT` where a pool doesn't calibrate it);
in **auto_select** mode it's the tidy single selected-pool table. The
`specimens`, `standard_curve_params`, `standard_curve_data`, and
`nc_levels` sheets follow.

## Settings

Editable on the Settings page (persisted to `config.yaml`):
well-classification patterns, **priority antigens** (curves shown in the
Summary/Overview; blank = all), excluded analytes, bead-count
thresholds, problem-fraction threshold, background %CV and max-MFI
reference thresholds, recovery tolerance, and the single-outlier drop
toggle.

## Development

``` bash
git clone https://github.com/GenevaIDD/bangladesh-serosurveillance-luminex-qc.git
cd bangladesh-serosurveillance-luminex-qc
uv sync
uv run python -m src.main          # dev server
```

Build standalone apps:

``` bash
# macOS
uv run python -m PyInstaller bangladesh-serosurveillance-luminex-qc.spec --clean -y
codesign --force --deep --sign - "dist/Bangladesh Serosurveillance Luminex QC.app"
# Windows
python -m PyInstaller bangladesh-serosurveillance-luminex-qc-win.spec --clean -y
```

## Tech stack

pandas, scipy (`curve_fit` on log10 MFI), plotly + matplotlib, Flask,
Jinja2, PyYAML, openpyxl, PyInstaller.

## Contact

**Andrew Azman** —
[andrew.azman\@unige.ch](mailto:andrew.azman@unige.ch) Geneva Disease
Dynamics Group, Institute of Global Health, University of Geneva

## License

Developed for internal use by the Geneva Disease Dynamics Group (and
friends).
