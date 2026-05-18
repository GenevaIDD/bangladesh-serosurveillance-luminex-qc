# Uvira 200-plex Luminex QC — To-Do & Session Log

Working document tracking the migration of the MPXV 12-plex MagPix QC app to a
200-plex Intelliflex assay (Uvira pilot). Keep the **To-Do** section as the
running plan and append a new entry under **Session History** at the end of
every working session.

---

## Project context (snapshot)

- **Instrument**: Intelliflex (replaces MagPix). xPONENT CSV format is similar
  but has an expanded `DataType:` set (Median, Mean, Count, %CV, Peak, Std Dev,
  Trimmed Peak / SD / Mean, Net MFI, Avg Net MFI, Units, Dilution Factor).
  Header lines differ: `"Program","xPONENT","","Intelliflex"`, `SN` like
  `IFLEXP23263001`, `PanelName` (e.g. `XXL_CORRECTED [v1]`), no per-row
  bead-number prefix on analyte names.
- **Plate format**: 96-well. Row A wells A1–A10 hold the 10-point 4-fold
  standard curve; A11–A12 are backgrounds/NC. B1 onward are specimens
  (barcodes like `FD22124871`). See `Pilot_Uvira_XXL/…_inputfile.csv` for the
  authoritative layout (`Location, Plate Type, Type, Description, Dilution`).
- **Standards**: pooled standard with mAbs. Pool composition:
  - Standards: Zika 16/352, Diphtheria 10/262, Hep B surface 07/164,
    Mpox MP-001 (in-house), P. vivax 19/198, Rift Valley 22/104BA,
    Rubella RUBI-1-94, Yellow Fever YF, HPV18 10/140.
  - mAbs: HylE, ctxB, OSP.
- **Dilution series** (from screenshot): mAbs pre-diluted 1:50, then 4-fold
  serial. Final dilutions for the Std+Mabs row:
  62.5, 250, 1000, 4000, 16000, 64000, 256000, 1024000, 4096000, 16384000.
  Well volume 5 µL. First dilution recipe: `5 µL MAbs + 11.8 PBT (+3.2 Stds
  pool)`; proceeding dilutions: `5 pool + 15 PBT`.
- **Antigen panel**: ~200 antigens listed in the Median header of
  `PlateRunResults_PLATE_05112026_RUN000.csv` (row 52). Includes families
  RES_, TOXO_, VPD_, HHV_, BAC_, OTH_, ENT_, HEP_, ARB_, STI_, MAL_, CHO_,
  CTRL_, NTD_, HCoV_, SARS_, TBD_, FLU_, POX_, HAN_.
- **Erroneous bead regions to flag/drop**:
  `FLU_B_HA_Maryland_1959`, `FLU_B_NP_Brisbane_2008`, `VPD_Tet_tox`.
- **Barcode → patient-ID maps**: 22 xlsx files in
  `Renamed_Uvira_Sera_2023_Barcode_maps/`. Each has a single sheet with
  columns `Container Id, Orientation Barcode, Row, Column, Barcode, Scan
  Time, Filename, Automatic Export Directory, ID` — the `Barcode` column
  matches the `Description` field of the inputfile; `ID` is the patient ID
  (e.g. `4033-93`).

## What the existing app already provides (reuse vs. replace)

| Capability | Reuse? | Notes |
|---|---|---|
| `parse_xponent.py` CSV parser | **Edit** | Works on MagPix shape; Intelliflex header keys differ slightly and there are more `DataType:` blocks. The `01 MVA Ag` numeric-prefix strip is a no-op here. Plate-ID extraction regex (`(.+-Plate\d+)`) won't match `PLATE_05112026_RUN000` → needs new rule. |
| `classify.py` PC/NC patterns | **Edit** | New sample names are `Standard1…Standard10`, `Background`, and `FD########` barcodes. Pool concept (`ITM PC` vs `ITM PC2`) does not apply — single pooled standard. |
| `qc_beads.py` (bead-count flag) | **Reuse + extend** | Already flags `count < min`. Needs the 3-tier (red/yellow/green) table the user requested, plus a problem-sample list. |
| `qc_standard_curve.py` 4PL fitting | **Reuse** | Per-antigen 4PL is the right shape; just runs over ~200 antigens × 1 pool instead of 8 × 2 pools. Add the "% samples in linear range" metric and a per-(antigen, sample) IN/OUT-of-range table. |
| `qc_kit_controls.py`, `qc_nc.py`, `qc_replicates.py` | **Defer / probably drop** | The new assay has no MagPix kit-control beads (NC/ScG/FC/IC bead regions); NC is the row-A backgrounds. PC replicate CV does not apply (single replicate per dilution point in row A). |
| `report.py` / `templates/report.html` | **Edit heavily** | Layout assumes 8 antigens (2×4 grids). Needs to scale to 200 (paginated / filterable / searchable). New bead-count table and IN/OUT-of-range table go here. |
| `config.py`, `settings.py` | **Edit** | Panel definition, kit-control list, default thresholds, well-classification patterns all hard-coded for 12-plex MPXV. |
| `parse_layout.py` | **Edit** | Currently reads a Geneva "Sample list" xlsx. New flow joins the Intelliflex `inputfile.csv` (well → barcode) with one of the Box barcode-map xlsx files (barcode → patient ID). |
| `qc_history.py` / per-pool history JSON | **Keep, simplify** | Drop the multi-pool slug logic; one history per assay. |

---

## To-Do

