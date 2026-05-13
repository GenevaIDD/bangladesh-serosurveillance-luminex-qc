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
- [ ] In `config.py`, replace `MPXV_ANTIGENS` / `MPXV_KIT_CONTROLS` with the
      ~200 Uvira antigens. Source of truth = header row of the Median block;
      consider auto-deriving the panel from the CSV on first ingest and
      caching to YAML.
- [ ] Drop `MPXV_KIT_CONTROLS`-driven QC; add an `excluded_analytes` list
      (the 3 erroneous ones above) editable from the Settings page.
- [ ] Update `well_classification`: PC pattern `^Standard\d+$`, NC pattern
      `^Background$`; specimen = everything else (or `^FD\d+`).
- [ ] Encode the standard dilution series (10 points, 4-fold from 62.5 →
      16,384,000) as defaults; allow override.

### 3. Standard-curve QC (200 antigens)
- [ ] Run existing 4PL fit per antigen (single pool). Surface `fit_ok`,
      params, R², dynamic range as before.
- [ ] **New metric**: % of specimen samples falling inside the linear
      (reportable) range, per antigen. Use the LLOQ/ULOQ logic already in
      `_compute_reportable_range`.
- [ ] **New table**: per-(antigen × sample) **strictly binary**
      `IN RANGE` / `OUT OF RANGE` label, color-coded (green / red).
      "Out of range" = MFI below LLOQ MFI **or** above ULOQ MFI; both
      conditions collapse to the same red label. Filterable by antigen and
      by sample; export to CSV.
- [ ] Curve plots: 200 antigens won't fit in a 2×4 grid. Paginate or render
      a searchable picker that swaps a single plot at a time. Keep a summary
      heatmap (antigens × QC checks: R², slope, IC50, %-in-range).

### 4. Bead-count QC
- [ ] **New table**: rows = antigens, columns = samples, cell = bead count,
      color-coded RED `<30`, YELLOW `30–50`, GREEN `>50`. Render with
      sticky headers; for 200×~90 the DOM gets large, so use a virtualized
      table or Plotly heatmap with hover.
- [ ] Companion **problem list**: enumerate every `(sample, antigen)` pair
      that is red or yellow, grouped by sample, with bead count shown.
- [ ] Wire the threshold pair (30 / 50) into Settings.

### 5. Reporting & UI
- [ ] Audit `templates/report.html` and `report.py` for hard-coded references
      to the 8-antigen layout / kit-control beads.
- [ ] Add the two new sections (bead-count matrix + range matrix) and the
      antigen picker.
- [ ] Banner: list of excluded analytes; banner: which Box barcode map was
      used (if any).
- [ ] Specimen results table needs to scale to 200 columns — pivot the
      default view so antigens are rows.

### 6. Validation
- [ ] End-to-end run on `Pilot_Uvira_XXL/`. Confirm report opens, all 200
      antigens render, the 3 erroneous beads are flagged, bead-count matrix
      and IN/OUT-of-range matrix populate correctly.
- [ ] Cross-check a handful of patient IDs against
      `RENAMED-Box1_Uvira_sera_2023.xlsx`.

### 7. Packaging & docs
- [ ] Update `README.md` and `SPECIFICATION.md` to describe the Uvira /
      Intelliflex / 200-plex assay.
- [ ] Re-run PyInstaller specs (mac + win) once the rename lands.

---

## Decisions log

| # | Decision | Date |
|---|---|---|
| 1 | ~~Dual-mode app~~ **Reversed**: single-mode Uvira 200-plex Intelliflex; MPXV 12-plex MagPix path will be removed. | 2026-05-13 |
| 2 | Excluded bead regions are **soft-flagged** (rendered muted, never dropped). | 2026-05-13 |
| 3 | IN/OUT-of-range table is **strictly binary**. Below-LLOQ and above-ULOQ both collapse to "OUT OF RANGE". | 2026-05-13 |
| 4 | Barcode-map workflow: **manual upload** at submit time (no auto-matching by filename / BatchDescription). | 2026-05-13 |

## Open questions for the user

_None at the moment._ All four initial questions are resolved (see
Decisions log).

---

## Session History

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
