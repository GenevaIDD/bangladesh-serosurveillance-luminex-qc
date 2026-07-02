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

-   **Plate Overview** — a metadata table (Plate ID, Batch, **Run date &
    time** = the parsed run start, Operator, Instrument, Operating mode,
    CSV file) and a single row of count cards (total / PC / **each
    single-point control, e.g. Cholera High / Cholera Low** / NC / specimen
    / background wells, antigens), plus a **shape-coded 384-well plate map**.
-   **Bead Count** — a freeze-pane antigen × well tier heatmap (red \< 30,
    yellow 30–49, green ≥ 50) with a "how it works" description box,
    "≥ X % flagged" summary cards, and a mechanics note.
-   **Background QC** — per-antigen spread of the blank wells (per-well MFIs,
    SD, %CV, an intra-plate **High CV** flag, an inter-assay **High hist. CV**
    flag for run-to-run drift, and a `⚠ outlier` badge on antigens with a
    leave-one-out well outlier) and a cross-plate overview with a
    **Median ± IQR / Per-plate data points** toggle (per-plate view colours
    the current plate red and past plates on a chronological blue→green
    gradient). Hidden tables flag single-well outliers and negative net MFI.
-   **Positive & Negative Control QC** — the same two-view cross-plate
    overview for the single-point PCs (Cholera High/Low) and NC controls,
    plus an NC **duplicate-%CV** flag table.
-   **Multi-pool 4PL standard curves** — a 4PL is fit for **every
    antigen against every control pool**. By default (auto-select mode)
    each antigen is scored against the pool that calibrates it — cholera →
    Anti-OSP & cTxB, typhoid → HlyE, dengue → Dengue/Orpal, and other
    arboviruses & VPDs (no dedicated standard) → the Dengue/Orpal reference
    pools — matched by pathogen name, tie-broken by best fit, and fully
    YAML-overridable. Measles/diphtheria/rubella/tetanus prefer a **NIBSC**
    pool when one is on the plate. Every specimen carries a **calibration
    tier** (standard / reference / uncalibrated) so best-fit-only RAUs are
    clearly flagged. An optional per-pool mode instead scores every antigen
    against a single **scoring pool** and exports RAU under every pool.
-   **Standard-Curve Summary + All-Curves Overview** — one fit table per
    pool (labelled with pathogen targets); featured priority antigens each
    shown against their single best-fit standard, with the antigen's
    **past-plate curves overlaid in light grey** (Show all / Hide toggle) and
    all antigen × pool fits in a collapsed block. Range-problem tables show the
    calibrating Standard per antigen.
-   **Standard-Curve Picker** — type to inspect any antigen's curve, rug,
    and cross-plate overlays; the panel is titled with the selected
    **antigen × pool**; rug columns run current → nearest → oldest with labels
    on top; axes labelled (Standard dilution / MFI). Folded by default.
-   **Standard-Curve Range Matrix** — every specimen × antigen classified
    IN / BELOW / ABOVE range / NO_FIT against its matched standard; antigen
    rows grouped and colour-labelled by pathogen, and each **cell's hover names
    the calibrating standard + tier**; folded **Serum-vs-DBS** comparison.
-   **Chronological across plates** — cross-plate history, legends and rug
    columns are ordered by the parsed **run date + time** (`BatchStartTime`),
    independent of upload order; a warning banner shows if that datetime
    can't be parsed.
-   **Downloads** — per-plate CSVs plus a clean master "results" table with
    RAU and the calibration tier.

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

-   **auto_select (default)** — each antigen is scored against the pool
    meant to calibrate it: the tool parses the antigen's pathogen from its
    name and matches it to the targeting pool(s). Cholera → Anti-OSP &
    cTxB, typhoid → HlyE, dengue → Dengue/Orpal; other arboviruses
    (`ARB_`) and VPDs (`VPD_`, plus `RES_measles_lysate`) have no dedicated
    standard and use the Dengue/Orpal reference pools. When more than one
    pool targets the same category (e.g. Dengue vs ORPAL), the
    **best-fitting curve** wins (params present → fit_ok → highest R²).
    Antigens with no name match fall back to the best-fitting pool. Refine
    the matching with a regex rules field and exact per-antigen overrides
    in Settings (or the YAML).
-   **per_pool** — "fit every pool × antigen, no matching." RAU and range
    status are computed against a single **scoring pool** (by default the
    pool with the most passing fits; set `scoring_pool` to override). The
    Summary and All-Curves Overview show one table / grid per pool, and the
    master export lists RAU + status under *every* pool.

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

Per-antigen SD / %CV across the blank wells, the individual MFIs, and the
current-plate vs previous-plate IQR (with a Median ± IQR / Per-plate toggle).
Rows are flagged for high **intra-plate %CV** (> `bg_cv_threshold`, spread across
this plate's wells), high **inter-assay %CV** (> `hist_cv_threshold`, run-to-run
drift of the historical means), and for a **single-well outlier** (leave-one-out:
a well > mean + 2·SD of the other wells; the literal all-wells figures are shown
alongside). A hidden table flags specimen × antigen combos with **negative net
MFI** (specimen − mean background). The max-MFI (default 300, dashed line) and
the %CV thresholds are reference values — **formal Background pass/fail flagging
is still in development**.

### Negative control

NC wells (matching `Negative`) are tracked per antigen across plates, each
control kept separate. Because each control has only two wells, disagreement is
flagged by **duplicate %CV** (> `nc_cv_threshold`, default 25 %) with a focused
flag table, rather than a 2-SD outlier test. Deeper NC-level flagging is in
development.

## Output

All persistent data is stored under
`~/bangladesh-serosurveillance-luminex-qc-results/`:

```         
  reports/
    QC_<plate_id>.html              # interactive report
    results_<plate_id>.csv          # clean master (auto_select: single-pool tidy incl. pool + calibration tier; per_pool: RAU+status per pool)
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
in the default **auto_select** mode it's the tidy single matched-pool
table (one RAU + status per antigen); in **per_pool** mode it carries RAU
+ range status under **every** control pool (so each antigen's cholera /
dengue / typhoid pool RAU sit side by side, `NO_FIT` where a pool doesn't
calibrate it). The
`specimens`, `standard_curve_params`, `standard_curve_data`, and
`nc_levels` sheets follow.

## Settings

Editable on the Settings page (persisted to `config.yaml`):
well-classification patterns, **priority antigens** (curves shown in the
Summary/Overview; blank = the pathogen-priority set), the **pool mode**
(auto_select / per_pool) with scoring pool, regex rules and per-antigen
overrides, excluded analytes, bead-count thresholds, problem-fraction
threshold, background intra-plate %CV, **inter-assay %CV**, and max-MFI
reference thresholds, the **NC duplicate %CV** threshold, recovery tolerance,
the single-outlier drop toggle, and the (informational-only) specimen dilution.

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