Status legend: `[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked.

### 0. Project setup
- [x] Create this tracking doc (`UVIRA_TODO.md`).
- [x] Decision: **single-mode app** — Uvira 200-plex Intelliflex only. The
      existing MPXV 12-plex MagPix code path will be removed. No assay
      selector; the pipeline replaces (not augments) the current one.
- [~] Strip MPXV-specific code. Done in Session 2: `MPXV_ANTIGENS` and
      `MPXV_KIT_CONTROLS` are now deprecated aliases for `ANTIGENS` / `[]`
      in `config.py` (kept as a shim so legacy `qc_*` / `report.py`
      modules still import cleanly until Sections 3–5). README, SPEC,
      `app.py`, `main.py`, and the three HTML templates rebranded.
      Outstanding: remove `qc_kit_controls.py` / `qc_nc.py` /
      `qc_replicates.py` entirely (Section 5), strip remaining MPXV
      copy from `report.py` and `templates/report.html` (Section 5),
      and update the legacy descriptive sections of README/SPEC
      (Section 7).
- [x] Rename app branding (window title, report title, settings page,
      results-dir name, download filenames, README/SPEC headers) from
      "MPXV Luminex QC" to "Uvira Luminex QC". Package import path
      stays `src/`. `RESULTS_DIR_NAME = "uvira-luminex-qc-results"` now
      lives in `config.py` and is consumed by `app.py` + `settings.py`.
- [x] Bumped `APP_VERSION` to `0.9.0-uvira`.

### 1. Data ingestion
- [x] Extend `parse_xponent.py` to handle Intelliflex headers. Captures
      `instrument_program` (MagPix / Intelliflex), `panel_name`,
      `batch_description`, `batch_stop_time`. Metadata scan now stops at
      the first `DataType:` row. Smoke-tested on
      `PlateRunResults_PLATE_05112026_RUN000.csv`: 200 analytes × 96
      wells parsed cleanly, batch / SN / panel name all captured. The
      existing `_strip_bead_prefix` regex is a no-op for unprefixed
      Intelliflex analyte names.
- [x] New plate-ID rule. `_extract_plate_id` falls back to the raw
      batch string when the legacy `-Plate\d+` regex doesn't match, so
      Intelliflex batches like `PLATE_05112026_RUN000` are used verbatim
      as the plate ID.
- [x] Replaced `parse_layout.py` with `read_inputfile_csv()`,
      `read_box_xlsx()`, and `build_layout()` (a unified well-level join
      that produces `well, plate_well_type, barcode, patient_id, box_id,
      source_row, source_col`). `read_plate_layout()` retained as a
      backward-compat wrapper. Smoke-tested on the pilot data: 84/84
      specimens get a patient ID; the 12 control wells correctly have
      empty barcodes.
- [x] Extended the Flask upload form to accept three files (plate CSV
      [required], inputfile CSV [optional but recommended], Box xlsx
      [optional]). All three are persisted to `uploads/` and tracked in
      `plate_registry.json` (new `inputfile_filename` field) so
      Regenerate-All works without re-upload. `run_pipeline` now takes
      `inputfile_path`; when provided it routes through `build_layout`
      and writes `sample_id` (patient_id if known, else barcode),
      `barcode`, `patient_id`, `box_id` onto each row.
- [ ] **Soft-flag** the three erroneous bead regions
      (`FLU_B_HA_Maryland_1959`, `FLU_B_NP_Brisbane_2008`, `VPD_Tet_tox`):
      keep them in all tables/plots but render them visually muted (grey
      row, italic label, "(excluded)" suffix) and surface the list in a
      report banner. Do **not** drop them from the data. **Data side
      done** — `EXCLUDED_ANALYTES` and `panel.excluded_analytes` are in
      `config.py` and exposed via `get_excluded_analytes()` in
      `settings.py`. **Render side pending** until Section 5
      (report.py rewrite).

### 2. Config & panel definition
- [x] Replaced `MPXV_ANTIGENS` / `MPXV_KIT_CONTROLS` with the 200 Uvira
      antigens (`ANTIGENS` constant in `config.py`). Old names retained
      as deprecated aliases.
- [x] Panel auto-derived from each CSV's Median-block header on
      ingest. `parse_xponent_csv` records `metadata['analytes']`;
      `pipeline.py` passes that list as the authoritative panel into
      `fit_standard_curves(antigens=...)`. Config panel is now a
      display-only fallback.
- [x] `excluded_analytes` is editable from the Settings page (textarea,
      one analyte per line). Defaults to the three erroneous bead
      regions. Surfaced on the per-(antigen × sample) range table via
      the `excluded` column.
- [x] Updated `well_classification` patterns to `^Standard\d+$` /
      `^Background`.
- [x] Standard dilution series baked into defaults (10-point 4-fold
      from 62.5 → 16,384,000); editable on the Settings page as a
      single comma-separated field (the old auto/manual mode toggle was
      removed because Intelliflex never encodes dilutions in sample
      names).

### 3. Standard-curve QC (200 antigens)
- [x] Existing 4PL per-antigen fit reused. `fit_standard_curves` now
      takes an `antigens` kwarg so the pipeline passes the per-plate
      panel from the CSV header. Pool concept collapses to a single
      `"PC"` key on Uvira (the multi-pool branch is unused but kept
      for backward compat).
- [x] **New metric** `compute_pct_in_range_per_antigen(in_range, ...)`
      returns one row per analyte with `n_samples / n_in_range /
      n_out_of_range / n_no_fit / pct_in_range / excluded`. Exported
      as `pct_in_range_<plate>.csv`.
- [x] **New table** `compute_in_range_table(data, fits, excluded)`
      returns one row per (specimen well × analyte) with `mfi /
      mfi_lloq / mfi_uloq / status / excluded` plus any sample-id /
      barcode / patient-id columns from the layout merge. Status is
      strictly `IN_RANGE` / `OUT_OF_RANGE` / `NO_FIT`; below-LLOQ and
      above-ULOQ both collapse to OUT_OF_RANGE per decision #3.
      Exported as `in_range_<plate>.csv`. Smoke-test on the pilot data:
      16,800 rows (84 specimens × 200 antigens), the three excluded
      bead regions came back at 0–3.6% in-range as expected.
- [x] Curve-plot picker shipped — single Plotly figure with all 200
      antigens as visibility-toggled traces and a dropdown menu (Section 5).

### 4. Bead-count QC
- [x] **New table** built in `qc_beads.py::qc_bead_counts`. Returns
      `matrix` (analytes × wells, raw counts), `tier_matrix` (red /
      yellow / green strings), and a `problems` long-format DataFrame
      sorted red-first. Rendered in the report as a discrete-tier
      Plotly heatmap.
- [x] **Problem list** included as an HTML table below the heatmap and
      exported as `bead_problems_<plate>.csv` from the pipeline.
- [x] Threshold pair wired through Settings (`bead_count_min` /
      `bead_count_warn`) and into the Plotly heatmap legend.

### 5. Reporting & UI
- [x] `templates/report.html` and `src/report.py` rewritten from
      scratch for the 200-antigen layout. Removed all kit-control / NC
      bead / replicate-CV sections. Plotly is loaded via CDN once.
- [x] Bead-Count matrix + IN/OUT-of-Range matrix, both as Plotly
      heatmaps with discrete colour scales and per-cell hover.
- [x] Standard-Curve Picker — Plotly figure with 200 traces and an
      `updatemenus` dropdown that swaps the visible analyte. Title
      updates with `fit_ok` and the four 4PL parameters.
- [x] Per-antigen Standard-Curve Summary table (a, b, c=IC50, d, LLOQ
      / ULOQ dilutions, %-in-range, QC warnings, `fit_ok` badge).
      Excluded-analyte rows rendered muted.
- [x] Banner sections: excluded analytes (warn-yellow); Box xlsx
      identifier and patient-ID resolution count (info-blue).
- [x] Specimen-results table not embedded — 200 cols × 84 rows would
      blow up the page. Three CSV download buttons replace it
      (`specimens_*.csv`, `in_range_*.csv`, `pct_in_range_*.csv`).

### 6. Validation
- [ ] End-to-end run on `Pilot_Uvira_XXL/`. Confirm report opens, all 200
      antigens render, the 3 erroneous beads are flagged, bead-count matrix
      and IN/OUT-of-range matrix populate correctly.
- [ ] Cross-check a handful of patient IDs against
      `RENAMED-Box1_Uvira_sera_2023.xlsx`.

### 8. Usability + cross-plate features (Session 6+)

User requests (2026-05-18) after reviewing the first end-to-end Uvira
report:

- [x] **Report navigation.** Sticky left sidebar with section links
      (TOC) plus per-section `<details>` collapse. Done Session 6.
- [x] **Bead-Count Matrix — summary cards** + downloadable
      `bead_problem_antigens_<plate>.csv` /
      `bead_problem_samples_<plate>.csv`. Threshold shared across
      bead + range summaries (Settings: `problem_fraction_threshold`,
      default 0.20). Done Session 6.
- [x] **Bead-Count Matrix — group separators.** Dotted vertical
      lines between Standards / Background / NC / specimen columns,
      derived from `well_type`. Done Session 6.
- [x] **Standard-Curve summary cards** + downloadable
      `range_problem_antigens_<plate>.csv` /
      `range_problem_samples_<plate>.csv`. Four cards: antigens
      below / above + samples below / above. Done Session 6.
- [x] **Curve Picker — rug plot.** Right-edge specimen MFI ticks
      colored by BELOW_RANGE / IN_RANGE / ABOVE_RANGE / NO_FIT, plus
      a grey rug for historical-plate specimens. New
      `specimen_mfi_history.json` persists per (plate, well, analyte).
      Done Session 8.
- [x] **Curve Picker — historical curves.** Grey dotted overlays of
      every previous plate's 4PL, sourced from
      `fit_history_<pool>.json`. Done Session 8.
- [x] **Range Matrix — CB-friendly recolor.** Palette: BELOW =
      #4477AA blue, IN = #44AA99 teal, ABOVE = #EE7733 orange,
      NO_FIT = #CCBB44 yellow (Paul Tol / Okabe-Ito). Grey reserved
      for the historical overlays now. Done Session 6.
- [x] **Background QC.** New `qc_background.py` module computing
      `n_wells`, `mean_mfi`, `sd_mfi`, `cv`, `max_mfi`, `cv_flag`,
      `max_flag` per antigen. Renders as the Background QC section
      with summary cards and a per-antigen table; exported as
      `background_qc_<plate>.csv`. Settings:
      `bg_cv_threshold` (default 0.25 = 25%), `bg_max_mfi`
      (default 100). Done Session 6.

### 7. Packaging & docs
- [x] `README.md` rewritten end-to-end for the Uvira 200-plex /
      Intelliflex assay. Done Session 9.
- [x] `SPECIFICATION.md` rewritten end-to-end. Done Session 9.
- [x] PyInstaller specs renamed `mpox-luminex-qc{,-win}.spec` →
      `uvira-luminex-qc{,-win}.spec`. Product name, bundle id, and
      hiddenimports list refreshed (legacy `qc_kit_controls`,
      `qc_replicates` dropped; `qc_background` added; matplotlib
      added since the small-multiples curve grid needs it).
      Done Session 9.
- [x] GitHub URL in `templates/web/index.html` swapped to
      `GenevaIDD/uvira-luminex-qc`. Done Session 9.
- [x] Legacy `scripts/generate_test_data.py` (MagPix 12-plex MPXV
      synthetic data, no longer referenced) deleted. Done Session 9.
- [ ] **Actually build** the macOS `.app` (and Windows `.exe` on a
      Windows machine) with the renamed specs; sign the macOS bundle
      with `codesign --force --deep --sign -`. Defer until a real
      release is needed.

---

## Decisions log

| # | Decision | Date |
|---|---|---|
| 1 | ~~Dual-mode app~~ **Reversed**: single-mode Uvira 200-plex Intelliflex; MPXV 12-plex MagPix path will be removed. | 2026-05-13 |
| 2 | Excluded bead regions are **soft-flagged** (rendered muted, never dropped). | 2026-05-13 |
| 3 | ~~Strictly binary IN/OUT-of-range~~ **Reversed** in Session 5: split into BELOW_RANGE / IN_RANGE / ABOVE_RANGE (plus NO_FIT). | 2026-05-13 / 2026-05-18 |
| 4 | Barcode-map workflow: **manual upload** at submit time (no auto-matching by filename / BatchDescription). | 2026-05-13 |
| 5 | Background and NC are **separate** well types. `^Background` = plate blank (A11/A12); `^NC` / `^Negative` = the QC'd negative-control sample (not present on the pilot plate). | 2026-05-18 |
| 6 | NC QC follows the legacy MPOX behaviour: render NC MFI per (well × antigen) as a heatmap, **no automatic flagging**. Threshold logic deferred. | 2026-05-18 |
| 7 | Report navigation: **sticky left sidebar** with section links + collapsible sections. | 2026-05-18 |
| 8 | One **shared `problem_fraction_threshold`** (default 0.20) drives all the "≥X% problematic" summary counts. | 2026-05-18 |
| 9 | Curve-picker historical overlays show **all** prior plates (no N-most-recent cap). | 2026-05-18 |
| 10 | Background QC runs **mean + %CV + max-MFI flag** per antigen — all three legacy MPOX metrics, applied to Background wells when no NC is present. | 2026-05-18 |

## Open questions for the user

_None at the moment._ All four initial questions are resolved (see
Decisions log).

---

## Session History

### Session 9 — 2026-05-18 (Section 7: docs + packaging)

Closed out the long-running Section 7 — the migration's
documentation, packaging, and stray-reference cleanup. The
codebase is now self-consistently "Uvira 200-plex Intelliflex"
from `pyproject.toml` to the report footer.

**Files edited:**
- `README.md` — full rewrite. Drops the "migration in progress"
  banner and the MPXV 8-antigen / 4 kit-control table; introduces
  the Uvira 200-antigen panel by family prefix; describes the new
  QC stack end-to-end (`fit_ok` criteria, four-status range
  classification, summary thresholds, Background QC, NC QC); lists
  every per-plate CSV; updates the GitHub clone URL, app names
  (`Uvira Luminex QC.app`), and PyInstaller commands.
- `SPECIFICATION.md` — full rewrite. New "Plate Layout" section
  describes the Intelliflex / Uvira convention (Standard1–10 in
  A1–A10, Background in A11–A12, named NC patterns separate);
  documents the 200-antigen auto-derivation from the CSV header,
  the three soft-flagged excluded analytes, the four-status range
  table, the Background QC module, and the cross-plate JSON
  history files. Section "Reports" updated to match the current
  nine-section sidebar layout.
- `mpox-luminex-qc.spec` → **`uvira-luminex-qc.spec`** (macOS) and
  `mpox-luminex-qc-win.spec` → **`uvira-luminex-qc-win.spec`**.
  Product name `Uvira-Luminex-QC`, bundle name `Uvira Luminex QC.app`,
  bundle identifier `ch.unige.uvira-luminex-qc`. Hiddenimports
  refreshed: dropped `src.qc_kit_controls` and `src.qc_replicates`
  (deleted in Session 4); added `src.qc_background` (added in
  Session 6); added `matplotlib`, `matplotlib.pyplot`, and
  `matplotlib.backends.backend_agg` since `_make_curve_grid`
  renders the small-multiples PNG via Matplotlib at report time.
  Removed `matplotlib` from the spec's `excludes` list.
- `templates/web/index.html` — footer GitHub URL swapped from
  `GenevaIDD/mpox-luminex-qc` → `GenevaIDD/uvira-luminex-qc`.
- `scripts/generate_test_data.py` — **deleted**. The script
  fabricated MagPix-shape 12-plex MPXV CSVs. Nothing references it
  anymore (no imports, no callers in README / SPEC / pyproject /
  app code), and Uvira testing uses the real pilot CSV.

**Smoke tests:**
- `grep -r 'mpox\\|MPXV\\|MagPix\\|12-plex' --include='*.md'
  --include='*.html' --include='*.spec' --include='*.toml'` — only
  legitimate explanatory references remain (README/SPEC mention the
  MagPix CSV header is still supported as a parser fallback; SPEC
  notes the MagPix-era `ITM PC / ITM PC2` pool concept that is no
  longer used on Uvira but whose dict structure is preserved
  internally). Confirmed clean otherwise.
- Both renamed `.spec` files parse as Python (`ast.parse`).
- Re-ran the full pipeline on `Pilot_Uvira_XXL/`. Report at 14 MB,
  every per-plate CSV emitted, no regressions.

**Remaining for Session 10:**
- Section 6 validation patient-ID spot-check (still open).
- Actually build the macOS `.app` and Windows `.exe` with the
  renamed specs when a release is needed.

### Session 8d — 2026-05-18 (picker UX iteration on the subplot)

User feedback on the Session-8c subplot picker, in order:

1. **Status-name annotations were overlapping** with each other and
   with the bottom x-axis tick labels (panel too narrow at 30%).
2. **Single-column rug**: the four BELOW / IN / ABOVE / NO_FIT status
   columns collapsed into a single "This plate" column with statuses
   stacked and colour-coded. The Past column stays as its own column.
   Percentages moved into a single multi-line summary text block.
3. **Rug too wide / summary blocked the curve**: rug narrowed
   further; summary pinned to the upper-right of the curve panel
   instead of upper-left.
4. **Legend too wide**: legend font shrunk and plate labels switched
   to a date-formatted short form for the legend (full label kept in
   hover + title).
5. **Status-count annotations weren't updating across antigens**:
   intro copy was stale (still talked about per-column updates after
   they had been collapsed) AND the JS used the undocumented merge
   behaviour of `Plotly.update`'s layout-update bag, which doesn't
   reliably replace the annotations array.

**Files edited:**
- `src/report.py::_make_curve_picker`
  - `column_widths` 0.78/0.22 → 0.70/0.30 → 0.82/0.18, final
    `horizontal_spacing=0.04`. Right margin trimmed 220 → 180 px to
    let the legend sit closer to the rug.
  - `RUG_X` table now puts **every** current-plate status at x=0 and
    the past column at x=1. Rug subplot range `[-0.5, 1.5]` (or
    `[-0.7, 0.7]` when there are no past plates). Dotted vertical
    separator at x=0.5 marks the boundary.
  - Rug subplot's bottom x-axis hidden (`showticklabels=false`,
    `showline=false`, no title, no grid). Column labels are the only
    things above the rug now.
  - `_rug_annotations(an)` returns three items: a multi-line summary
    text block (paper-anchored to upper-right of curve subplot, at
    `x=0.77, y=0.99, xanchor="right"`) listing the four status
    counts and percentages, plus "This plate" / "Past · N plates"
    column headers above the rug subplot in `x2` data coords.
  - Summary text block has white background + light border so it
    overlays cleanly on top of the gridlines.
- `src/report.py::_short_plate_label` (new) — extracts the date and
  run number from `PLATE_<MMDDYYYY>_RUN<NNN>` and emits
  `MM/DD/YYYY · R<N>` (+ ` · Box<N>` when a box xlsx is attached).
  Used for legend entries and the current-plate trace name; the full
  `_plate_label` is still used for hovers and the figure title.
- `src/report.py` legend layout — font size 11 → 10, title
  "Plates · click to toggle" in 10 pt grey, `tracegroupgap=2`,
  `itemsizing="constant"`.
- `src/report.py` JS shim — switched from one `Plotly.update(div,
  data, layout)` call to three explicit calls per antigen pick:
  `Plotly.restyle(div, {visible: …})`, then
  `Plotly.relayout(div, "title.text", …)`, then
  `Plotly.relayout(div, "annotations", …)`. The 3-arg `relayout`
  path form is the documented way to wholesale-replace a layout
  array; the previous bag form was relying on undocumented merge
  behaviour and silently kept the first analyte's annotations.
- `templates/report.html` Standard-Curve Picker intro fully
  rewritten to describe the new two-column rug, the
  upper-right status-count box, and the legend toggle behaviour. The
  earlier "count and percentage above each status column update as
  you switch antigens" sentence was stale and is gone.

**Smoke tests:**
- Pilot run: report at 14 MB. Layout uses `n_per_analyte = 6` (no
  past plates). Summary text shows `This plate · 84 specimens` with
  the four colour-coded status counts.
- Synthesised three plates (Box1 attached to all; Plate B specimens
  scaled +25%, Plate C scaled −25%):
  - Plate C report has 200 lookup entries, each with 3 annotations.
    110 distinct count vectors across the 200 antigens — confirms
    the per-antigen percentages do differ.
  - JS shim now uses
    `Plotly.relayout("fig-curve-picker", "annotations", entry.annotations)`
    (verified by grep).
  - Legend entries read e.g. `01/01/2026 · R0 · Box1` (short form);
    hover tooltip still shows
    `PLATE_01012026_RUN000 · Box1` (full form).

**Carry-over to Session 9:** unchanged.

### Session 8c — 2026-05-18 (curve-picker subplot + status columns)

Promoted the rug from an overlay on the curve to a dedicated subplot
panel, added per-status count + percentage annotations, and labelled
plates by `plate_id · Box{N}` everywhere they appear.

**Files edited:**
- `src/report.py` —
  - New `_plate_label(plate_id, box_ids)` helper. Handles the
    comma-string format used in history files and the list format
    used by the live `layout_info` dict. Shortens long Container Id
    values (e.g. `Box1_Uvira_sera_2023`) to the leading `Box\d+`
    portion via `_BOX_SHORT_RE`; falls back to the raw string when
    no `Box\d+` prefix is present.
  - `_hist_fits_by_analyte` now carries `box_ids` per past plate so
    the legend can compose `plate_id · Box{N}` without an extra
    lookup.
  - `_make_curve_picker` rebuilt around `plotly.subplots.make_subplots`
    (`column_widths=[0.78, 0.22]`, `shared_yaxes=True`):
    - **Left panel**: standards + current 4PL + grey historical 4PL
      curves (one trace per past plate).
    - **Right panel**: rug with categorical x-axis. Tick positions
      0–3 = BELOW / IN / ABOVE / NO_FIT for the current plate;
      tick position 5 = `Past` for all historical specimens.
      Position 4 left empty so a dotted vertical separator
      (paper-y shape) cleanly divides current from historical.
    - Above each of the four status columns sits a layout
      annotation: `BELOW`/`IN`/`ABOVE`/`NO FIT` (status colour) +
      `n (pct%)` underneath, computed from this plate's
      `in_range` for the selected antigen.
    - Annotations swapped via `Plotly.update("…annotations": …)`
      when the typeahead changes antigen. Subplot titles preserved
      across switches by keeping them as the first two entries of
      the annotation array.
- `src/pipeline.py` —
  - `_build_specimen_mfi_history` now carries `box_id` from
    `in_range` into the JSON, so the past-plate legend label can
    look it up later.
  - `_build_fit_history` accepts a new `box_ids=` kwarg (joined
    comma-string of all boxes on the plate). `run_pipeline` derives
    it from `data["box_id"]` before the call.

**Smoke tests:**
- Pilot run: report at 14 MB, subplot scaffolding present
  (`"Specimen MFI rug"` subplot title), 4 rug status ticks, no
  past-plate traces (P = 0).
- Three synthesised plates (`PLATE_01012026_RUN000` /
  `PLATE_02152026_RUN000` / `PLATE_03102026_RUN000`, all attached
  to `Box1`, second plate scaled +25%, third scaled −25%):
  - Plate 3's report shows the two prior plates as legend entries
    labelled `PLATE_01012026_RUN000 · Box1` and
    `PLATE_02152026_RUN000 · Box1`. Current 4PL legend reads
    `This plate (PLATE_03102026_RUN000 · Box1)`.
  - Per-antigen annotation block carries 4 status entries; first
    annotation text is `<b style='color:#4477AA;'>BELOW</b>
    <br><span style='font-size:10px;color:#34495e;'>{n} ({pct}%)</span>`
    confirming the swap structure.
  - Legend toggle still works: clicking a past plate hides both
    its 4PL trace (left subplot) and its rug points (right
    subplot) because they share `legendgroup="plate:<plate_id>"`.

**Carry-over to Session 9:** unchanged from 8b.

### Session 8b — 2026-05-18 (curve-picker refinements)

Three follow-ups on the Session-8 rug + historical overlay:

1. **Rug overlap.** Bumped `rug_x_current` to `x_max × 2.0` and
   `rug_x_hist` to `x_max × 2.6` (was 1.18 / 1.27). Added an explicit
   x-axis `range=[log10(x_min × 0.7), log10(x_max × 3.5)]` so the rugs
   render in the padded area and never clip. Right margin grew from
   30 px → 220 px to accommodate the legend.
2. **Z-order.** Trace slot order rewritten: historical curves
   (`[0 .. P-1]`), historical rugs (`[P .. 2P-1]`), then current
   standards / fit / 4 status rugs (`[2P .. 2P+5]`). Plotly draws in
   addition order, so historical now sits behind the live overlay.
3. **Per-plate legend toggling.** Each past plate gets a single
   legend entry (one curve trace shown in the legend, its rug trace
   hidden but sharing `legendgroup="plate:<plate_id>"`). Clicking the
   legend entry hides every overlay for that plate across every
   antigen; double-click isolates. `plot_layout.legend.title` reads
   "Plates (click to toggle)" when ≥1 past plate is present.

**Files edited:**
- `src/report.py::_make_curve_picker` — full rewrite of trace order
  and per-plate slot allocation. New `past_plates` roster computed
  once (chronological by `run_date` when available) and used for
  every analyte. `n_per_analyte = 2P + 6`; layout call passes the
  padded x range and the new `legend_layout` dict.
- `templates/report.html` — picker intro adds the legend / double-
  click instruction and a short note explaining that history is per
  output directory (first plate has no grey overlay; subsequent
  plates accumulate).

**Smoke tests:**
- Pilot (no past plates): 15 MB report. Layout uses `n_per_analyte =
  2×0 + 6 = 6`. Legend shows the current-plate entries only ("This
  plate (PLATE_05112026_RUN000)", "Standards").
- Synthesised three plates A → B → C (B scaled +20%, C scaled −20%
  on specimens). Plate C's report contains 400 trace references
  each for PLATE_A and PLATE_B (200 analytes × 2 slot kinds per
  past plate), `legendgroup="plate:PLATE_A"` (and B) populated, and
  the legend-title string is present. Verified Plate C's grey
  overlays sit behind the blue current curve and the current-plate
  rug column doesn't overlap the rightmost standard point.

**Workflow note** (added to the picker intro): history is per
output directory — the first plate has no grey overlay; every
subsequent plate processed into the same directory becomes a
toggleable legend entry. To start fresh, delete the corresponding
`history/` subdirectory.

### Session 8 — 2026-05-18

Curve-picker rug + cross-plate overlays — the deferred Session-7
follow-up. The picker now shows where the current plate's specimens
sit on the y-axis (colored by BELOW / IN / ABOVE / NO_FIT), plus
prior-plate specimens and curves in grey so drift across runs is
visible without flipping between reports.

**Files edited:**
- `src/pipeline.py` —
  - New helper `_build_specimen_mfi_history(metadata, in_range)`.
    One row per (`plate_id`, `well`, `analyte`) with `mfi` and
    `status` from the current run. Drops NaN MFI rows.
  - `run_pipeline` reads / appends / writes
    `<history_dir>/specimen_mfi_history.json`, dedup key
    `[plate_id, well, analyte]`. `history_specimens` flows through
    to the report whether or not the current plate contributed
    rows (so prior plates still render after a no-NC-no-spec run).
  - `generate_report` call now also passes `history_fit`
    (already loaded earlier in the pipeline for `fit_history_PC.json`).
- `src/report.py` —
  - `generate_report` signature gains `history_fit=` and
    `history_specimens=` keyword args.
  - New `_hist_fits_by_analyte(history_fit, current_plate_id)`
    flattens the per-pool DataFrame into
    `{analyte: [{plate_id, params: (a, b, c, d)}, …]}` and excludes
    the current plate.
  - `_make_curve_picker` rewritten. Fixed `TRACES_PER_ANALYTE = 8`
    slot layout per analyte so the typeahead visibility array
    stays dense and predictable:
    - 0 — current standards (markers)
    - 1 — current 4PL fit (blue line)
    - 2–5 — current specimens, one rug trace per
      BELOW_RANGE / IN_RANGE / ABOVE_RANGE / NO_FIT status,
      colored from the CB-safe range-matrix palette
      (#4477AA / #44AA99 / #EE7733 / #CCBB44)
    - 6 — historical specimens rug (grey, plate name in hover)
    - 7 — historical 4PL curves (grey dotted line; all prior
      plates concatenated with `None` segment breaks).
  - Rugs sit at `x = max(std_dilution) × 1.18` (current) and
    `× 1.27` (historical) so the two columns are visually
    distinct on the log axis.
  - Typeahead lookup updated to flip all 8 slots per analyte
    instead of just 0–1; initial visibility likewise.
- `templates/report.html` — Standard-Curve Picker intro rewritten
  to introduce the two rugs and the grey-historical convention,
  with inline badges showing each status colour.

**Smoke tests:**
- Pilot plate (fresh history): `specimen_mfi_history.json` written
  (3.5 MB, 16,800 rows = 84 specimens × 200 antigens). HTML at
  15 MB (was 12 MB) — extra trace bookkeeping. 800 status-rug
  traces in JSON (200 antigens × 4 statuses); 200 "Past plates"
  + 200 "Past curves" traces (empty for the first plate; non-empty
  on subsequent runs).
- Synthesised two plates (`HIST_A`, `HIST_B`, scaled Plate B's
  specimen MFI by 1.3×) by monkey-patching `parse_xponent_csv`:
  - After Plate A: history file has 16,800 rows / 1 plate.
  - After Plate B: history file has 33,600 rows / 2 plates.
  - Plate B's report contains "Past plates" + "Past curves" trace
    names; the embedded JSON contains 16,800 `HIST_A`
    references inside Past-plate `customdata` arrays.
  - Past curves rendered as grey dotted lines; current curve still
    blue. Past specimens as grey ticks slightly outside the
    current-plate rug column.

**Carry-over to Session 9:**
- Section 6 validation patient-ID spot-check.
- Section 7 (original): rewrite README / SPEC for the Uvira
  assay, rename PyInstaller specs, update GitHub URLs in
  templates / footer / README.

### Session 7b — 2026-05-18 (continuation)

Small follow-up: ported the legacy MPOX cross-plate NC history so that
when a future plate has a named NC sample, drift across runs is
visible in the report.

**Files edited:**
- `src/pipeline.py` —
  - New helper `_build_nc_history(metadata, nc_levels)` returns one
    row per (`plate_id`, `well`, `analyte`) with the NC well's MFI.
  - `run_pipeline` now loads `<history_dir>/nc_well_history.json`,
    appends the current plate's NC rows (dedup on
    `[plate_id, well, analyte]` via `append_history`), and saves
    back. When the current plate has no NC wells the existing
    history is still loaded and passed through so the report can
    show prior plates.
  - `history_nc` now flows through to `generate_report` as a
    `DataFrame` instead of `None`.
- `src/report.py` — new `_make_nc_history_plot(history_nc,
  current_plate_id)`: aggregates to per-(plate × analyte) mean MFI
  and renders a Purples heatmap. Plates ordered by `run_date` when
  present; the current plate gets a `(current)` suffix on its row
  label. Empty / no-history → empty string, template hides the
  subsection. Wired into `generate_report` via `nc_history_html` and
  `nc_history_present`.
- `templates/report.html` — added an "NC MFI across plates"
  subsection inside the NC QC section, rendered only when
  `nc_history_present`. NC explainer banner gained a fifth bullet
  noting that NC MFI is persisted to a cross-plate history JSON.

**Smoke tests:**
- Real pilot plate (no NC wells): JSON not written; history section
  correctly hidden in the report. No regression.
- Synthesised two test plates (`TEST_PLATE_A`, `TEST_PLATE_B`) by
  monkey-patching `parse_xponent_csv` to relabel `A11` as
  `NC_pool` and to inject a small drift on RES_* antigens for
  Plate B. After two runs:
  - `nc_well_history.json` contains 400 rows (200 antigens × 2
    plates), no duplicates.
  - Plate B's report contains "NC MFI across plates",
    `fig-nc-history`, `TEST_PLATE_A`, and `TEST_PLATE_B (current)`.
  - The injected drift surfaces as a per-plate mean MFI bump
    (132.4 → 141.4 across the panel).

### Session 7 — 2026-05-18

Polish pass on the Session-6 report.  Several rounds of user feedback
on copy clarity, section order, and the curve picker UI.

**Files edited:**
- `src/report.py` —
  - `_make_bead_heatmap` group separators now drawn as
    `add_shape(yref="paper", y0=0, y1=1.08)` so the dotted lines
    extend above the heatmap into the x-tick label band instead of
    stopping at the plot edge.
  - `_make_curve_picker` rewritten: the Plotly `updatemenus` dropdown
    was removed entirely (it duplicated the new typeahead). An HTML5
    `<datalist>`-backed `<input>` sits above the figure; a tiny JS
    shim reads a per-antigen `{vis, title}` lookup and calls
    `Plotly.update("fig-curve-picker", …)` on `change`/`input`. The
    lookup is embedded as a JS object literal with `</` escaped, so
    nothing leaks out of the `<script>` block.
- `templates/report.html` —
  - **Section reorder.** New order: Plate Overview → Negative
    Control QC → Background QC → Bead-Count Matrix → Standard-Curve
    Summary → All Curves Overview → Standard-Curve Picker → Range
    Matrix → Downloads. NC + BG QC moved up from the bottom; sidebar
    TOC mirrors the new order.
  - "Negative-Control Levels" renamed to **Negative Control QC**.
  - Every top-level `<details class="section">` now has the `open`
    attribute by default.
  - Sidebar JS at end of `<body>`: listens for `<nav.sidebar a>`
    clicks + `hashchange` and force-opens the targeted `<details>`,
    then smooth-scrolls to it. Section nav always lands on visible
    content even if the user has manually collapsed something.
  - **Bead summary cards** split into four cards with consistent
    typography (Antigens flagged / Specimens flagged / Red cells /
    Yellow cells), each with a one-line subtitle naming the criterion.
  - **Range summary cards moved** from "All Curves Overview" into
    "Standard-Curve Summary" (the natural home — the summary table is
    right there).
  - New **"What does Fit OK mean?"** banner in Standard-Curve Summary
    listing all four pass criteria (R² ≥ 0.95 on log10, IC50 inside
    the tested dilution range with ±3× margin, Hill slope 0.3–5.0,
    dynamic range ≥ 3×).
  - New **"How Background QC works"** banner in Background QC
    explaining Mean / %CV / Max checks in plain English, with the
    live `bg_cv_pct` and `bg_max_mfi` thresholds inlined.
  - **Downloads section reorganised**. Buttons grouped by section
    (NC QC → Background QC → Bead-Count Matrix → Standard-Curve
    Summary → Range Matrix → Specimens cross-cutting), one row per
    button with a plain-English description of the CSV's contents.
    NC group only renders when the plate has NC wells. Added the
    long-form `bead_problems_*.csv` button that was previously
    missing from the page.
  - Curve-picker introductory copy updated: "Pick an antigen either
    by typing in the search box (with autocomplete) or via the
    dropdown menu above the plot." → "Pick an antigen by typing in
    the search box (with autocomplete)."

**Smoke tests:**
- Full pipeline ran cleanly on `Pilot_Uvira_XXL/`. Report at
  ~12 MB. Section-order grep confirmed Plate Overview → NC QC →
  Background QC → Bead-Count → … → Downloads in that order. No
  duplicate `sec-nc` / `sec-bg` blocks. Sidebar JS present
  (`openTarget` defined, click + `hashchange` listeners wired).
  All five `<h4>` Downloads groups render in section order.
- Typeahead manually tested: typing a partial name pops the
  matching analyte via the datalist; selection triggers
  `Plotly.update` and the figure swaps to that analyte's curve
  + standards. No matching name shows a "no match" hint instead
  of breaking. Dropdown is gone from the picker layout (the lone
  remaining `updatemenus` string in the HTML is inside the
  embedded plotly.js bundle, not our figure).

**Known follow-ups (closed in Session 8 unless noted):**
- ~~Curve-picker rug plot~~ — done Session 8.
- ~~Historical curves + rugs in grey~~ — done Session 8.
- ~~Specimen-MFI history JSON~~ — done Session 8.
- Section 6 validation patient-ID spot-check (still open).
- Section 7 (the original): rewrite README / SPEC, rename
  PyInstaller specs, update GitHub URLs in templates / footer
  (still open).

### Session 6 — 2026-05-18

User-driven usability pass on the Session-5 report.  Most of Section 8
landed; the historical-overlay items (curve picker rug + grey
historical curves) are explicitly deferred to Session 7.

**Files added / edited:**
- `src/config.py` — new `PROBLEM_FRACTION_THRESHOLD = 0.20`,
  `BG_CV_THRESHOLD = 0.25`, `BG_MAX_MFI = 100`. Surfaced through
  `DEFAULTS["qc_thresholds"]`. `well_classification.background_patterns`
  added.
- `src/qc_background.py` (new) — `qc_background_levels(df, cv_threshold,
  max_mfi_threshold, excluded_analytes)` returns per-antigen
  `n_wells / mean_mfi / sd_mfi / cv / max_mfi / cv_flag / max_flag /
  excluded`.
- `src/qc_beads.py` — added `bead_problem_summary(bead_qc, well_types,
  fraction_threshold)`. Returns per-antigen and per-sample summaries
  (count + list of problem wells / analytes). Sample summary counts
  only specimens (Standards / Background / NC excluded from the
  denominator).
- `src/qc_standard_curve.py` — added `range_problem_summary(in_range,
  fraction_threshold, excluded_analytes)`. Returns four counts
  (antigens below / above; samples below / above) plus the detail
  rows for each axis.
- `src/report.py` —
  - Imported the two new helpers + `qc_background_levels`.
  - `generate_report` now computes summaries, formats them via
    `_format_bead_summary`, `_format_range_summary`,
    `_format_bg_levels`, and passes everything through.
  - `_make_in_range_heatmap` recoloured to a CB-safe four-stop scale
    (BELOW = #4477AA, IN = #44AA99, ABOVE = #EE7733, NO_FIT =
    #CCBB44). Grey reserved for historical overlays.
  - `_make_bead_heatmap` now takes `well_types=` and draws dotted
    vertical lines between well-type groups via `_group_boundaries`.
- `src/pipeline.py` — computes the three new summaries (bead, range,
  background) and exports five new CSVs:
  `bead_problem_antigens_<plate>.csv`,
  `bead_problem_samples_<plate>.csv`,
  `range_problem_antigens_<plate>.csv`,
  `range_problem_samples_<plate>.csv`,
  `background_qc_<plate>.csv`.
- `templates/report.html` — full body rewrite. Two-column layout with
  a sticky `<nav class="sidebar">` TOC plus a `<main class="content">`
  containing nine `<details class="section">` blocks (one per section),
  all collapsible. New `.stat-row` / `.stat` summary cards at the top
  of the bead-count, all-curves, and background sections. New
  `badge-r-below / -r-in / -r-above / -r-nofit` CSS classes matching
  the recoloured heatmap. New section: **Background QC** (between NC
  and Downloads), with three summary cards and a per-antigen table
  (n wells / mean / SD / %CV / max / flags). Downloads section
  expanded with the five new CSV buttons.
- `templates/web/settings.html` — added Background pattern field
  separately from NC; added `problem_fraction_threshold`,
  `bg_cv_threshold`, `bg_max_mfi` inputs.
- `src/app.py::save_settings` — parses `background_patterns` and the
  three new thresholds.

**Smoke test on `Pilot_Uvira_XXL/`:**

Full pipeline ran clean. Report at 12.3 MB. Output:
- `bead_problem_antigens_*.csv` (200×7): 7 antigens flagged
  (≥ 20% of wells problematic).
- `bead_problem_samples_*.csv` (84×8): 6 specimens flagged
  (≥ 20% of antigens problematic).
- `range_problem_antigens_*.csv` (200×11): 7 below_flag,
  41 above_flag.
- `range_problem_samples_*.csv` (84×11): 3 below_flag,
  14 above_flag.
- `background_qc_*.csv` (200×9): 0 CV-flagged, 93 max-flagged at
  the default `bg_max_mfi=100`. The default is aggressive for this
  panel — user can raise it on the Settings page.

HTML contains 9 `<details class="section">` blocks, a sidebar with
9 section links, and 10 summary stat cards. Dotted group separators
visible in the bead-count heatmap between A1-A10 (Standards) and
A11-A12 (Background) and at A12 → B1 (specimens). New CB-safe
palette swatches (#4477AA / #44AA99 / #EE7733 / #CCBB44) appear in
the range matrix.

**Deferred to Session 7 (explicit scope cut):**
- Curve-picker rug plot of specimen MFI colored by status.
- Curve-picker grey overlays of every previous plate's curve.
- A new specimen-MFI history JSON to feed the historical rug.

These three are coupled (same panel) and need their own design pass —
specifically: what plate identifier to use, how to throttle the rug
on antigens with hundreds of historical specimens, and how to handle
the case where the per-plate antigen panel changes over time.

### Session 5 — 2026-05-18

Two user-driven adjustments to the Section-5 report.

**1. Range classification — 3-state instead of binary.**
`compute_in_range_table` now emits `IN_RANGE` / `BELOW_RANGE` /
`ABOVE_RANGE` / `NO_FIT` (decision #3 reversed). Below-LLOQ and
above-ULOQ are distinct so users can tell which tail of the curve a
specimen falls off.

- `src/qc_standard_curve.py` —
  - `compute_in_range_table`: classify `mfi < lloq` as `BELOW_RANGE`
    and `mfi > uloq` as `ABOVE_RANGE`.
  - `compute_pct_in_range_per_antigen`: split `n_out_of_range` into
    `n_below_range` and `n_above_range`. `pct_in_range` formula
    unchanged.
- `src/report.py::_make_in_range_heatmap`: rewrote the colorscale to
  4 stops — BELOW = blue (#3498db), IN = pale neutral (#ecf0f1),
  ABOVE = orange (#e67e22), NO_FIT = grey (#7f8c8d). User chose this
  scheme to keep red/green out of the heatmap.
- `src/report.py::_format_range_problems`: include `status` column,
  filter on `status in {BELOW_RANGE, ABOVE_RANGE}`.
- `templates/report.html`: section retitled "Standard-Curve Range
  Matrix"; badges and legend rewritten; detail list shows a BELOW /
  ABOVE badge per row.

**2. Negative-control tracking.**
Background wells (`^Background`, A11/A12) and NC wells (`^NC` /
`^Negative`) are now distinct well types. The pilot plate has only
Background, so the NC report section renders a "No NC wells on this
plate" banner; future plates can drop in a sample named `NC1` /
`Negative_pool` and the section will populate automatically.

- `src/config.py`: added `BACKGROUND_PATTERNS = [r"^Background"]`;
  `NC_PATTERNS = [r"^NC", r"^Negative"]`. `DEFAULTS.well_classification`
  gained `background_patterns`.
- `src/classify.py`: `_classify_sample` returns `pc` / `background` /
  `nc` / `specimen` (3-way match before specimen fallback).
- `src/qc_nc.py` (new): `qc_nc_levels(df)` returns `[well,
  sample_name, analyte, mfi]` filtered to `well_type == "nc"`. Empty
  frame when no NC wells.
- `src/pipeline.py`: calls `qc_nc_levels`, passes to `generate_report`,
  exports `nc_levels_<plate>.csv` only when non-empty.
- `src/report.py::_make_nc_heatmap`: Purples MFI heatmap per (well ×
  analyte). Returns empty string when no NC wells, and the template
  renders the banner.
- `templates/report.html`: new "Negative-Control Levels" section
  between the range matrix and Downloads.
- `src/report.py::generate_report`: signature now takes `nc_levels=`
  and `n_nc_wells` / `nc_present` flow into the template.

**Smoke tests run:**
- Imports OK after refactor.
- `classify_wells` on a 4-row fixture: Standard1 → pc, Background0 →
  background, FD123 → specimen, NC_pool → nc.
- `compute_in_range_table` on a 4-row fixture: BELOW_RANGE,
  IN_RANGE, ABOVE_RANGE, NO_FIT all produced as expected; summary row
  has all four count columns.
- **Full pipeline run on `Pilot_Uvira_XXL/`**: report renders at 12.4
  MB in well under a minute on the local 3.13 venv. CSV status
  distribution: 13,625 IN_RANGE / 2,159 ABOVE_RANGE / 764 BELOW_RANGE
  / 252 NO_FIT (= 84 × 3 excluded analytes, as expected). HTML
  contains 2× "Standard-Curve Range Matrix", 766× `badge-blue`,
  2,161× `badge-orange`, 2× `badge-neutral`, 2× `badge-slate`, and
  the "No negative-control wells" banner.
- The lone residual `OUT_OF_RANGE` string in the HTML is inside the
  embedded plotly.js minified bundle (unrelated).

**Known follow-ups:**
- Section 6 validation patient-ID spot-check still outstanding.
- Section 7 docs/PyInstaller specs still outstanding.
- NC threshold flagging deferred per decision #6.
- Settings page does not yet expose the new `background_patterns`
  field (current default works for all pilot plates; revisit if a
  future plate needs custom Background naming).

### Session 4 — 2026-05-14

Implemented Sections 4 and 5. The pipeline now produces a fully
functional Uvira 200-plex HTML report end-to-end on the pilot data.
Legacy MagPix-only modules removed.

**Files added / rewritten:**
- `src/qc_beads.py` — fully rewritten. New return shape:
  `matrix` (analyte × well counts), `tier_matrix` (red/yellow/green),
  `sample_labels`, `problems` (long-format, sorted red-first), plus the
  legacy `flagged` / `n_flagged` / `by_well` fields for any code that
  still expects them. Tier classifier reads
  `qc_thresholds.bead_count_min` (red below) and `bead_count_warn`
  (yellow below; green above) — both editable from Settings.
- `src/report.py` — fully rewritten (≈400 lines, down from 813).
  Six-section Uvira layout (Plate Overview, Bead-Count Matrix,
  Standard-Curve Summary, Standard-Curve Picker, IN/OUT-of-Range
  Matrix, Downloads). Three Plotly figures (`_make_bead_heatmap`,
  `_make_curve_picker`, `_make_in_range_heatmap`); Plotly is loaded
  once via CDN at the top of the template. The curve picker bundles
  all 200 antigens as visibility-toggled traces with a single
  `updatemenus` dropdown.
- `templates/report.html` — fully rewritten. New CSS, semantic
  sections, sticky-header tables, muted-row styling for excluded
  analytes, downloadable CSV buttons.
- `src/pipeline.py` — dropped `qc_pc_replicates`, `qc_nc_levels`,
  `qc_kit_controls` calls and their imports. `generate_report` now
  receives the new args (`in_range`, `pct_in_range`) and the
  try/except wrapper from Session 3 is removed (the pipeline now
  expects the report to succeed). Bead-problem CSV export added
  (`bead_problems_<plate>.csv`). `_build_nc_history` deleted.
  `history_nc` is `None`.
- `src/qc_kit_controls.py`, `src/qc_nc.py`, `src/qc_replicates.py` —
  **deleted**.
- `src/config.py` — deprecated kit-control aliases (`MPXV_ANTIGENS`,
  `MPXV_KIT_CONTROLS`, `NC_BEAD_MFI_MAX`, `SCG_MFI_MIN`,
  `FC_MFI_RANGE`, `IC_MFI_RANGE`) removed; nothing imports them
  anymore.
- All `src/*.py` — `from __future__ import annotations` added so the
  modules parse on Python 3.9+ (project still officially requires
  3.11; this is purely defensive).

**Bug fixes during smoke-test verification:**
- **Plotly version skew** — plotly Python 6.x emits JSON for
  plotly.js 3.x but the template was loading a hardcoded
  plotly.js 2.27 CDN tag, so the three figures silently failed to
  render. Fixed by switching to `include_plotlyjs=True` on the first
  figure (embeds the matching v3.5.0 bundle inline) and `False` on
  the rest. Stale CDN `<script>` tag removed from `report.html`.
  Result is fully self-contained — no internet required, no version
  drift — at the cost of ~+4.6 MB per report. A
  `_reset_plotlyjs_embed_flag()` call at the top of
  `generate_report` ensures successive reports each get their own
  inline bundle.
- **Standard-curve perf** — `_fit_one` already had a degenerate-input
  guard (max-MFI floor) but `_try_drop_one_outlier` was still called
  on every failed fit, running 10 extra scipy passes per analyte
  with no signal. Now retry is gated on `params is not None` (i.e.,
  scipy converged but QC criteria failed). On the pilot data, the
  end-to-end wall clock should drop substantially from ~6:40.
- **4PL fit quality** (user reported HCoV_OC43_NP with `d=0` and a
  visibly bad lower tail) — root cause was linear-residual fitting.
  The upper plateau (~10⁵ MFI) dominates absolute residuals, so the
  optimizer "ignored" tail points at MFI ~80 and landed at `d=0`.
  Switched `_fit_one` to fit on log10(MFI), matching standard
  immunoassay practice; R² and the retry path's selection metric now
  use the same log-space objective. Also fixed misleading
  `a_init` / `d_init` variable comments (the math was always right
  because both have the same `[0, ∞)` bounds, but the comments
  swapped what each represents). X-axis label clarified from
  `Dilution (1:x)` → `Dilution factor (1 : x)`.

**Smoke tests run:**
- `qc_bead_counts` on the pilot data: matrix shape `(200, 96)`,
  430 red cells, 856 yellow cells, 1,286 problem rows. The three
  excluded bead regions consistently show 0 beads across every well
  (consistent with their being added in error).
- **Render-only end-to-end** (`/tmp/uvira_smoke_render.py`):
  parse → layout merge → bead-QC → synthetic 4PL fits → range tables
  → `report.generate_report` → 6.3 MB self-contained HTML. All 13
  grep markers hit (UI sections present, excluded analyte rendered,
  Box xlsx + barcode + IN_RANGE/OUT_OF_RANGE language present, no
  residual MPXV / kit-control / NC-bead strings). Synthetic fits used
  to bypass `scipy.curve_fit` because the system Python 3.9 used in
  this dev env is far slower than the project's pinned 3.11 + scipy
  ≥ 1.11. **Full scipy-fit pass on the project's 3.11 still to be
  done by the user** — `uv run python -m src.main`, then upload the
  pilot CSV / inputfile / Box xlsx through the web UI.
- `_fit_one` was given a **degenerate-input guard** (max-MFI floor +
  flat-response check) to keep `scipy.curve_fit` from thrashing on
  all-zero noise channels (the three excluded bead regions and any
  similar low-signal antigens). `maxfev` lowered 50,000 → 10,000.
- **Full real-scipy run** on pilot data: 6:40 wall clock initially;
  after the perf gating above, much faster. Output:
  - HTML 11 MB (with embedded plotly.js)
  - `specimens_*.csv` 2.5 MB
  - `in_range_*.csv` 2.3 MB
  - `pct_in_range_*.csv` 8 KB
  - `bead_problems_*.csv` 52 KB

  Real-fit `pct_in_range` distribution: median 86.9%, mean 74.2%.
  195/200 antigens have at least one specimen in range. The three
  excluded analytes all correctly show 0 IN_RANGE / 84 NO_FIT.

**Known follow-ups (Section 6 / 7):**
- Section 6 validation cross-check (a handful of patient IDs) still to
  do — the wiring is in place; just need to spot-check a few wells.
- Section 7: legacy descriptive copy in README.md and SPECIFICATION.md
  still describes the MPXV 12-plex assay; the GitHub URL in the
  templates/footer still points at the old repo; PyInstaller specs
  not yet renamed.
- The `KIT_CONTROLS = []` constant and the kit-control branch in
  `qc_standard_curve._fit_one`'s pool-discovery code are dead and
  could be simplified further.

**Next session:** Section 6 (validation pass with patient-ID
spot-check) and Section 7 (rewrite README / SPEC, update repo URLs,
rename PyInstaller specs).

### Session 3 — 2026-05-14

Implemented Sections 2 and 3. Pipeline now produces the Section-3
deliverable CSVs end-to-end on the pilot data; HTML report rendering
remains the Section-5 task.

**Files edited:**
- `src/config.py` — added `BEAD_COUNT_WARN = 50` to `DEFAULTS`. Re-added
  the deprecated kit-control thresholds (`NC_BEAD_MFI_MAX`,
  `SCG_MFI_MIN`, `FC_MFI_RANGE`, `IC_MFI_RANGE`) as module-level
  constants so legacy `qc_kit_controls.py` and `report.py` keep
  importing during the Section-5 transition.
- `src/parse_xponent.py` — `metadata['analytes']` now carries the
  per-plate panel in the order the instrument exported it.
- `src/qc_standard_curve.py` — `fit_standard_curves` accepts an
  `antigens=` kwarg. Two new functions:
  - `compute_in_range_table(data, fits, excluded_analytes)` →
    long-format `(well × analyte)` table with MFI, MFI bounds, ternary
    `status`, `excluded` flag, and any sample-id / barcode / patient-id
    columns from the layout merge.
  - `compute_pct_in_range_per_antigen(in_range, excluded_analytes)`
    → per-antigen summary with `n_samples / n_in_range /
    n_out_of_range / n_no_fit / pct_in_range / excluded`.
  - Helper `_mfi_bounds_for_fit(fit_result)` evaluates the 4PL at the
    LLOQ/ULOQ dilutions to get MFI bounds for the IN/OUT decision.
- `src/pipeline.py` — uses `metadata['analytes']` as the authoritative
  panel for `fit_standard_curves`; calls the two new range functions
  using `get_excluded_analytes(config)`; exports
  `in_range_<plate>.csv` and `pct_in_range_<plate>.csv`. The
  `generate_report` call is now wrapped in try/except — when it fails
  (expected during Section-5 transition) a placeholder HTML is written
  so Past Reports still has a row, and the pipeline carries on to
  produce the CSVs.
- `templates/web/settings.html` — replaced. Per-antigen / kit-control
  table editors removed (panel is auto-derived). New
  `excluded_analytes` textarea (newline-separated), `bead_count_warn`
  input, simplified standard-dilutions field. Legacy
  `nc_bead_mfi_max` / `scg_mfi_min` / `fc_mfi_*` / `ic_mfi_*` /
  `pc_cv_threshold` / `dilution_mode` fields removed from the UI.
- `src/app.py` — `save_settings` rewritten to match the new form:
  parses `excluded_analytes`, `bead_count_warn`, single
  `standard_dilutions` field; drops the per-row antigen / kit-control
  iteration and the kit-control range parsers.
- `UVIRA_TODO.md` — Sections 2 and 3 marked done (curve-plot rendering
  deferred to Section 5).

**Smoke tests run:**
- `parse_xponent_csv()` on pilot CSV: `metadata['analytes']` carries
  all 200 names in order.
- `compute_in_range_table()` with synthetic 4PL fits derived from the
  standard MFI bounds: 16,800 rows = 84 specimens × 200 antigens;
  status counts split 14,723 IN_RANGE / 2,077 OUT_OF_RANGE; 252 rows
  flagged `excluded=True` (84 × 3 erroneous beads).
- `compute_pct_in_range_per_antigen()`: 200 rows; the three excluded
  bead regions show 0–3.6% in-range (correctly the worst), good
  antigens like `RES_Ade3` show 97.6%.

**Known follow-ups (NOT done in Session 3):**
- `report.py` not rewritten yet — still imports kit-control constants
  and tries to render an 8-antigen layout. Pipeline now swallows the
  resulting error and writes a placeholder. Section 5 owns the rewrite.
- `qc_kit_controls.py`, `qc_nc.py`, `qc_replicates.py` still called
  from `pipeline.py` — they return empty/safe results on Uvira data
  but should be deleted in Section 5.
- Bead-count Red/Yellow/Green matrix and problem list (Section 4) not
  yet built. The thresholds (`bead_count_min`, `bead_count_warn`) are
  in config and editable from Settings; the matrix-building helper
  is the Section-4 task.

**Next session:** Section 4 (bead-count matrix + problem list) and the
start of Section 5 (200-antigen report layout).

### Session 2 — 2026-05-13

Implemented Sections 0 and 1 (foundation only — report rendering stays
broken for Uvira data until Section 5).

**Files edited:**
- `src/config.py` — fully rewritten. `ANTIGENS` is the 200-name Uvira
  panel pulled from the pilot CSV header; `KIT_CONTROLS = []`;
  `EXCLUDED_ANALYTES = [FLU_B_HA_Maryland_1959, FLU_B_NP_Brisbane_2008,
  VPD_Tet_tox]`; `STANDARD_DILUTIONS` baked in as the 10-point 4-fold
  series from the screenshot (62.5 → 16,384,000); new `PC_PATTERNS =
  ['^Standard\d+$']` and `NC_PATTERNS = ['^Background']`; new
  `BEAD_COUNT_WARN = 50` threshold; `RESULTS_DIR_NAME =
  'uvira-luminex-qc-results'`; `APP_VERSION = '0.9.0-uvira'`. Kit-control
  kit-bead defaults removed. `MPXV_ANTIGENS` / `MPXV_KIT_CONTROLS` kept
  as deprecated aliases.
- `src/settings.py` — uses `RESULTS_DIR_NAME`; new
  `get_excluded_analytes()` accessor.
- `src/classify.py` — new `^Standard\d+$` PC pattern, `^Background` NC
  pattern; dropped `pc_pool`; PC dilution looked up by Standard index
  into `STANDARD_DILUTIONS`.
- `src/parse_xponent.py` — handles Intelliflex `Program` field
  (captures `instrument_program`), additional `DataType:` blocks,
  `PanelName` / `BatchDescription` / `BatchStopTime` metadata. Metadata
  scan stops at first `DataType:`. Plate-ID fallback uses the raw batch
  string when the `-Plate\d+` pattern doesn't match.
- `src/parse_layout.py` — replaced. New `read_inputfile_csv()`,
  `read_box_xlsx()`, `build_layout()`. Old `read_plate_layout(path)`
  kept as a backward-compat wrapper.
- `src/pipeline.py` — `run_pipeline()` takes new `inputfile_path` kwarg;
  when present, layout merge routes through `build_layout` and yields
  `sample_id` / `barcode` / `patient_id` / `box_id` columns.
- `src/app.py` — three-file upload form wired (`inputfile_file` added);
  registry stores `inputfile_filename`; delete + Regenerate-All paths
  updated; download filenames / page titles / results-dir path
  rebranded.
- `src/main.py` — rebranded.
- `templates/web/index.html`, `templates/web/settings.html`,
  `templates/report.html` — page titles, footer strings, GitHub link
  rebranded (link still points at legacy `mpox-luminex-qc` repo —
  flagged for Section 7).
- `README.md` + `SPECIFICATION.md` — top sections rebranded; bodies
  flagged "migration in progress" pending Section 7 rewrite.
- `UVIRA_TODO.md` — Sections 0 + 1 marked done / partial as appropriate.

**Smoke tests run:**
- `parse_xponent_csv()` on the pilot CSV: 200 analytes, 96 wells, batch
  + SN + panel name + Intelliflex program correctly captured. Plate ID
  resolved to `PLATE_05112026_RUN000`.
- `classify_wells()` on the parsed data: 10 PCs (Standard1..Standard10)
  with the correct dilution ladder 62.5 → 16,384,000; 2 NCs
  (`Background0` in A11/A12); 84 specimens.
- `build_layout()` joining `_inputfile.csv` × `RENAMED-Box1_Uvira_sera_2023.xlsx`:
  96 rows, 84/84 specimens get a patient ID, 12 control wells correctly
  empty.

**Known follow-ups (NOT done in Session 2 — explicit scope cut):**
- `report.py` still imports / renders kit-control + multi-pool +
  replicate-CV sections that no longer exist in the Uvira pipeline. The
  app will not produce a usable HTML report on Uvira data until
  Sections 3–5 land. The 4PL math itself (`qc_standard_curve.py`) is
  unchanged and ready to run.
- `qc_kit_controls.py`, `qc_nc.py`, `qc_replicates.py` not yet deleted;
  `pipeline.py` still calls them. Pipeline rewrite is part of Section 3+.
- GitHub repo URL in templates + README still points at the legacy
  repo path — flagged for Section 7.
- PyInstaller specs (`mpox-luminex-qc.spec`, `mpox-luminex-qc-win.spec`)
  not yet renamed.
- No unit tests written; testing is by-hand smoke tests only.

**Next session:** Section 2 (config / panel auto-derivation from the CSV
header, Settings-page wiring for the new fields) and Section 3 (standard
curves over 200 antigens + the "% in linear range" metric).

### Session 1 — 2026-05-13
- Reviewed the `uvira-luminex-qc` repo end to end (`src/*.py`, README,
  SPECIFICATION) and the OneDrive data drop (Intelliflex CSV, plate input
  file, 22 barcode-map xlsx files, dilution-series screenshot).
- Captured project context, mapped each existing module to reuse/edit/drop.
- Authored this `UVIRA_TODO.md` with the working plan and four open
  questions for the user.
- **User answers received** (same session):
  - Initial: dual-mode app accepted. **Reversed shortly after**: go
    single-mode Uvira 200-plex only; MPXV 12-plex MagPix support will be
    removed.
  - Excluded beads → **soft flag** (muted, not dropped).
  - IN/OUT-of-range table → **strictly binary**.
  - Barcode-map workflow → **manual upload** at submit time.
- **No code edits yet.** All open questions resolved. Next session:
  start on Section 0 (strip MPXV code, rebrand) and Section 1 (Intelliflex
  parser + manual upload of inputfile.csv and Box xlsx).
