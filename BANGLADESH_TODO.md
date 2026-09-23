# Bangladesh National Serosurveillance Luminex QC — To-Do & Session Log

## RELEASE DECISION (supersedes v0.4.0 planning below)

**Everything ships together in v0.3.0** — Phases 8/9/11, Phase A (pool remap),
the bead-count + text + doc updates, AND the 5PL curve model. The "→ v0.4.0"
notes in the older planning entries below are historical; 5PL is part of 0.3.0.
Version strings are set to 0.3.0. All work uncommitted pending the user's tag.

**Home-page model selector now authoritative for BOTH generate + Regenerate All
(bug fix).** Root cause of "changed the dropdown but the report still says 5PL":
the dropdown only fed the /upload route; **Regenerate All used the saved Settings
model** (default 5PL). Fixed: Regenerate All form now carries `curve_model`
(hidden input synced from the dropdown via onsubmit) and `regenerate_all()` reads
+ applies it; both `/upload` and `/regenerate-all` now **persist** the chosen
model to config (dropdown, Settings, and regenerated reports stay in sync; the
home dropdown default reflects the persisted value). Verified via Flask test
client: upload(4pl)→4PL, regen(5pl)→5PL, regen(4pl)→4PL, config persisted each
time, dropdown default follows. (NOTE: the dropdown affects *newly generated*
reports; re-opening an old report without regenerating shows its original model —
now also covered by the no-cache headers/meta.)

**Model-text audit (5PL↔4PL) + cache fix.** Diffed the same plate rendered under
both models: report text DOES update (badge, featured/picker legends via
len(params), Fit-OK definition, g column, all curve_model_label description
boxes). Found + fixed ONE stale spot: the Positive Control description hardcoded
"fit to a 4PL curve" → now `{{ curve_model_label }}`. No hardcoded four/five-
parameter text remains. Root cause of "text doesn't update on re-run" = **browser
caching** (reports reuse `QC_<plate_id>.html`): added no-cache headers to the
`/report/<filename>` route + a no-cache `<meta>` in the report head. Both re-run
paths (upload selector override; regenerate_all via saved config) correctly thread
`curve_model`.

**Fit-OK column now 3-state** (was binary OK/FAIL): OK (passed QC) / FAIL (curve
fit but failed a criterion) / **NO_FIT** (no curve at all — params None). Added
`no_fit` to `_build_curve_summary` rows; template badge dispatches (grey NO_FIT);
"Definition of Fit OK" box + README explain all three. Range Matrix already had a
distinct NO_FIT status. Verified: summary shows OK/FAIL/NO_FIT distinctly.

**Priority Antigens setting REMOVED** (superseded by Phase 9 "show all + Relevance
column"). Deleted: settings.html field + YAML-import mention, app.py POST parse,
config.py DEFAULTS key, config.example.yaml block, `settings.get_priority_antigens`,
report.py priority computation + unused `curve_summary`/`_pool_fits_for` +
`priority_*` context vars. Summary (`_build_summary_by_pool_all`) + Featured +
All-curves already use `panel_order` (all antigens), so no display change. Test
`test_config_roundtrip` now round-trips `curve_model` instead. README/SPEC updated.

**CI runners pinned** (build.yml): `macos-15` + `windows-2022` (were
`macos-latest`/`windows-latest`) for reproducible release builds — macos-14
began deprecation 2026-07-06; macos-latest now → macos-26. Bump when GitHub
deprecates these (keeps ~2 versions). **Pre-release review done:** py_compile
clean, test suite 2/2, Flask app + templates render, config.example.yaml +
DEFAULTS carry `curve_model: 5pl`; full-panel run only exceeds the sandbox 45s
cap (fine on a real machine). Stale `config.py` fallback comment fixed.

## PLAN — Pool relevance remap (Phase A, near-term) + 5PL (v0.4.0)

**Phase A — pool relevance remap + Institute Pasteur recognition (items 1–3).**
Mostly `qc_standard_curve.py`; Featured/Summary builders derive from these helpers
so they update automatically.
- **A1.** Split non-dengue **arbovirus** into its own group (today it collapses to
  `dengue`, which is why Dengue and Orpal look identical). Relevance groups:
  dengue→`{dengue}`, non-dengue arbo→`{arbovirus}`, cholera/typhoid own,
  **M/D/R/T VPD→ordered `[vpd_nibsc, arbovirus]`** (NIBSC preferred, pan-arbo
  fallback), **all other VPD→`[]` (never featured/relevant)**.
- **A2.** `_pool_groups` returns sets + recognizes the pan-arbo pool by name:
  Dengue→`{dengue}`; **Orpal OR Institute Pasteur** (tokens `orpal`/`pasteur`/
  `institut`)→`{dengue, arbovirus}`; Anti-OSP&cTxB&HlyE→`{cholera, typhoid}`;
  NIBSC→`{vpd_nibsc}`. Orpal kept for pilot; no display rename.
  → Dengue pool = dengue only; Institute Pasteur/Orpal = dengue + arbovirus
  (dengue fit against BOTH); non-MRT VPD featured nowhere but still fit against
  every pool (viewable in picker + all-antigens tables).
- **A3.** `antigen_calibration`/scoring: arbovirus→pan-arbo reference; non-MRT
  VPD→best-fit/`uncalibrated`; M/D/R/T→NIBSC `standard`, else pan-arbo `reference`
  (DECIDED: fall back to pan-arbo when NIBSC absent, e.g. pilot).
- **A4.** Verify on pilot ("Orpal") + a synthetic "Institute Pasteur" pool.

**Phase B — 5PL model (item 4) → v0.4.0 (separate release).** Add `five_pl` +
inverse; `panel.curve_model` config (**default `5pl`**, `4pl` optional) + settings
dropdown; model-aware fitting/bounds/plotting/back-calc/R²/history overlays;
**tag each stored fit with its model** (existing 4PL history kept & rendered under
its own model — DECIDED); **mark the model clearly in the report** (badge +
per-curve); docs.

**Sequencing (DECIDED):** Phase A near-term; 5PL as v0.4.0.
Tasks: #10–#13 (Phase A), #14 (5PL).

**Phase B / 5PL STATUS: DELIVERED (uncommitted), staged 0–4 + verified.**
Version aligned to **0.3.0** (APP_VERSION `0.3.0-bangladesh`, pyproject `0.3.0`,
SPEC) — the current unreleased work is 0.3.0; **5PL ships as 0.4.0** when cut.
- **Model:** standard asymmetric 5PL `y=d+(a−d)/(1+(x/c)^b)^g` (g∈[0.1,10]) +
  4PL; `five_pl`/`invert_5pl` + `curve_eval`/`curve_invert` dispatch by param
  count. `panel.curve_model` default `5pl`.
- **Uniform per report, NO per-antigen fallback** (user's revised decision): a
  report is one model throughout; 5PL-fail → NO_FIT (re-render under 4PL to try).
  Chosen at **render time** via a **home-page selector** (default 5PL) + Settings
  default. `_fit_one(model=…)` fits the one model; fit_ok checks unchanged.
- **Model-aware end-to-end:** obs/exp, reportable range, R², concentrations,
  mfi-bounds, report curve drawing (server + picker JS `curve()`), summary (+g
  column), all dispatch by param count. Fit result + history store `model`+`g`.
- **History (Option A, user's choice):** no duplication — dedup key is
  `(plate_id, analyte…)`, keep-last, so re-rendering the SAME csv under a
  different model **overwrites** (never double-counts). Model not in the key.
  Past-plate curve **overlays drawn under each plate's own stored model**;
  clearly stated on the **home page**, in the Featured/Picker **description
  boxes**, and in the overlay **hovers** (`<plate> · 4PL/5PL (as fit)`).
- **Report marking:** "Curve model: …" banner in Standard-Curve Summary; trace
  names + all description "4PL" wording now model-aware (`curve_model_label`).
- Verified: 5PL R²≥4PL on dengue, g≈0.5 (real asymmetry), near-asymptote
  back-calc differs sensibly; both modes render; mixed-model overlay (5PL report
  over 4PL history) renders; settings/index templates render.

**Phase A STATUS: DELIVERED (uncommitted), verified on both pilot fixtures.**
- A1/A2: `_antigen_scoring_groups` (arbovirus own group; M/D/R/T `[vpd_nibsc,
  arbovirus]`; other VPD `[]`) + `_pool_groups` (Dengue `{dengue}`; Orpal/Institute
  Pasteur `{dengue,arbovirus}`; combined/split cholera+typhoid handled by
  independent osp/ctxb/hlye tokens). A3: `antigen_calibration` (arbovirus→
  reference; M/D/R/T→standard@NIBSC / reference fallback; other VPD→uncalibrated);
  removed dead `_SCORING_POOL_GROUP`.
- Verified end-to-end (parse→classify→fit→render) on Plate 1 (5 pools: combined +
  split Anti-OSP&cTxB + HlyE + Dengue + Orpal) and Plate 2 (3 pools). Featured:
  Dengue=dengue only; Orpal=dengue+arbo+M/D/R/T(fallback, no NIBSC on pilot);
  cholera→every OSP/cTxB pool, typhoid→every HlyE pool. The 3 non-MRT VPDs shown
  in all-antigens tables/picker but relevant=False everywhere & uncalibrated.
- **Text/label sync (post-review):** `_pool_target_label` rewritten (Dengue→
  "Dengue"; Orpal/IP→"Dengue · Other arbovirus (reference)"; NIBSC→"Measles /
  Diphtheria / Rubella / Tetanus") — drives every "targets:" label. Updated stale
  narrative in report.html (auto-select matching, calibration-tier legend,
  Featured description, **"How to read this matrix"**) and settings.html pool-rules
  list. Verified matrix hover now shows non-MRT VPD as "no calibrating standard".
  NOTE: SPECIFICATION.html still has old wording — covered by the pending doc-sync
  task.
- **Dengue scoring preference (post-review):** `select_pool_per_antigen` now
  prefers the *dedicated* Dengue pool over the pan-arbo Orpal/Institute Pasteur
  pool for dengue scoring (ranking tier `dedicated` = pan-arbo pools deprioritized
  for group=dengue; sits above R² but below params/fit_ok, so it only falls back
  when the dedicated fit is unusable). Fixes dengue antigens getting swapped onto
  Orpal by a marginally higher R² (e.g. DENV1_VLP). Featured still shows dengue
  under both pools. Verified: all dengue → Dengue pool; CHIKV → Orpal (reference).
- **Label reword:** `_pool_target_label` pan-arbo case → "Dengue & other
  arboviruses (pan-arbovirus reference)" (plain `&`; escaped downstream).
- 5PL (#14) remains for v0.4.0.

**Text audit (report + settings + report.py strings) — done (uncommitted):**
- ACCURACY: clean across all three files — no stale pool descriptions, no
  premature 5PL claims (only 4PL referenced), correct card denominators,
  standardized "Intra-/Inter-assay %CV". Phase A text sync held up.
- TONE fixes (report.html + 2 report.py placeholders): bead "200 scattered single
  misses" → neutral wording; Picker "Pick any… / Use this to investigate" →
  "Select an… / This view is intended for inspecting…"; Downloads "Looking for the
  clean analysis table? … tidy" → "Analysis-ready results table. The
  consolidated…"; "downstream-analysis workhorse" → "primary table for downstream
  analysis"; placeholders "start typing…" → "Search antigen, e.g. RES_Ade3"
  (standardized); heading 'What does "Fit OK" mean?' → 'Definition of "Fit OK"'.
- JUDGMENT: kept ✓ (pass) / ⚠ (warn) status glyphs as functional QC indicators.
- settings.html: no changes needed. SPECIFICATION.html "tidy" wording will be
  refreshed in the pending doc-sync task.

**Bead Count section — 3 tweaks (post-review, uncommitted, verified on plate 1):**
1. Grid x-axis wells now **sorted by plate position** (`_make_bead_heatmap`
   reindexes matrix/tier_matrix columns via `_well_sort_key`) so re-run wells that
   xPONENT appends at the end of the CSV (e.g. D7/G7/L24) no longer trail off the
   right out of sequence — order is now monotonic A1→last.
2. Top-row card reworded "Overall **cells**" → "Overall **grid cells** with bead
   count < N" (both red & yellow cards) to clarify the denominator is the
   well×antigen grid.
3. New top-row card: **"Wells with ≥ 1 antigen at critically low bead count
   (< N) — out of {bead_n_wells} wells"** (`_tier_counts` now returns `red_wells`
   = distinct wells with any red cell; `bead_n_wells` = matrix column count). Top
   row widened to 5 cards. Plate 1: 3 / 346 wells.
4. **Card reorder** (post-review): wells-with-critically-low card moved to
   FIRST; order now wells → grid cells <N (red) → grid cells N–M (yellow) →
   antigens flagged → specimens flagged.

**Full-panel VPD audit (200 antigens) — verified correct after Phase A:**
9 VPD-group antigens. PRIORITY/featured (M/D/R/T, scoring `[vpd_nibsc,
arbovirus]`, standard@NIBSC / reference fallback): VPD_measles_NP,
RES_measles_lysate, VPD_Diphteria_Tox, VPD_Rub_VLP, VPD_Tetanus_Toxin,
VPD_Tet_tox. EXCLUDED (scoring `[]`, uncalibrated, best-fit only, never
featured): VPD_B_pertussis_FHA, VPD_Bordetella_p_Tox, VPD_N_meningitidis_B_MP.
Sanity scan: BAC_N_meningitidis_C_CPS & RES_mumps_NP correctly not featured
(not M/D/R/T). No missed/false matches.

---

Working document tracking a **new project** forked from `uvira-luminex-qc`
(which was itself forked from the legacy `mpox-luminex-qc`). This app provides
automated QC for **202-plex Luminex immunoassays run on a 384-well plate** for
the Bangladesh National Serosurveillance project.

Keep the **To-Do** section as the running plan and append a new entry under
**Session History** at the end of every working session. Mirror the conventions
of `UVIRA_TODO.md`.

> **STATUS: PLAN FOR REVIEW (Session 0).** Nothing in the code has been changed
> yet beyond the folder fork. The sections below are the proposed plan. Please
> review, edit, and confirm before implementation begins.

---

## Project context (snapshot)

- **Lineage**: `mpox-luminex-qc` (12-plex MPXV, MagPix, **multi-pool** standards
  "ITM PC"/"ITM PC2") → `uvira-luminex-qc` (200-plex, Intelliflex pilot,
  **single** `Standard1..10` series) → **this repo** (Bangladesh national
  serosurveillance, 384-well, **multi-pool** standards). Bangladesh is in some
  ways closer to the *legacy mpox* multi-pool design than to Uvira — the two
  attached screenshots ("ITM PC" / "ITM PC2" small-multiples with the green
  linear-range square, red out-of-tolerance triangles, and "×" excluded point)
  are exactly the legacy multi-pool curve grid we want to reproduce.

### Confirmed from the two pilot CSVs (parsed 2026-06-01)
- **Plate format**: **384-well, rows A–P (16) × columns 1–24 (24)**. Header
  declares `ProtocolPlate … Type,384`. Plate 1 (`…21.8.25`) fills A–P
  (346 wells); Plate 2 (`…25.8.25`) fills A–N (316 wells). Uvira's hard-coded
  96-well (8×12) plate map + several heatmap layouts MUST be generalized to 16×24
  (well-position regex is `[A-H]\d+` today → needs A–P / 1–24).
- **Panel**: both pilots expose **200 analytes** in the `Median` header (Uvira's
  exact same 200-name panel, `RES_Ade3 …`). The brief says "202-plex" — likely
  the production panel adds 2 antigens. Panel is auto-derived per ingest, so this
  is not blocking, but the default `ANTIGENS` list and "202" branding should be
  reconciled (see Open questions). DataType blocks present: Median, Mean, Count,
  Avg MFI, %CV, Peak, Std Dev, Trimmed Peak/SD/Mean, Net MFI, Avg Net MFI, Units,
  Dilution Factor. Operating mode: `FLEXMAP 3D® High PMT`. SN `IFLEXS23121001`.
  Batch e.g. `PLATE_08212025_RUN000`.
- **NO `inputfile.csv` was provided** — well classification must come from the
  `Sample` name in the CSV (regex), not an authoritative `Type` column.
- **Sample naming is entirely different from Uvira** (no `Standard1..10`):
  - **Background** → `Background0` (wells A1–A4). 4 wells per plate.
  - **Standards / PC = MULTIPLE distinct pools, each its own dilution series,
    with the dilution encoded in the sample name**:
    - `Pilot Control: Anti-OSP & cTxB (& HlyE) pool … 1:1 … 1:16384` (8-pt)
    - `Pilot Control: Dengue pool 1:1000 … 1:16384000` (8-pt)
    - `Pilot Control: Orpal pool 1:100 … 1:102400` (11-pt)
    - `Pilot Control: HlyE 0.39…50 ng/mL` (8-pt concentration series, Plate 1)
    - `Pilot Control: Cholera High/Low (1:1000)` (single points)
  - **Negative controls (NC)** → `Pilot Control: Negative 0 , 1:1000` and
    `Pilot Control: Negative 49 , 1:1000`. 4 NC wells per plate.
  - **Specimens** → `{id}_r3_{Serum|DBS}` (e.g. `10012_r3_Serum`,
    `10012_r3_DBS`). Each specimen appears as BOTH a Serum and a DBS sample.
    ~248–250 specimen wells per plate.
- **Implication — multi-pool standards return.** The Uvira single-series logic
  is insufficient. We need to: (a) parse the **pool name** and **dilution** from
  each PC sample name, (b) fit a 4PL per (pool × antigen), and (c) revive the
  per-pool history slug logic that Uvira simplified away (Section 1 / 5 below).
- **Priority pathogens (NEW concept)**: each pool targets specific pathogens
  (Dengue pool → dengue antigens; Anti-OSP/cTxB/HlyE & Orpal → cholera/typhoid;
  etc.). Only priority (pool × antigen) curves are meant to be *interpreted*.
  Curves are still *fit* for all antigens; Summary / All-Curves Overview show
  priority antigens by default. Default = all antigens until the team defines the
  pool→antigen priority mapping.
- **Dev fixtures**: the two pilot CSVs above now live in `tests/fixtures/`.
  No barcode map / patient-ID join yet (specimen IDs are in the sample name).

### Study design & controls (from project protocol, 2026-06-01)
- **Instrument / mode**: Intelliflex, **High PMT (enhanced) mode only** — all
  cross-sectional V. cholerae models were built on high-sensitivity mode for its
  higher MFI and greater dynamic range. Bead reagents mixed once weekly.
- **Production panel = 202-plex.** The pilots ran fewer beads because some
  bead-antigen reagents (e.g. MSP1, SARS-CoV-2) were in short supply; excluding
  low-volume beads was acceptable. So: brand the app "202-plex", but keep the
  panel **auto-derived from each CSV header** (pilots legitimately show ~200).
- **Goal**: quantify Relative Antibody Units (RAU) / Antibody Units (AU) and
  estimate seroprevalence/seroincidence. Final assay uses cholera + typhoid
  mAbs and icddr,b dengue pooled controls; Richelle Charles (RC) protocol is the
  study protocol.
- **Intended plate layout (well budget)**: Blank 4; V. cholerae OSP+CTXB mAbs 16;
  Typhoid HlyE mAbs 16; OSP+CTXB+HlyE combined mAbs 16; individual dengue
  controls 56 (28 samples ×2); Dengue pooled serum control 16; ORPAL controls 22;
  DBS SeroChit 124; Serum SeroChit 124; V. cholerae pooled serum High/Low 4
  (2 high, 2 low); Negative controls 4.
- **Control intent (drives the pool → priority-antigen mapping)**:
  - **V. cholerae mAbs** (OSP IgG + CTXB IgG; ±HlyE) → cholera antigens (OSP/CtxB);
    high/low pooled serum marks the detectable range.
  - **Typhoid HlyE mAbs** (8-pt dilution series) → S. typhi HlyE. Pilot tests
    whether HlyE can be combined in-well with cholera mAbs vs run separately.
  - **Dengue pooled serum** + **individual dengue controls** (28 PCR-confirmed,
    serotype counts DENV1=3, DENV2=21, DENV3=4, DENV4=0) → DENV antigens.
  - **ORPAL controls** (White lab, limited stock) → dengue/flavivirus;
    used to cross-validate the icddr,b dengue pool.
  - **Negative** = pooled North American plasma collected pre-2019 (also a
    SARS-CoV-2-naïve control for future work).
- **Two pilot plates have different purposes**:
  - **Plate 1**: cholera controls; compares **Michael White vs Richelle Charles
    protocols** by MFI concordance (study will use RC; scaling factor TBD).
  - **Plate 2**: blank + negatives + the 28 individual dengue controls in
    duplicate; RC protocol, 202-plex reagents; characterizes the dengue control
    pool (primary vs secondary infection, cross-reactivity by serotype).

## What the existing (Uvira) app provides — reuse vs. replace

| Capability | File(s) | Plan |
|---|---|---|
| xPONENT CSV parser | `parse_xponent.py` | **Edit** — generalize well-position parsing to A–P / 1–24; confirm plate-ID extraction on Bangladesh batch strings. |
| Well classification (PC/NC/specimen) | `classify.py` | **Rewrite patterns** — no input file; classify from `Sample` name: Background=`^Background`, NC=`Negative`, PC=`^Pilot Control:` (minus NC), specimen=rest. Add pool-name + dilution parsing. |
| Bead-count QC | `qc_beads.py` | **Reuse + relabel** — logic stays; card copy and thresholds clarified/made configurable. |
| Standard-curve 4PL fitting | `qc_standard_curve.py` | **Extend to multi-pool** — fit 4PL per (pool × antigen) with per-pool dilution series; add priority filtering; expose `reportable_range` for the linear-range square. Revive multi-pool slug logic (mpox-style). |
| Multi-pool history slugs | `qc_history.py`, `pipeline.py` | **Revive** — Uvira dropped per-pool slugs; Bangladesh needs them back (one history per pool). |
| Background QC | `qc_background.py` | **Edit** — default max-MFI → 300; add per-plate & previous-plate IQR; drop mean/max columns + max flag from table. |
| Cross-plate history | `qc_history.py`, `pipeline.py` | **Reuse** — already persists background/specimen/std/nc history per output dir; reused for IQR comparison. |
| Report generator | `report.py`, `templates/report.html` | **Edit heavily** — section reorder, 384 plate map (shape-coded + hover + scroll), bead-count relabel, background IQR plot + folded table, priority-antigen curves, interactive All-Curves Overview, folded picker, range-matrix axis change. |
| Settings page | `templates/web/settings.html`, `config.py`, `settings.py`, `app.py` | **Edit** — add priority-pathogen list, background max-MFI, and make all flag thresholds editable. |
| Branding / paths | everywhere | **Edit** — rename "Uvira Luminex QC" → "Bangladesh Serosurveillance Luminex QC"; `RESULTS_DIR_NAME`; window/report titles; README/SPEC; .spec files; .Rproj. |

---

## To-Do

Status legend: `[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked.

### 11. Docs, downloads, master export, cleanup — DONE (Session 11)
- [x] **README.md + SPECIFICATION.md** rewritten for the Bangladesh 202-plex /
      384-well / High-PMT / multi-pool assay (sections, pools, auto pool-select,
      outputs, settings, build). No Uvira/MPXV copy.
- [x] **Per-plate download CSVs fixed**: report links point to
      `/download/specimens/<f>`, but only `specimens_*.csv` was mirrored to
      `specimens/` — the rest live in `reports/`. `download_specimens` now checks
      both dirs. Verified all 9 links return 200.
- [x] **Clean master CSV (with RAU)**: new per-plate `results_<plate>.csv`
      (`_build_clean_results`) — plate, well, sample_id, matrix, analyte, pool,
      mfi, RAU, status, censored. `/export/all` now leads with a concatenated
      **results** sheet (+ specimens / curve params / curve data / nc_levels);
      fixed the NC history filename (`nc_well_history.json`). Verified via Flask.
- [x] **Code cleanup**: removed dead `_make_nc_heatmap`, `get_kit_control_names`,
      `KIT_CONTROLS`/`ALL_BEADS`, `PC_CV_THRESHOLD`/`pc_cv_threshold`,
      `STANDARD_DILUTIONS` (+ the dead `standard_dilutions` settings handler) and
      the unused `replicate_qc`/`kit_controls` report params. Imports clean.

### 0. Project setup & rebranding
- [x] Fork folder from `uvira-luminex-qc` → `bangladesh-serosurveillance-luminex-qc`.
- [x] Create this tracking doc (`BANGLADESH_TODO.md`) with the plan.
- [x] Rebrand (Session 1): `RESULTS_DIR_NAME` →
      `bangladesh-serosurveillance-luminex-qc-results`; app/window/report/settings
      titles; download filename prefixes; `.spec` files renamed + internal names;
      `APP_VERSION = "0.1.0-bangladesh"`; assay name/description; pyproject; GitHub
      URL. `report.py` module docstring.
- [x] Rewrite `README.md` + `SPECIFICATION.md` for the 202-plex / 384-well /
      Bangladesh context (remove Uvira/MPXV-specific copy entirely). DONE
      Session 11.
- [x] Legacy docs moved to `legacy/` (UVIRA_TODO + PLATE_RUN_FINDINGS .md/.html).
      Pilot CSVs copied to `tests/fixtures/`.

### 1. 384-well + multi-pool foundation (do first)
- [x] Generalize well parsing in `parse_xponent.py` `_parse_well_from_location`
      to accept rows A–P and columns 1–24.
- [x] Plate-geometry inferred from the data (snaps to 96 or 384) in `report.py`
      `_make_plate_layout_overview` (replaces hard-coded 8×12). *(Full shape-coded
      redesign is Section 2; this is the geometry groundwork.)*
- [ ] Audit remaining heatmaps for 384 scale. *(Bead/range/NC heatmaps already use
      first-seen well order + dynamic height, so they render; revisit visual
      density in Sections 3/6.)*
- [x] **Rewrote `classify.py` patterns** for Bangladesh sample names
      (Background0 / Negative / Pilot Control / `{id}_r3_{Serum|DBS}`), checked
      background→nc→pc→specimen with `re.search`. Defaults in `config.py`,
      editable in Settings.
- [x] **Pool + dilution parser** (`_parse_pc` in `classify.py`): extracts pool
      label (parenthetical stripped), dilution (`1:N`), or concentration
      (`N ng/mL` → `pc_x_kind='concentration'` for HlyE); flags single-point
      controls (`pc_single_point`). Verified on both pilots: pools, dilutions,
      x-kinds, single-points all parse correctly.
- [x] **Multi-pool standard-curve fitting + per-pool history** working. Single-
      point pools dropped from fitting; pools with <4 dilution points → NO_FIT
      (no crash). Per-pool `fit_history_*` / `std_curve_history_*` JSON written.
      Verified: Dengue pool fits its DENV antigens (15/15 on subset), cholera/
      typhoid pool does not (1/15) — confirms the priority-pathogen concept.

- [x] **Auto antigen→pool selection** (`select_pool_per_antigen`): each antigen
      is scored against the curve of the pool meant to calibrate it. Pathogen
      group parsed from the antigen name (dengue / cholera / typhoid), matched to
      pools by name; **ties and unmatched antigens broken by best fit (fit_ok then
      highest R²)**. Runs as the default; overridable via
      `config['panel']['pool_antigen_overrides']` (antigen→pool) once the team
      signs off. `compute_in_range_table` + `compute_concentrations` now use this
      per-antigen mapping instead of `pools[0]`. R² stored in each fit result.

> **Section 1 verification (Session 1):** both pilots parse (Plate 1: 90 PC /
> 4 BG / 4 NC / 248 specimen wells; Plate 2: 58 / 4 / 4 / 250). Full 200-antigen
> × multi-pool fit + history completes. `generate_report` runs on the multi-pool
> /384 data. Auto pool-selection verified: DENV NS1 → Dengue pool (R²≈0.999),
> DENV VLP → Orpal pool (best-fit tiebreak), HlyE → HlyE pool, CtxB → cholera
> pool; plain `rau` for a DENV antigen correctly equals its selected pool's AU.

### 2. Plate Overview section (rebuild) — DONE (Session 2)
- [x] **Metadata table** (replaced inline header grid): Plate ID, Batch, Run
      date, Operator, Instrument (+ SN), Operating mode (with Low-PMT badge),
      CSV file, Panel.
- [x] **Number cards**: total wells, PC (standard) wells, NC wells, specimen
      wells, antigens analysed — from `plate_counts` in `report.py`. Verified on
      Plate 1: 346 / 90 / 4 / 248 / 200.
- [x] **384 plate map** rebuilt as a shape-coded Plotly scatter:
      circle = PC/standard, ✕ = NC, square = specimen, open square = background.
      No sample labels; hover shows well position + sample ID + type. Geometry
      inferred (96 or 384), equal-aspect, wrapped in a horizontally/vertically
      scrolling container (max-height 560px).

### 3. Bead Count section (move to 2nd; relabel) — DONE (Session 3)
- [x] Reordered: Bead Count now comes immediately after Plate Overview, before
      Background QC (template blocks swapped + figure-build order updated in
      `report.py` for the Plotly embed-first invariant; section comments
      renumbered 1–9).
- [x] Rewrote the four cards with self-explanatory copy (thresholds live from
      settings): "Antigens flagged (≥X% of wells have either 30–49 beads or
      <30 beads)", "Specimens flagged (≥X% of antigens …)", "Overall cells with
      bead count <30 (red cells)", "Overall cells with bead count 30–49 (yellow
      cells)". Numbers come from `bead_count_min`/`bead_count_warn`/
      `problem_fraction_threshold`. Cards forced to a 4-column row.
- [x] **Bead-count heatmap**: x-axis shows the **well location only** (no sample
      ID); hover shows Antigen, Well, Sample, Bead count, Tier.
- [x] **Wide-matrix legibility + frozen antigen labels**: matrix rendered as two
      row-aligned panes — a fixed antigen-label column on the left (frozen) and
      the heatmap (wells) in a horizontal-scroll pane beside it; both share an
      outer vertical-scroll box. Fonts 7px, cells 10px rows × 9px cols. Page
      width unaffected (`min-width:0` on the content grid track + on the scroll
      pane). Label pane uses a wide left margin so long antigen names aren't
      clipped and sit flush against the cells.
- [x] Heatmap + problem tables render at 384 scale.

### 4. Background QC section (after Bead Count; substantial edits) — DONE (Session 4)
- [x] **Default max-MFI threshold → 300** (`bg_max_mfi`) in `config.py`,
      `qc_background.py`, `pipeline.py`, `report.py` fallback, and `settings.html`.
- [x] **Rewrote the "How Background QC works" description**: dropped the
      confusing mean/max points; now describes within-plate spread (individual
      MFIs, SD, %CV) and the this-plate-vs-history IQR comparison, and states
      that formal pass/fail flagging is still in development (max-MFI is a
      tracked reference only). No stale copy left.
- [x] **Overview plot redesigned** (`_bg_overview_iqr` + branch in
      `_make_background_overview_plot`): < 3 plates → existing dot scatter;
      ≥ 3 plates → grey vertical bar = previous-plates IQR (Q1–Q3, current
      excluded) + current-plate mean dot; dots **outside the IQR flagged** in
      red (provisional, "flagging in development" note). Verified with a
      synthetic 3-plate history.
- [x] **Per-antigen table rebuilt + folded** (click to expand, scrollable both
      ways). Dropped Mean MFI, Max MFI, and the MAX/CV flag column. Columns now:
      Analyte → n wells → Individual MFIs → SD → %CV → IQR current plate (Q1–Q3
      of this plate's Background wells) → IQR previous plates (Q1–Q3 of per-plate
      mean across earlier plates). Flags deferred — noted in code + UI.
- [x] Cards replaced with neutral info (antigens w/ Background data, Background
      wells this plate, previous plates in history) — no premature pass/fail.

### 5. Standard curves — multi-pool + priority-pathogen concept — DONE (Session 5)
- [x] **Multi-pool fitting** (Section 1): 4PL per (pool × antigen); single-point
      controls excluded from fitting.
- [x] **Settings: priority pathogens** — new textarea (`panel.priority_antigens`,
      default empty = all); wired through `settings.html`, `app.py`, and a
      `get_priority_antigens` getter. Persists to YAML.
- [x] **Per-antigen selected fit** (`_build_selected_fits`): each antigen shown
      against its auto-selected pool's curve (pool name injected); a single
      `selected_fits` dict feeds the Summary, Overview, and Picker.
- [x] **Standard Curve Summary** filtered to **priority antigens** (default all),
      with a new **Pool** column and a note that curves are fit for all antigens.
- [x] **All Curves Overview — interactive** (`_make_curve_grid_interactive`):
      Plotly small-multiples for priority antigens with hover, current-plate
      specimen **rug** (status-coloured), **linear-range green square**, red
      4PL line, blue observed points, **red triangles** for out-of-tolerance
      standards, **✕** for a dropped point. Falls back to a static grid (still
      with the square) above 48 panels (unfiltered default).
- [x] **Standard Curve Picker**: covers **all** antigens (each via its selected
      pool fit); **folded by default** with a "review only — only priority
      curves are interpretable" disclaimer.
- [x] Linear-range square **now also in the Standard-Curve Picker** (Session 9):
      per-antigen green reportable-range rectangle (log10 coords) appended to the
      rug-separator base shapes and swapped on typeahead via
      `Plotly.relayout(DIV,"shapes",…)`.

### 6. Standard-Curve Range Matrix + Serum/DBS pairing — DONE (Session 6)
- [x] Range Matrix rebuilt with the **frozen antigen-label** + horizontal-scroll
      pattern (shared `_frozen_label_heatmap` helper). Top axis shows the **well
      location only** (no sample-ID); hover shows Antigen, Well, Sample, Status
      (Below/In/Above range, No fit). Uses `sample_id` when present, else
      `sample_name`.
- [x] **Paired Serum-vs-DBS comparison** (`_make_serum_dbs_comparison`): folded
      sub-section under the Range Matrix. Parses `{id}_r3_{Serum|DBS}`
      (case-insensitive), pairs per person × antigen, and plots Serum MFI vs DBS
      MFI (scattergl) with a y=x reference line and per-point hover. Specimens
      still listed individually elsewhere.

### 7. Settings page — make thresholds editable — DONE (Session 7)
- [x] Priority-pathogen list (Section 5).
- [x] Background max-MFI threshold (default 300).
- [x] Bead-count thresholds (min/warn) — labels clarified ("RED below" / "YELLOW
      below"); read live from config in `qc_bead_counts`.
- [x] Problem-fraction (≥X%) threshold — present; read live in pipeline + report.
- [x] Background %CV threshold — present (reference only).
- [x] Recovery tolerance — present; drives LLOQ/ULOQ.
- [x] **Audit**: confirmed every threshold is read from config (bead via
      `qc_bead_counts`, problem-fraction/bg-cv/bg-max/recovery via
      `qc_thresholds`, priority via `panel`); none hard-coded in the report.
- [x] **Cleanup**: removed the now-unused "Standard Dilutions" field (dilutions
      are parsed from sample names per pool) and replaced it with an explanatory
      note; updated Well-Classification labels/copy for Bangladesh naming; marked
      Background thresholds as "reference (flagging in development)".
- [x] Verified Settings round-trip with a Flask test client (GET renders, POST
      persists all thresholds + priority list, reset restores defaults).

### 8. Descriptions audit (cross-cutting) — DONE (Session 8)
- [x] Reviewed every section's explanatory text against current behavior. Fixed:
      NC QC (Bangladesh `Negative` pattern, `Background0`, pre-2019 NA plasma, NC
      flagging-in-development note); Background QC download desc (flags are
      reference-only); Range-Matrix download desc (auto-selected pool; dropped
      Uvira barcode/patient_id/box_id wording); upload page (input-file + barcode
      map marked optional / not needed for Bangladesh).
- [x] Confirmed no stale Uvira / MPXV / MagPix / RENAMED / Row-A / Standard1 /
      12-plex copy remains in report.html, index.html, settings.html.

### 9. Validation
- [ ] Obtain a representative Bangladesh 384-well xPONENT CSV (+ input file +
      barcode map) and validate end-to-end.
- [ ] Verify plate map, well counts, and classification on real 384 data.
- [ ] Regression-check the Uvira fixtures still process (96-well path).

### 10. Deferred / future work (noted, not in this scope)
- [x] **PC Replicate Variability** — BUILT (Session 12). Standards are run in
      duplicate; `qc_pc_replicates` computes the %CV between the two replicate
      wells per (pool × antigen × dilution), flags points > `pc_cv_threshold`
      (default 0.20, editable in Settings), and the report shows a "PC replicate
      variability" subsection (cards + folded flagged-points table) with a
      `pc_replicates_*.csv` download.
- [~] Negative Control levels section — **reworked to the legacy MPOX style**
      (Session 9): per-antigen "NC MFI across plates" small-multiples (current
      plate red) + folded "NC details for this plate" (mean-MFI-by-analyte bar +
      Well/Analyte/MFI table). Deeper NC flagging (thresholds, drift) still TBD.
- [ ] Decide background-IQR out-of-range flagging rule.
- [ ] Decide final flag rules for the Background QC table.
- [ ] **Standard-Curve Picker performance at full panel scale.** Generating the
      full ~200-antigen report is slow (minutes); the picker builds a very large
      multi-trace Plotly figure (all antigens × pools + historical overlays).
      With a priority list set everything is fast. Optimize later (e.g. limit/
      lazy traces, or build the picker only for a capped set). Logged Session 5.
- [x] Add the green linear-range square inside the Picker's own curve panel —
      DONE Session 9.

---

## Decisions log
- **2026-06-01**: New project created as a fork of `uvira-luminex-qc`. Target
  assay is 202-plex on a 384-well plate for Bangladesh national
  serosurveillance. Plan drafted for review (this document).
- **2026-06-01**: Pilot CSVs parsed → assay is **multi-pool** (revive mpox-style
  per-pool fitting/history); 384-well A–P × 1–24; classify from sample name (no
  input file). Linear-range styling locked from screenshots.
- **2026-06-01**: Study protocol received. Production = 202-plex (pilots reduced
  by reagent shortage; panel auto-derived). High PMT only. Pool intents + plate
  well-budget recorded. Legacy docs moved to `legacy/`.
- **2026-06-02**: Plan finalized for build. HlyE → ng/mL axis; Serum/DBS = two
  specimens + folded paired comparison (Section 6); single-point controls =
  reference markers (no fit); no White-vs-RC view; bead-count heatmap loses the
  top sample-ID labels (keeps well location, sample id in hover). Priority
  antigens = fit-all + user Settings filter. Ready to start Sections 0 & 1.

## Open questions for the user
**Resolved 2026-06-01:** screenshots received (green linear-range square + red
out-of-tolerance triangles + "×" excluded point — see Section 5); priority-
pathogen default = all antigens; IQR = Tukey Q1–Q3 on per-plate mean background
MFI per antigen, previous-plate IQR excludes the current plate, current plate is
the overlaid dot; flag current-plate dot when outside historical IQR (with a
"more BG flags in development" note); 384 layout confirmed (A–P × 1–24); keep
legacy docs in a `legacy/` folder.

**Resolved 2026-06-01 (study protocol):** production is **202-plex**; pilots ran
fewer beads due to reagent shortage (auto-derive panel, brand as 202). High PMT
only. NC = pooled pre-2019 North American plasma (`Negative 0`/`Negative 49` —
treat both as NC). Pool intents now known (cholera mAbs → OSP/CtxB; HlyE →
S. typhi HlyE; Dengue pool + individual dengue + ORPAL → DENV; Cholera High/Low =
range markers). Serum & DBS are both SeroChit specimens (124 each).

**Resolved 2026-06-02:**
- **Priority antigens**: always fit every pool × antigen; the priority list is a
  *display filter* the user sets in Settings (default = all). Exact list TBD by
  team but does not block the build.
- **No White-vs-RC concordance view** in the QC tool — that's a separate
  analysis done outside this app.
- **Dilution x-axis** (FINAL): `1:N` is the curve x-axis. **HlyE** is fit on its
  own **ng/mL concentration axis**, shown in the same curve grid with different
  x-units. Everything else uses dilution.
- **Serum vs DBS** (FINAL): treated as **two independent specimens**, clearly
  labeled `{id} (Serum)` / `{id} (DBS)` (casing normalized). **Plus** a
  **paired serum-vs-DBS comparison in a folded sub-section/tab** (per-person
  serum MFI vs DBS MFI). See Section 6.
- **Single-point controls** (FINAL): Cholera High/Low and combined-mAb
  singletons shown as **reference markers**, no curve fit.

**Resolved 2026-06-02 (auto pool-selection):** specimens are scored against the
pool that calibrates each antigen, auto-derived by parsing the pathogen name and
tie-breaking by best fit (default on). Team can later override per antigen and
confirm the prefix→pathogen rules in Settings.

**Still open (non-blocking):**
1. **Pool → priority-antigen mapping (exact lists)**: **Decision (Session 13):
   default mode is `per_pool` — fit & show a curve for EVERY (pool × antigen),
   NO matching or auto-selection.** Auto-select remains available as a Settings
   option. Caveat (documented in the report): pools have different dilution
   ranges (Dengue 1:1k–16M, ORPAL 1:100–102k, OSP/cTxB 1:1–16k, HlyE ng/mL), so
   RAU is anchored per pool and not comparable across pools; specimen RAU/range
   use a single configurable scoring pool. Once the team confirms the
   pool→antigen mapping, switch to a per-antigen intended calibrator.

---

## Session History

### Session 15 — 2026-06-02 (CI release workflow for Mac/Windows builds)
- Rewrote the inherited `.github/workflows/build.yml` (was still MPXV-branded:
  wrong spec filenames, `MPXV Luminex QC.app`, MPXV zip/artifact names) for the
  Bangladesh app: builds `bangladesh-serosurveillance-luminex-qc.spec` (macOS
  `.app`, ad-hoc codesigned + zipped) and `…-win.spec` (Windows folder zipped),
  uploads artifacts, and on a `v*` tag publishes a GitHub Release with both zips.
  Also runs on `workflow_dispatch`.
- Added `src.qc_pc_replicates` to the `hiddenimports` of both `.spec` files (new
  module this project; would otherwise risk a missing-import in the frozen app).
- Verified all build inputs exist (run.py, make_icon.py, icons .icns/.ico,
  templates, static/vendor, SPECIFICATION.md) and the workflow YAML is valid.
- Note: builds run on GitHub's macOS/Windows runners — push the repo + a `vX.Y.Z`
  tag (or run the workflow manually) to produce the downloadable apps. No native
  build was possible in this Linux sandbox.
- Added a **"Download & install"** section to the README (Releases link + macOS
  right-click-Open / `xattr` and Windows SmartScreen first-launch steps).
- Smoke-tested: app imports + boots (home + settings pages 200). All session
  changes are still **uncommitted/local**; CI has not run yet (no tags).

### Session 14 — 2026-06-02 (Regex pool-assignment rules in Settings)
- Documented how `auto_select` works (antigen-name pathogen group → pools whose
  name targets that group → best-fit tie-break → fallback).
- Added a **Settings "Pool assignment rules"** textarea: `"<regex> => <pool>"`,
  one per line, first match wins. In `select_pool_per_antigen` the order is now:
  (1) exact `pool_antigen_overrides`, (2) **user regex rules** (`_parse_pool_rules`),
  (3) built-in pathogen heuristic, (4) best-fit fallback. Lets the lab define the
  antigen→pool mapping explicitly without code (and sidesteps the keyword
  heuristic's edge cases). Config `panel.pool_assignment_rules` + app.py parse.
- Verified: a rule `ARB_DENV.* => Orpal pool` forces all DENV antigens to ORPAL;
  `RES_Ade.* => Dengue pool` assigns antigens the heuristic wouldn't match;
  settings round-trip + reset OK.

### Session 13 — 2026-06-02 (Per-pool curve mode — no matching/auto-select)
- **Decision reversed**: do NOT auto-select a pool per antigen for the interim.
  New default **`pool_mode = "per_pool"`**: a 4PL is fit and shown for EVERY
  (pool × antigen), with no pathogen matching and no best-fit pick.
  - Standard-Curve Summary → one row per (pool × antigen) (Pool column; %-in-range
    omitted since it's a single-pool metric).
  - All-Curves Overview → one curve grid **per pool** (legacy ITM-style), each
    with its hover / rug / linear-range square.
  - Picker / cross-run / Range Matrix / RAU → scored against a single
    **scoring pool** (`panel.scoring_pool`; blank → the pool with the most
    fit_ok antigens, via `default_scoring_pool`). Per-pool AU columns remain in
    specimens CSV; clean results uses the scoring pool.
- **Settings**: added `pool_mode` (per_pool | auto_select) dropdown + `scoring_pool`
  field; wired through `app.py`; verified round-trip + reset → per_pool.
- Refactor: `compute_in_range_table` / `compute_concentrations` /
  `_build_clean_results` now take an explicit `pool_map`; `build_pool_map`
  applies the mode. `auto_select` mode preserved (banner explains each mode).
- Fixed a `html` name-shadowing bug (`html = template.render` shadowed the
  `import html` used by the per-pool heading escape) → render var renamed.
- Verified both modes render on the pilot (per-pool: 5 pool grids + per-(pool×
  antigen) summary; auto_select: single grid + Pool column).
- **Bug fix**: in per-pool mode every pool's interactive grid was emitted with
  the same Plotly div id (`fig-curve-grid`), so only the first pool's grid
  rendered and the rest were blank. Threaded a unique `div_id` per pool
  (`fig-curve-grid-{i}`) through `_make_curve_grid` → all pool grids now render.

### Session 12 — 2026-06-02 (PC replicate QC + pool-group fix + threshold restore)
- Confirmed standards run in **duplicate** (2 wells per pool × dilution).
- Restored `PC_CV_THRESHOLD` (default 0.20) — now a real, consumed threshold —
  + Settings field + POST handler.
- New **`qc_pc_replicates`** module: %CV between duplicate standard wells per
  (pool × antigen × dilution); per-point table + per-(pool × antigen) summary.
  Wired into the pipeline (`pc_replicates_*.csv` export) and a "PC replicate
  variability" subsection in the report (cards + folded flagged-points table +
  download). Verified end-to-end + settings round-trip.
- **Bug fix**: `_antigen_group` was tagging Borrelia `TBD_OspA`/`OspC` as
  *cholera* via a bare "OSP" substring. Cholera now keys on the `CHO_` prefix /
  cholera-specific tokens (CtxB/Inaba/Ogawa/cholera/vibrio); verified TBD_Osp*
  → None, CHO_Inaba_OSP → cholera.
- Clarified the pool-column question: full-panel selected-pool distribution is
  150 Dengue / 44 Orpal / 2 Anti-OSP&cTxB / 1 HlyE / 1 combined — the cholera/
  typhoid pools map only to their targets; the rest fall back to the broadly-
  reactive pooled sera. (Earlier "only Dengue/Orpal" was a 12-antigen preview
  artifact.)

### Session 11 — 2026-06-01 (Docs + downloads + master CSV + cleanup)
- Rewrote README.md + SPECIFICATION.md for Bangladesh (202-plex / 384-well /
  High PMT / multi-pool; sections, pools, auto pool-selection, outputs, build).
- Fixed all per-plate CSV download links (`download_specimens` now serves from
  both `specimens/` and `reports/`) — verified 9/9 return 200.
- Added clean master `results_<plate>.csv` (`_build_clean_results`: well ×
  antigen with pool, MFI, **RAU**, status, censored, Serum/DBS matrix) and made
  `/export/all` lead with a concatenated **results** sheet; fixed NC history
  filename. Verified the workbook via a Flask test client.
- Code cleanup: removed dead `_make_nc_heatmap`, `get_kit_control_names`,
  `KIT_CONTROLS`/`ALL_BEADS`, `PC_CV_THRESHOLD`, `STANDARD_DILUTIONS`, the dead
  `standard_dilutions` settings handler, and unused `replicate_qc`/`kit_controls`
  report params. All modules import cleanly.
- This completes the planned scope (Sections 0–11). Remaining items are the
  deferred/in-development ones in Section 10 (Background/NC flagging rules, PC
  replicate variability, picker performance, team pool→antigen mapping).

### Session 10 — 2026-06-01 (Picker rug alignment + NC controls split)
- **Picker rug/curve alignment**: curve and rug panels now pinned to the SAME
  explicit per-antigen log10 y-range (`_y_range_for`, computed from standards +
  current/historical specimen MFIs), set on load and via
  `Plotly.relayout({yaxis.range, yaxis2.range})` on each pick — guarantees a
  given MFI lands at the same height in both panels.
- **Picker linear-range square**: reimplemented as a per-antigen filled
  ("toself") trace toggled by the existing visibility scheme (the layout-shape +
  relayout approach wasn't rendering); `n_per_analyte` 2P+6 → 2P+7.
- **NC reworked per user decisions**: Negative 0 and Negative 49 kept **separate**
  (`_nc_control` parses the control; duplicate wells averaged within each
  control). Across-plate panels = static grid over **all** antigens, one coloured
  line per control, current-plate markers ringed. NC bar = grouped bars per
  control. NC table gained a **Control** column. Clarified the "dots = plates"
  point (preview used synthetic plates).
- Verified on Plate 1: 4 NC wells → Negative 0 / Negative 49; panels, grouped
  bar, and table all split by control.

### Session 9 — 2026-06-01 (Picker linear-range square + NC rework)
- **Picker linear-range square**: added a per-antigen green reportable-range
  rectangle to the Standard-Curve Picker (log10 coords on the log axes),
  appended to the static rug-separator shapes and swapped per antigen via
  `Plotly.relayout(DIV,"shapes",…)`; description updated.
- **NC QC reworked to the legacy MPOX style**: replaced the two purple heatmaps
  with (1) per-antigen "Negative Control MFI across plates" small-multiples
  (`_make_nc_history_plot` now a subplot grid; line + markers across plates,
  current plate red; bounded to priority antigens, capped at 48), and (2) a
  folded "NC details for this plate" containing a mean-NC-MFI-by-analyte bar
  (`_make_nc_bar`, scrollable) + a Well/Analyte/MFI table (`_format_nc_table`).
  Banner rewritten accordingly.
- Verified: picker carries shapes + relayout; NC panels/bar/table render; old
  `fig-nc-heatmap` removed.
- Remaining: README/SPEC rewrite for the Bangladesh context.

### Session 8 — 2026-06-01 (Section 8: Descriptions audit)
- Swept all report/upload copy for accuracy and stale Uvira/MPXV references:
  - NC QC banner rewritten (Bangladesh `Negative` pattern, `Background0`,
    pre-2019 NA plasma; "deeper NC QC in development" note; updated "no NC" copy).
  - Downloads: Background QC desc (flags reference-only), Range-Matrix desc
    (auto-selected pool; removed barcode/patient_id/box_id Uvira wording).
  - Upload page: input-file + barcode-map fields marked optional / not needed
    (wells classified from the sample name; IDs in `{id}_r3_{Serum|DBS}`).
- Verified report renders and a grep sweep finds no remaining
  Uvira/MPXV/MagPix/RENAMED/Row-A/Standard1/12-plex copy.
- Next: rewrite README.md + SPECIFICATION.md for the Bangladesh 202-plex / 384-
  well / multi-pool context (Section 0 leftover).

### Session 7 — 2026-06-01 (Section 7: Settings audit)
- Confirmed all flag thresholds are editable AND read live from config: bead
  RED/YELLOW (via `qc_bead_counts`), problem-fraction, background %CV, background
  max-MFI, recovery tolerance (via `qc_thresholds`), priority antigens (via
  `panel`). Nothing hard-coded in the report path.
- Cleaned the Settings page: removed the unused "Standard Dilutions" field
  (dilutions now parsed per-pool from sample names) → replaced with a note;
  rewrote Well-Classification labels/help for Bangladesh naming
  (`Background0` / `Pilot Control:` / `Negative` / `{id}_r3_{Serum|DBS}`);
  clarified bead labels ("RED below"/"YELLOW below"); marked the two Background
  thresholds as reference-only (flagging still in development).
- Verified the full Settings round-trip with a Flask test client (GET renders,
  POST persists every threshold + the priority list, reset restores defaults).
- Next: Section 8 (descriptions audit across all sections), then README / SPEC
  rewrite for the Bangladesh context.

### Session 6 — 2026-06-01 (Section 6: Range Matrix + Serum/DBS)
- Added shared **`_frozen_label_heatmap`** helper (frozen antigen-label pane +
  horizontal-scroll well pane); the Range Matrix now uses it — bare well-location
  top axis, hover = Antigen / Well / Sample / Status. (Bead matrix keeps its own
  equivalent inline version.)
- **`_make_serum_dbs_comparison`**: folded Serum-vs-DBS scatter (scattergl) under
  the Range Matrix — pairs `{id}_r3_{Serum|DBS}` per person × antigen, y=x
  reference, per-point hover. Hidden when no matched pairs exist.
- Clarified earlier preview confusion (Section 5): the "handful of antigens" was
  a fast-preview artifact (only ~10–24 antigens fit to dodge the 45 s tool cap);
  the real pipeline fits all ~200 (198/200 get a usable fit). Logged a picker
  performance follow-up (full-panel report is slow).
- Verified: range matrix frozen panes + enriched hover; serum/dbs section builds
  and pairs on the pilot specimens.
- **Follow-up (Section 6):** upgraded both the bead matrix and the range matrix
  to full **freeze panes** — promoted the helper to `_freeze_pane_heatmap`
  (frozen corner + frozen column header for well positions + frozen row header
  for antigens + scrolling body), with a small JS shim syncing the body's
  horizontal scroll → column header and vertical scroll → row header. Now both
  the antigen names AND the well positions stay visible while scrolling either
  way. Bead matrix retains its well-type group separators.
- Next: Section 7 (Settings completeness — confirm all flag thresholds editable)
  and Section 8 (descriptions audit), then README/SPEC rewrite.

### Session 5 — 2026-06-01 (Section 5: Standard curves)
- **Priority-pathogen setting**: `panel.priority_antigens` (default empty = all)
  added to config, `settings.html`, `app.py` POST, and `get_priority_antigens`.
- **`_build_selected_fits`**: per-antigen fit from its auto-selected pool (pool
  injected), shaped as a single-pool dict; one `selected_fits` feeds Summary /
  Overview / Picker. Priority list derived (panel order; empty = all).
- **Standard-Curve Summary**: now priority-filtered, with a **Pool** column and
  a "fit for all antigens / curves shown for priority" note.
- **All-Curves Overview** rebuilt: interactive Plotly small-multiples
  (`_make_curve_grid_interactive`) for ≤ 48 panels — hover, current-plate
  status-coloured **rug**, green **linear-range square**, red 4PL line, blue
  observed points, red-triangle out-of-tolerance standards, ✕ dropped point.
  `_make_curve_grid_static` keeps the matplotlib grid (now with the square) for
  larger/unfiltered sets. Linear-range geometry via `_linear_range_box`.
- **Standard-Curve Picker** folded by default with a "review only" disclaimer;
  now spans all antigens via their selected-pool fits.
- Verified: default (all) shows the Pool column + note; priority filter narrows
  the Summary/Overview to the chosen antigens; interactive grid carries the
  square + rug + out-of-tolerance markers; picker collapsed with disclaimer.
- Follow-up: add the linear-range square inside the picker curve too (deferred);
  PC Replicate Variability + NC levels still later (Section 9 / general).
- Next: Section 6 (Range Matrix axis change + Serum/DBS paired sub-section),
  then Section 7/8 (settings completeness + descriptions audit).

### Session 4 — 2026-06-01 (Section 3 finalize + Section 4: Background QC)
- Finalized Section 3 (bead matrix frozen labels + sizing) per user approval.
- **Section 4 — Background QC overhaul:**
  - Max-MFI default 100 → **300** everywhere (config, qc_background, pipeline,
    report fallback, settings.html).
  - `qc_background_levels` now returns the **individual Background-well MFIs**
    plus the current-plate **IQR (Q1/Q3)**; mean/sd/cv/max retained for the
    plot + history. Flagging columns kept for reference only (display deferred).
  - **Overview plot**: new `_bg_overview_iqr` — ≥3 plates shows previous-plate
    IQR bars (current excluded) + current-plate dot, outside-IQR dots flagged
    red; <3 plates keeps the dot scatter. `_make_background_overview_plot`
    branches on plate count.
  - **Description rewritten** (clear, accurate; no stale mean/max copy; states
    flagging is in development).
  - **Per-antigen table**: folded by default, scrollable; columns Analyte /
    n wells / Individual MFIs / SD / %CV / IQR current plate / IQR previous
    plates. Mean/Max/flag columns removed.
  - Cards now neutral (no premature pass/fail).
  - Verified: single-plate report renders (table + columns + note); ≥3-plate
    IQR overview + previous-plate IQR column verified with a synthetic history.
- Next: Section 5 (standard curves — multi-pool priority display, interactive
  All-Curves Overview with rug + linear-range square, folded picker).

### Session 3 — 2026-06-01 (Section 3: Bead Count)
- Reordered report: **Plate Overview → Bead Count → Background QC → …**
  (swapped the template `<details>` blocks, renumbered section comments 1–9, and
  reordered the figure builds in `report.py` so `bead_heatmap` is built before
  `bg_overview` — preserves the "Plotly.js embeds on first call" DOM invariant).
- Rewrote the four Bead Count cards in plain language (counts vs <30 / 30–49
  thresholds and the ≥X% flag, all from settings); fixed to a 4-column row.
- Bead-count heatmap: dropped the sample-ID text from the top axis (well
  location only); hover now shows Antigen / Well / Sample / Bead count / Tier.
- Left "red / yellow cell" wording only where it correctly names the heatmap
  tiers (the detail list + download descriptions), per the colour legend.
- Verified on Plate 1: DOM order correct, new card copy present, hover enriched.
- Plate Overview review fixes from last round also confirmed (compact 6-card row,
  top-centered plate-map legend, trimmed map description).
- **Review fixes (Section 3):** the wide bead heatmap was stretching the whole
  page — fixed with `min-width:0` on the `1fr` content grid track (and on the
  scroll pane). Reworked the matrix into a **frozen left antigen-label pane +
  horizontally-scrolling heatmap** (per user choice "antigens left, freeze
  them"), shrank fonts to 7px and cells to 10×9px, and fixed the large
  label↔cell gap (left-margin sizing) so long antigen names aren't clipped.
- Section 3 finalized and approved.
- Next: Section 4 (Background QC overhaul — max-MFI default 300, rewritten
  description, IQR overview plot, folded/scrollable table with individual MFIs +
  current/previous-plate IQR columns).

### Session 2 — 2026-06-01 (Section 2: Plate Overview rebuild)
- **Metadata table**: replaced the inline `meta-grid` with a table — Plate ID,
  Batch, Run date, Operator, Instrument (+SN), Operating mode (Low-PMT badge
  retained), CSV file, Panel.
- **Count cards**: total / PC / NC / specimen wells + antigens, computed as
  `plate_counts` in `generate_report`. Verified on Plate 1 (346/90/4/248/200).
- **Plate map** (`_make_plate_layout_overview`) fully rebuilt: shape-coded Plotly
  scatter (● PC, ✕ NC, ■ specimen, ▫ background), no labels, hover = well +
  sample ID + type, equal aspect, geometry auto (96/384), inside a both-axis
  scrolling container. Legend across the top.
- Verified: report renders with metadata table, correct card counts, and the
  scrollable shape-coded map.
- **Review fixes (Session 2)** from user screenshot: removed the redundant
  subtitle line under the title (it duplicated the metadata table); **removed the
  excluded-analytes concept** — emptied the leftover MPXV/Uvira default
  (`EXCLUDED_ANALYTES = []`), removed the Plate Overview banner and the stray
  excluded-analyte sentences in the Background QC / Standard-Curve descriptions;
  added a **Background (blank) wells** card so the cards reconcile to the total
  (90 PC + 4 NC + 248 specimen + 4 background = 346).
- Also explained the multi-pool auto pool-selection on the report (banner in
  Standard-Curve Summary + note in Range Matrix) — see Section 1 entry.
- Next: Section 3 (Bead Count — move above Background QC, relabel cards, drop
  top sample-ID labels on the heatmap, keep well location + richer hover).

### Session 1 — 2026-06-01 (Section 0 rebranding + Section 1 foundation)
- **Section 0 (rebranding)** complete: `config.py` (version `0.1.0-bangladesh`,
  `RESULTS_DIR_NAME`, assay name/description, panel/pattern docstrings), all
  user-facing titles in `templates/` + `src/main.py` + `src/app.py`, download
  filenames, `pyproject.toml`, GitHub URL, `.spec` files (renamed + internal app
  names + bundle id), `report.py` docstring. App imports + loads config cleanly.
- **Section 1 (384 + multi-pool foundation)** complete:
  - `parse_xponent.py`: well regex `[A-H]` → `[A-P]` (96- and 384-well).
  - `report.py`: plate-map geometry inferred from data (snaps 96↔384).
  - `classify.py`: full rewrite for Bangladesh sample names + `_parse_pc` pool/
    dilution/concentration/single-point parser. New columns `pc_pool`,
    `dilution`, `pc_single_point`, `pc_x_kind`.
  - `config.py`: Bangladesh well-classification patterns; added
    `panel.priority_antigens` (default `[]` = all).
  - `qc_standard_curve.py`: drop single-point pools from fitting; guard pools
    with <4 dilution points (→ NO_FIT, no crash). Multi-pool dict + per-pool
    history confirmed.
- **Verified** on both `tests/fixtures/` pilots: classification counts, 7/4-pool
  detection, dilution parsing, HlyE ng/mL axis, full fit + per-pool history, and
  `generate_report` on the multi-pool/384 data (tested on a 15-antigen subset for
  speed — full 200-antigen run works but takes minutes; the per-pool history
  files from the full run are the evidence it completes).
- **Auto antigen→pool selection added** (resolves the `pools[0]` follow-up):
  `select_pool_per_antigen` parses pathogen group from the antigen name, matches
  to target pools, tie-breaks by best fit (fit_ok then R²); overridable via
  `config['panel']['pool_antigen_overrides']`. Wired into `compute_in_range_table`
  + `compute_concentrations`. Verified per-antigen routing on Plate 1.
- **Explained on the report**: added an explanatory banner in the Standard-Curve
  Summary ("Multiple control pools — how each antigen is scored") that lists the
  detected pools, describes the name-match + best-fit-tiebreak rule, and shows how
  many antigens each pool was chosen to calibrate; plus a short cross-reference
  note in the Range Matrix. Driven by `_build_pool_selection_summary` →
  `pool_selection` template var. Banner only shows when >1 pool is present.
- Next: Section 2 (Plate Overview rebuild — metadata table, count cards,
  shape-coded scrollable 384 plate map with hover).

### Session 0 — 2026-06-01 (Project kickoff + plan)
- Folder forked from `uvira-luminex-qc`.
- Read and mapped the Uvira codebase: `config.py`, `settings.py`,
  `parse_xponent.py`, `classify.py`, `qc_*`, `pipeline.py`, `report.py`
  (full section map), `templates/report.html`, `templates/web/settings.html`,
  and the `UVIRA_TODO.md` history (through Session 19).
- Confirmed key facts: all requested Plate Overview metadata is already parsed;
  plate map + several heatmaps are hard-coded to 96-well (8×12) and need
  generalizing to 384-well (16×24); `reportable_range` (LLOQ/ULOQ) already
  available to drive the linear-range square; cross-plate history already
  persisted (reusable for IQR comparison).
- **Parsed the two pilot CSVs** and discovered Bangladesh is structurally closer
  to the legacy *multi-pool* mpox app than to Uvira: 384-well (A–P × 1–24), 200
  analytes, no input file, and PC = multiple named pools each with its own
  dilution series encoded in the sample name (Anti-OSP/cTxB/HlyE, Dengue, Orpal,
  HlyE ng/mL, Cholera High/Low), NC = "Negative 0/49", specimens = `{id}_r3_
  {Serum|DBS}`. Updated plan: revive multi-pool fitting + per-pool history,
  rewrite classification patterns, new pool/dilution parser.
- Received the two screenshots; locked the linear-range styling (green square,
  red out-of-tolerance triangles, "×" excluded point).
- Raised 6 new open questions from the pilot data (202 vs 200, pool→antigen
  priority mapping, HlyE concentration axis, NC labels, Serum/DBS pairing,
  single-point controls).
- Drafted this plan (To-Do sections 0–10) for user review. **No code changed**
  (other than moving legacy docs into `legacy/`).
- Next session (pending approval): Section 0 rebranding + Section 1 (384-well +
  multi-pool foundation), since all downstream UI work depends on it.

---

## Session 20 — Major report enhancements (PLAN, pending approval)

Grounded in a full code map. **No code changed yet.** Items marked **[DECISION]**
need a user call before building.

### Phase A — Control QC restructure
- **A1. New "Positive Control QC" section** (insert *after* Background QC).
  Single-point controls (Cholera High / Low) are currently parsed in
  `classify.py` (`pc_single_point=True`, `pc_x_kind="single"`) but then
  **discarded** — excluded from the 4PL fit and from PC-replicate QC, never
  rendered. New work:
  - `qc_pc_single_point(data)` → per (control × antigen) MFI for the current
    plate (one value per single-point control per analyte).
  - New history `pc_single_point_history.json`, keyed
    `[plate_id, control, analyte]`, carrying `plate_id, run_date, control,
    analyte, mfi`.
  - **Two cross-plate plots** — one for Cholera Low, one for Cholera High —
    built on a generalised version of the Background overview (Plotly; x =
    antigen in panel order, y = MFI log scale; < 3 past plates = one dot/plate,
    >= 3 = historical Q1-Q3 IQR bar + median tick + current-plate red dot with
    inside/below/above-IQR hover).
  - **Duplicates exist** (each single-point control runs in 2 wells/plate). No
    separate rug strip (200-antigen layout problem + 2 points isn't a
    distribution). Instead the overview plots **both duplicate wells as
    individual points** per plate (current = red, historical = faint) over the
    IQR band — gives every MFI value (current + historical) + duplicate spread +
    drift in one view.
  - **Cross-plate stats table per control**: one row per antigen — current MFI
    (mean of the 2 reps), current-plate **duplicate %CV** (recovers the
    replicate-agreement signal lost by removing PC-replicate variability),
    historical mean / SD / %CV / IQR, n past plates.
  - Description adapted from the supplied example (no other-project specifics).
- **A2. Remove "PC replicate variability"** entirely: template block,
  `_format_pc_replicates` (report.py), `qc_pc_replicates` call + `pc_replicates_*.csv`
  write (pipeline.py), the Downloads button, `src/qc_pc_replicates.py`, and the
  `.spec` hiddenimports entry.

### Phase B — Negative Control QC rework (placed *after* Positive Control QC)
- Replace the faceted matplotlib grid with **two Plotly plots**, one per NC
  control (Negative 0, Negative 49), on the same generalised cross-plate overview
  as Background/PC. **Plate toggle** via radio buttons (current / all historical /
  pick a plate) instead of legend-only. No rug.
- Add the **cross-plate stats table** (same columns as PC).
- Refresh the description to match.

### Phase C — Standard-Curve Summary / All-Curves / Picker
- Picker stays folded; ensure an explicit "Click to expand" note.
- **Rug labels**: smaller + angled so they stay legible as plates accrue; reduce
  rug-column width (less whitespace); wrap the picker figure in a
  **horizontally scrollable** container so rugs remain reachable.
- **Plate toggle**: radio buttons (current / all historical / specific plate).
- **Standard/pool picker**: add a pool dropdown so the user can view ANY
  (pool x antigen) fit (we already fit every combination). Fallback: a
  "search to plot" points-only view when a pool didn't converge for an antigen.

### Phase D — Cross-cutting
- **D1. Sortable tables**: click-to-sort headers on every report table via a tiny
  vanilla-JS sorter (no dependency -> works in the downloaded HTML).
- **D2. Lab Notes section [DECISION-persistence]**: columns Date / Output file /
  Notes / Usable? (yes-no-maybe) / Freezer box(es) / Actions taken. Static HTML
  can't save typed input on its own - needs a persistence approach (see questions).
- **D3. Cross-run MFI scatter**: make collapsible; add the "X of Y specimens
  appear in history; empty if 0" note.
- **D4. Standardised plate naming**: one canonical plate-label helper used in
  EVERY section (overview, background, PC, NC, picker, cross-run). Today the
  picker/cross-run use a composed `date . run . box` label while others show the
  raw `plate_id`.
- **D5. Sample-matching section [DECISION-list ingestion]**: match plate wells to
  a master sample list (barcode <-> patient_id); show matched count, unmatched
  barcodes/patient_ids, and repeated-sample flags (this plate + across history).
  Drives the standardised display names in D4.
- **D6. "Click to expand"** note on every folded section.
- **D7. Descriptions audit**: re-verify every section's prose against actual
  behaviour after these changes.
- **D8. Offline downloads [DECISION-embedding]**: report plots are already
  self-contained (inline Plotly + base64 PNGs), but the Download buttons point at
  Flask routes (`/download/...`) so they 404 in the saved HTML. Fix = embed CSVs
  as base64 data-URI links (tradeoff: larger HTML).
- **D9. YAML round-trip test**: pattern fields (`pc/background/nc_patterns`) are
  comma-split in the UI (fragile if a regex contains a comma) - switch to
  newline-split; add a save->load->save test, especially for
  `pool_assignment_rules` / `pool_antigen_overrides` (antigen<->standard matching).

### Suggested sequencing
1. Phase A + B (control QC; biggest scientific value, shared overview helper).
2. Phase C (picker usability).
3. D4 + D5 (naming + sample matching; related).
4. D1, D3, D6, D7 (UX polish).
5. D8, D9 (offline + config robustness).
Lab Notes (D2) slots in once its persistence model is chosen.

### Decisions (resolved with user)
- **D2 Lab Notes**: *editable fields in the report, manual export* — no
  server-side persistence. Build editable table cells + a "Download notes as
  CSV" button (data-URI). Caveat to surface in the UI: notes are **not** saved
  automatically and are lost on reload unless downloaded.
- **D8 Offline downloads**: *embed ALL CSVs in the HTML* as base64 data-URIs so
  every button works in the saved report (accept the larger file size).
- **D5 Sample list**: *persistent master list, reused across plates* — upload
  once, stored in the results dir, applied to every plate (re-upload to update).
  - No separate barcodes in this project: **`patient_id` IS the join key** (the
    number parsed from the well name before `_r3_`, e.g. `12602`).
  - Columns: `patient_id` (required, join key), `collection_date`, `visit`,
    `site`, `comments`.
  - **Unmatched wells flagged visually** (⚠) so they stand out; matched wells
    display as standardized `patient_id · <matrix>` (matrix from the well name).
  - Section reports: matched count, plate `patient_id`s not in the list, and
    repeated samples (same `patient_id` on >1 well this plate, or across history).
- **Build order**: start with **Phase A + B (Control QC)**.

### Session 20 progress — Phase A + B DONE
- New `src/qc_pc_single_point.py` (`qc_pc_single_point`, `control_label`):
  extracts Cholera High/Low duplicate-well MFIs per (control × antigen).
- Pipeline: calls it; writes `pc_single_point_<plate>.csv`; persists
  `pc_single_point_history.json` (key `plate_id, control, analyte, well`);
  passes `history_pc` to the report. Removed the `qc_pc_replicates` call +
  `pc_replicates_*.csv` write.
- `report.py`: new shared `_cross_plate_mfi_overview` (IQR band ≥3 plates, else
  per-plate dots; current duplicate wells in red; legend-toggle "Past plates
  (individual)"), `_format_control_stats`, `_control_qc_sections`. Removed
  `_format_pc_replicates`, `_make_nc_history_plot`, `_make_nc_bar`.
- Template: new **Positive Control QC** + reworked **Negative Control QC**
  sections placed right after Background QC (nav updated); per-control overview
  plot + folded cross-plate stats table; PC-replicate block + download removed.
- Deleted `src/qc_pc_replicates.py`; both `.spec` hiddenimports now list
  `src.qc_pc_single_point`.
- Verified end-to-end on pilot Plate 1: both sections render, Cholera High/Low +
  Negative 0/49 present, stats tables populated, no PC-replicate remnants, app
  boots (home/settings 200).
- **Left for later (noted):** `pc_cv_threshold` (config + Settings field) and
  `_nc_control_colors` are now orphaned — prune in a cleanup pass. Full
  200-antigen `run_pipeline` is slow (>45s, mostly the picker) — Phase C will
  address picker performance.

#### Session 20 refinements (review rounds, all in `report.py` + `report.html`)
- **Background QC unified** with PC/NC: it now uses the same
  `_cross_plate_mfi_overview` + `_format_control_stats` (current-plate
  Background wells + each past plate's mean as a pseudo-well). Removed the old
  `_make_background_overview_plot`, `_bg_overview_iqr`, `_format_bg_levels`, and
  the unused `qc_background_levels` import from `report.py`.
- **Tables (Background / PC / NC) now identical**: Analyte · n wells · one
  column per well (by position) · current Mean / SD / %CV / IQR · Historical
  mean / SD / %CV / IQR · (n past plates — PC/NC only, omitted for Background).
  Driven by the shared `_format_control_stats`.
- **Plot styling**: dropped the faint individual-well dots and the
  "Past plates (individual)" trace; current-plate point is the **mean** of the
  wells, sized down and **flag-coloured** — blue within the historical IQR,
  orange ♦ above/below it. No visible median tick (median is in the hover).
- **Row highlighting**: stats rows where this plate's mean is outside the
  historical IQR are tinted + bar + ▲/▼ marker, with **direction-specific
  colours** (above Q3 = orange, below Q1 = blue).
- **Hover standardized** across the three sections — grey bar:
  `<antigen>` / `Historical IQR (N plates):` / `Q1; Median; Q3`; current dot:
  `<antigen>` / `This plate — mean MFI: X (wells: …)` / `Historical IQR` /
  `Position: within / above Q3 / below Q1`. Hover numbers match the table.
- **Colour-blind-safe palette (Okabe–Ito)** report-wide: blue `#0072B2`,
  orange `#D55E00`, amber `#E69F00`, bluish-green `#009E73`, grey `#999999`;
  pass/fail also varies marker SHAPE (♦, ▲/▼). Replaced red/green throughout
  (control plots, bead heatmap, range-status badges + matrix, picker rug,
  curve-fit colours). Bead tiers relabelled **Adequate / Low / Critically Low
  Bead Count** (badges, cards, heatmap hover, and the problem-list table — no
  more RED/YELLOW text). "vermillion" wording changed to "orange".
- **Removed the NC per-well detail table** (redundant with the per-well stats
  columns); dropped `_format_nc_table` and `nc_table`.
- Re-verified end-to-end on pilot Plate 1 (with a simulated multi-plate history
  to exercise the ≥3-plate IQR view, both flag directions, and the bead tiers).

#### Session 20 refinements (round 2)
- **Chronological history fix (important):** "past" plates are now those run
  *before* the current plate (compared by `run_date` via new
  `_past_plate_ids`), not "every other plate." Fixes the first plate's report
  showing later-run plates as historical. The IQR, the stats table's historical
  columns, and "n past plates" all use this definition, so plot and table agree.
- **Per-plate legend + toggle:** each historical plate is now its own grey,
  individually legend-toggleable trace (named by plate id; hover names the
  plate; small per-plate x-jitter so overlapping means separate). Added
  "Show all past plates" / "Hide past plates" buttons (Plotly `updatemenus`,
  offline-safe). In the ≥3-plate view individual plates start hidden behind the
  IQR band; in the < 3-plate view they show by default.
- **"(not on this plate)" note** in a control's heading when the current plate
  has no wells for it but history does (`on_plate` flag).
- **Collapsible description boxes:** all seven section description boxes
  (Background / PC / NC / control-pool note / "Fit OK" / All-Curves legend /
  Range Matrix) are now collapsed-by-default `<details class="desc-box">` so
  they no longer crowd out the plots; full bulleted text on expand.
- **Spacing:** trimmed the overview plot's top margin and pulled the
  legend/buttons to just above the plot (removed the large title-to-plot gap).
- **Wording:** "not yet (need ≥ 3 plates)" → "not established (requires ≥ 3
  prior plates)"; grey-bar hover drops the "Antigen:" prefix.

## Session 21 — Phase C: Standard-Curve Picker (DONE)
Replaced the old pre-built picker (which rendered every antigen's traces into
one figure — the main perf cost) with an **on-demand** explorer in `report.py`
(`_make_curve_picker` fully rewritten):
- **Antigen typeahead + pool dropdown** — inspect ANY (pool × antigen) fit, not
  just the scoring pool. Compact per-(pool × antigen) fit data + per-antigen
  specimen rug + per-past-plate history are embedded as JSON; one figure is
  drawn client-side (`Plotly.newPlot`) per selection → fast even at 200 antigens.
- **Left panel:** standards + 4PL (orange) + green reportable-range box +
  out-of-tolerance ▲ + dropped ✕ + grey past-plate curves.
- **Right panel (rug):** this plate's specimens coloured by status (computed
  client-side from the selected pool's range) in one column; each past plate its
  own grey column; **angled small labels**, narrower, in a **horizontally
  scrollable** container that widens with plate count.
- **Plate toggle:** per-plate legend entries (curve + rug toggle together via
  `legendgroup`) **plus** "Show all / Hide past plates" buttons. "Past" =
  chronological (`run_date` before current).
- Status line shows `fit_ok` + this plate's IN/BELOW/ABOVE/NO_FIT counts.
- Picker call now passes the full `fits` dict + `current_run_date`; description
  rewritten to match; fixed a pandas FutureWarning on the empty-history concat.
- Verified the report renders with the picker (controls, on-demand draw, pool
  options, toggle) and the app boots. NOTE: a full 200-antigen `run_pipeline` is
  still > 45s in the sandbox — the remaining cost is the 4PL fitting + the
  200-panel static All-Curves grid, not the picker (Phase D / later perf pass).

#### Phase C layout refinements (review rounds)
- Standardized + aligned the antigen typeahead and pool dropdown (shared
  `.cp-ctrl` style); removed the inline status text.
- Restored the in-plot-style **status box** (one line each: This plate · N
  specimens / IN / BELOW / ABOVE / NO FIT / fit OK) and the vertical
  "Click to toggle" legend — both moved into the **right margin** so they never
  overlap the curve or the reportable-range box. Fixed the `&middot;` typo
  (use the literal "·").
- **Rug sizing:** fixed ~46 px per column (was a fixed wide share), so columns
  pack tightly with no wasted side space; curve panel widened to ~720 px.
- "Show all / Hide past plates" buttons moved top-left (no legend overlap).

## Session 22 — Phase D: Quick UX wins (DONE)
- **Sortable tables:** dependency-free click-to-sort script (bottom of
  `report.html`) on every data table (those with a `<thead>`; the key-value
  metadata table is skipped). Numeric-aware (blanks/"—" sort to bottom),
  asc/desc toggle with a ▲/▼ indicator. Works offline.
- **Click-to-expand cues:** desc-boxes get " — click to expand" via CSS when
  closed; added the same note to the bead/range problem + out-of-range detail
  `<details>` summaries that lacked it.
- **Cross-run scatter:** now a collapsible `<details>` shown always, with the
  overlap note "<matched> of this plate's <total> specimens appear in the
  history" (new `_xrun_overlap` helper, matched on patient_id > barcode >
  sample_name). Plot only renders when there's overlap; otherwise the note
  explains why it's empty.
- **Descriptions audit:** fixed the picker bullet that still said "line above
  the plot" (now "status box, top-right") + the legend/toggle wording; confirmed
  no other stale picker phrasing. Verified render + app boot (home/settings 200).

#### Session 22b — cleanup + YAML test (DONE)
- Pruned orphaned `pc_cv_threshold` (removed `PC_CV_THRESHOLD` in config.py, the
  `qc_thresholds` default, the app.py save handler entry, and the Settings
  "PC Replicate %CV" field) and the dead `_nc_control_colors` / `_NC_CTRL_PALETTE`
  in report.py (`_nc_control` is still used and kept).
- Added `tests/test_config_roundtrip.py` (standalone-runnable + pytest-style):
  verifies the antigen→standard-pool matching config (priority_antigens,
  pool_mode, scoring_pool, pool_assignment_rules incl. a regex with a comma,
  pool_antigen_overrides) and numeric QC thresholds survive save→load→save.
  Passes. App still boots (home/settings 200).

#### Session 22c — editable YAML config + Settings instructions (DONE)
- Added `config.example.yaml` (repo root, bundled in both `.spec` datas): an
  annotated baseline of the *editable* settings (not the auto-derived antigen
  panel), with detailed comments on `panel.priority_antigens` and the antigen ×
  standard-pool matching keys (`pool_mode`, `scoring_pool`,
  `pool_assignment_rules`, `pool_antigen_overrides`).
- New route `/settings/example-config` serves it (packaging-safe via `base/`),
  alongside the existing Export (current config) / Import.
- Settings page: new "Configuration file (YAML)" card with concise step-by-step
  instructions (download a starting point → edit → import & apply) plus a
  "Annotated template" download link.
- Verified: template is valid YAML, merges over DEFAULTS (panel preserved),
  download + import round-trip work, Settings page renders the guidance.

#### Session 22d — offline (embedded) downloads (DONE)
- `pipeline._embed_report_downloads(report_path, output_dir)` runs at the end of
  `run_pipeline` (after all per-plate CSVs are written): rewrites every
  `/download/...` link in the report HTML to a base64 `data:text/csv` URI of the
  on-disk file (with a `download="<name>"` attr). Buttons now work in the saved
  HTML opened offline AND when served live. Missing files (e.g. nc_levels with
  no NC, or problem CSVs with no problems) keep their server link.
- Downloads-section note added: "buttons work whether the app is running or this
  report is opened as a saved file — each CSV is embedded."
- Verified: all referenced CSVs embed (server links → data-URIs). Size tradeoff
  (the user's chosen "embed all"): the specimens CSV pushes a full report to
  ~50 MB. If that's a concern later, embed only the small summaries and keep
  specimens/results server-only.

#### Still pending (Phase D onward)
- Lab Notes section (editable + download-CSV) — **lowest priority**.
- Standardized plate naming + sample-matching section (needs the master
  sample list).
- (Optional) switch the well-classification pattern fields from comma-split to
  newline-split in the Settings UI for regex-with-comma robustness.

## Session History — Session 23 (QC batch: matching + Background/NC/Summary/All-Curves/Picker/Range-Matrix)

Roadmap validated with the user before coding (auto_select matching; VPD/other-
arbovirus → Dengue/Orpal reference; measles = `VPD_measles_NP` + `RES_measles_lysate`;
NC outlier = duplicate %CV; negative net MFI vs plate background wells). Delivered:

1. **Antigen↔standard matching now defaults to `auto_select`** (config, app,
   report, pipeline fallbacks flipped). `antigen_group()` extended to 5 display
   categories (cholera/typhoid/dengue/arbovirus/vpd) with `_SCORING_POOL_GROUP`
   routing arbo+VPD → Dengue/Orpal. `pool_antigen_overrides` added to DEFAULTS.
   Docs (config.example.yaml, settings, SPEC, README) updated.
2. **Background QC:** shared overview now fixed-width + horizontal scroll +
   dashed `bg_max_mfi` line; per-antigen table gains a sortable **High CV** flag
   (row-highlight when %CV > `bg_cv_threshold`) + count card; two hidden tables —
   **well outliers (leave-one-out** mean+2SD, since plain all-wells 2SD never
   fires at n=4) and **negative net MFI** (specimen − mean plate background).
3. **NC QC:** widen+scroll (shared change); **duplicate-%CV** flag per antigen
   (`nc_cv_threshold`, new default 0.25) since n=2 makes 2SD meaningless.
4. **Standard-Curve Summary:** one sortable fit table **per pool**, each labelled
   with pathogen target(s) (`_pool_target_label`).
5. **All-Curves:** **featured priority antigens** grouped by pathogen category
   (each vs selected pool) on top; full per-pool × all-antigen grids collapsed.
6. **Picker:** past-plate rug coloured by range status (same scheme, alpha 0.45);
   rug labels rotated to 90°; bottom margin bumped.
7. **Range Matrix:** antigen rows grouped + colour-labelled by pathogen with
   dotted separators + legend (`_freeze_pane_heatmap` gained `row_label_colors` /
   `row_group_lines`).
8. `specimens.default_dilution` relabelled **informational** (not used in RAU).

Verified: config round-trip; matching unit test; leave-one-out outlier cases;
per-pool label/grouping; featured-grid categories; range-matrix legend; full
end-to-end pipeline on a 14-antigen subset in **both** auto_select and per_pool
(3.8 / 3.9 s) — all new markers present.

**Notes / decisions made:** (a) background well-outlier uses **leave-one-out**
mean+2SD (literal all-wells 2SD is statistically inert at n=4 — even 500 vs ~10
doesn't fire). (b) The collapsed "all curve fits, all pools" block renders one
grid per pool over **all** antigens; on the full 202-plex × N pools this is the
heavy/slow render (static images) — acceptable since collapsed, but it is the
main runtime cost. Featured section stays interactive.

## Session 23b — Post-review bug fixes (Session-23 feedback)

User screenshots surfaced four issues; all fixed & verified end-to-end (subset
pipeline, both pool modes):

1. **Background overview looked flat (y-axis to 1e304).** `add_hline` on a log
   axis blew up autorange. Fixed by setting an explicit data-derived log
   y-range (`yaxis.range`, `autorange:false`) that always includes the hline.
   Applies to Background/PC/NC (shared `_cross_plate_mfi_overview`).
2. **Picker rug x-labels cut off.** Bumped picker `b` margin 120→190, height
   560→620.
3. **"Show all / Hide past plates" buttons** moved from top-right to top-left,
   **under the legend** (legend raised to `y=1.14`, buttons `x=0` `y=1.015`).
   Shared overview → applies to Background/PC/NC.
4. **FLU under a cholera pool in the Summary.** Root cause: uncategorised
   antigens (no pathogen match) fell through to best-fit fallback in
   `auto_select`. Fix: the Summary + Featured views now default to the
   **pathogen-categorised** priority set (`antigen_group(a) is not None`);
   FLU/MAL/etc. are dropped from those tables (still in collapsed all-curves +
   picker). New flag `priority_is_pathogen`; banner reworded.

**PINNED (unresolved) decision:** whether no-standard antigens (FLU/MAL/…)
should keep a meaningless best-fit RAU in the clean-results export or be left
`NO_FIT`. Deferred to Phase 5.

## Session 24 — Phased roadmap agreed; Phases 1–3 delivered

User directive: **split remaining work into phases across sessions with
check-ins; do not do it all at once.** Agreed phases:
- **P1** Plate Overview & Bead Count text · **P2** table↔plot coherence audit ·
  **P3** chronological foundation (run date+time) · **P4** Background/PC/NC
  Median±IQR vs per-plate toggle · **P5** matching review + NIBSC + Featured
  standard labels + Range-problem standard column + pinned scoring decision ·
  **P6** picker polish (rug labels to top, axis titles).

### Answers/confirmations given (no code)
- Leave-one-out background outlier, negative-net-MFI table, and NC
  duplicate-%CV flag are all **already implemented** (Session 23) — explained
  in plain language. NC "outlier" is the duplicate-%CV column (n=2 → 2SD not
  meaningful).
- Confirmed fitting model: **every antigen is fit against every pool** always;
  Summary shows only relevant matches; Featured shows the single best-fit
  matched curve; collapsed all-curves + Picker show ALL combinations.

### Decisions this session
- Matching stays **auto_select default**, YAML-overridable (confirmed).
- All 5 pilot standards confirmed recognised: Anti-OSP & cTxB (& HlyE) →
  cholera (+ typhoid); HlyE 50 ng/mL → typhoid; Dengue/Orpal → dengue + arbo +
  VPD reference. (`_pool_groups` token match handles the `Pilot Control:`
  prefix fine.)
- Background outlier method: user chose **"show both / discuss"** → fold into a
  future Background-QC touch (keep LOO flag, add literal all-wells mean+2SD as
  an extra column). **TODO task #7.**
- P2 audit: **all tables numerically coherent** (card = table rows = independent
  recompute). No counting bug. User chose to **keep as-is**: antigen problem
  denominator = all wells; specimen = specimen wells only; negative-net keeps
  all `net < 0`.

### Phase 1 (DONE)
- Plate Overview: per-single-point-control count cards (Cholera High / Cholera
  Low PC wells), placed between "PC / standard" and "NC" cards; all 8 cards on
  one row via `.stat-row.compact8`.
- Bead Count: collapsed **"How the Bead-Count Matrix works"** description box
  above the cards; mechanics text (hover / sticky row+col / group separators)
  below the cards; removed the old redundant tier-legend paragraph.

### Phase 2 (DONE — audit only, no code changes)
- Verified bead, range-problem, background-outlier, negative-net, high-CV counts
  all equal their table rows and an independent recompute. Confusion was
  explanatory (heatmap looks red from standard/PC columns; flags need ≥20%).

### Phase 3 (DONE)
- **Canonical run datetime** (`parse_xponent._canonical_run_datetime`): prefers
  `BatchStartTime` (actual run start) → export `Date` → `BatchStopTime`; stored
  as ISO string in `metadata.run_datetime`, and `run_date` (the ordering key
  used across history/legends/rug). Export stamp kept as `run_date_export`.
- Ordering is **render-order-independent** (`_past_plate_ids` sorts by parsed
  datetime; verified identical after row shuffling).
- **Picker rug** columns + legend now run **current → nearest-past → oldest**
  (reversed `past_ids`). Cross-plate overview legends stay chronological.
- **Datetime-parse safeguard:** `metadata.run_datetime_ok` + `run_datetime_raw`;
  report shows a red banner under the title (and a `⚠ unparsed` badge on the
  Run date row) when no header datetime parses, advising to upload the original
  instrument CSV (not an Excel-resaved copy). Parsing never crashes.
- Note: `#####` in Excel is only a narrow-column display artifact; the app reads
  raw CSV text, and pandas parses `8/21/2025 9:22`, `…9:22:00 AM`, 24h, etc.

### Phase 4 (DONE) + task #7 folded in
- `_cross_plate_mfi_overview` now has a **two-view toggle** (buttons top-left,
  under the legend): **"Median ± IQR"** (grey IQR band + current dot blue/orange♦
  by IQR position) and **"Per-plate data points"** (each past plate its own dot on
  a chronological blue→green gradient via `_blue_green_gradient`, oldest faded /
  newest bold; current plate bold **red** `_CUR_RED`). Default = Median±IQR when
  ≥3 past plates, else Per-plate. Kept Show-all/Hide past plates + legend
  click-toggle. Applies to Background, PC, NC (shared fn). Margins bumped
  (t=118, height=620) to fit legend + two button rows.
- Descriptions updated in all three sections (Background/PC/NC) to explain the
  two views + per-plate gradient.
- **Task #7 (show both):** `_bg_well_outliers` now also reports the literal
  all-wells mean/SD/threshold + an `all_flag` column beside the LOO columns.
  Verified: LOO flags A4 (60 vs thr 12); all-wells does not (60 < 72.5) —
  both shown.

### Phase 4 refinements (post-review feedback)
- **Buttons no longer shift on click:** root cause was `margin.autoexpand`
  (default True) resizing the plot area when legend/visibility changed, moving
  the paper-anchored buttons. Fixed with `margin(autoexpand=False)` (+ fixed
  t=118). Verified present in all 5 overviews.
- **Background outlier now highlighted + explained:** flagged antigens get a
  `⚠ outlier` badge + amber row highlight in the main per-antigen table
  (`has_outlier` on each row; `bg_levels.n_outliers`), the outlier table's rows
  are amber-highlighted, and a plain-language explanation box was added.
- **NC duplicate-CV detail:** each NC control now shows a focused table listing
  the flagged antigens with their two well MFIs + %CV (or a "✓ none" line),
  above the full cross-plate stats table — instead of only the heading count.
- **Clarified:** default view = Median±IQR when ≥3 *past* plates exist, else
  Per-plate (depends on # past plates, not total uploaded). A plate with no
  single-point Cholera High/Low PC has no PC overview/toggle (nothing to plot);
  Background/NC toggles are unaffected.

### Phase 5 (mostly DONE — NIBSC deferred pending pool name)
- **Matching review** done against real 202-plex panel. Categories confirmed:
  cholera(3), typhoid(1), dengue(12), other-arbovirus(22), vpd(9 — incl.
  measles×2, diphtheria, rubella, tetanus×2, pertussis×2, meningitis-B),
  uncategorised(152).
- **BUG FIXED:** `FLU_H1N1_HA_Denver_1957` was matched as *dengue* (bare "DENV"
  substring caught "DENVer"). Now requires `DENV\d` or `DENGUE` (`import re`
  added to qc_standard_curve).
- **Calibration tiers** (`antigen_calibration` + `CALIBRATION_LABELS`):
  standard (cholera/typhoid/dengue) / reference (arbo/vpd → Dengue/Orpal) /
  uncalibrated (no category). **Decision: keep best-fit RAU for uncalibrated but
  MARK it.** Added `calibration` column to the clean-results tidy export.
- **Range-problem antigens table** now has a **Standard** column (matched pool +
  calibration tier) with an explanatory note.
- **Featured section**: headings now state the calibration tier + the best-fit
  standard pool(s); intro clarifies only the best-fit curve is featured and ALL
  antigen×pool fits live in the collapsed block + Picker. **Decision: for
  antigens with >1 candidate pool, feature only the single best-fit curve.**
- **Confirmed:** `fit_standard_curves` fits every antigen × every pool always;
  matching only selects which is scored/featured.
- **Meningitis C** (`BAC_N_meningitidis_C_CPS`) left uncategorised (decision).
- **NIBSC mapping (DONE, Phase 5b):** keyed on the **"NIBSC"** keyword in the
  pool name (user: name will be like `Pilot Control: NIBSC...`). Added a
  `vpd_nibsc` pool group + ordered preferred→fallback scoring
  (`_antigen_scoring_groups`): measles/diphtheria/rubella/tetanus prefer a
  NIBSC pool when present (tier upgrades to "standard"), else fall back to the
  Dengue/Orpal reference. Pertussis/meningitis stay reference (NOT NIBSC).
  `antigen_calibration(name, pool)` is now pool-aware. Verified with synthetic
  NIBSC-present / absent scenarios; existing no-NIBSC behavior unchanged. If the
  real pool name lacks "NIBSC", route via a YAML `pool_assignment_rules` entry.
- **Clarified for the record:** "(± combined)" just means a category has more
  than one *real* pool containing its reagent (e.g. cholera → `Anti-OSP & cTxB`
  AND the tri-mix `Anti-OSP & cTxB & HlyE`); best-fit picks one. The app never
  fabricates pool combinations — it fits every antigen against every real pool.

### Phase 6 (DONE) — picker polish
- Rug plate-column labels moved to the **top** (`xaxis2.side:"top"`) — they were
  being clipped at the bottom.
- Axis titles restored/made explicit: curve X = **"Standard dilution (1:x)"**,
  Y = **"MFI (log scale)"**, rug = **"Plate run (current → oldest)"**. They were
  being crowded out by the oversized bottom margin (b=190) that held the rug
  labels; moving labels to the top freed the bottom for the Dilution title.
- Margins rebalanced (t=160, b=64, height=640); Show all/Hide buttons moved to
  y=1.02 (top-left over the curve; plate labels sit top-right over the rug, no
  collision). NOTE: eyeball the top spacing on a real multi-plate report; bump
  `t` if long plate IDs clip.

### Final docs pass (DONE — reference docs synced)
- **SPECIFICATION.md**: report-sections list rewritten for Phases 1–6 (plate
  cards incl. single-point PC, bead description box, two-view control overviews,
  outlier "show both", NC focused flag table, pathogen-priority summary,
  featured best-fit, picker top labels + axis titles, Range-problem Standard
  column); added *Run datetime & chronological ordering* subsection; matching
  section gained NIBSC + calibration tiers + DENV-digit note; Outputs note the
  `calibration` column; Settings list updated (pool_mode/rules/overrides,
  nc_cv_threshold, informational default_dilution).
- **README.md**: feature bullets updated (plate cards, bead box, Background &
  PC/NC two-view toggle + flags, NIBSC + calibration tier, summary/featured,
  picker, range-matrix grouping, chronological ordering); Background/NC QC
  sections, Output (results calibration col), and Settings list synced.
- **REMAINING: v0.2.0 build** — commit, tag `v0.2.0`, verify CI (task #8). Not
  done yet; nothing committed since v0.1.0.

## Phase 7 (DONE — post-v0.2.0, uncommitted; for next release)

From review of the first real multi-plate report:
1. **Inter-assay CV flag.** The "Historical %CV" column is between-plate
   (inter-assay) variability; added a `hist_cv_threshold` (default 0.30), a
   **High hist. CV** flag column + `↕` marker + count card (Background), threaded
   through `_format_control_stats` / `_control_qc_sections` (PC/NC too). Editable
   in Settings + config.example.yaml.
2. **Range-matrix cell hover** now shows the calibrating standard + tier
   ("Calibrated vs: <pool> · <tier>"); legend note clarifies cell colour =
   status vs the matched standard, and that uncalibrated antigens are best-fit
   (left coloured, per decision). `_make_in_range_heatmap` gained `antigen_pool`.
3. **Featured priority antigens** now overlay **past-plate fitted curves** in
   light grey + a **Show all / Hide past plates** toggle (default shown).
   `_make_curve_grid[_interactive]` + `_build_featured_grids` gained
   `history_fit`/`past_ids`; `_hist_curve_params` helper.
4. **Picker polish:** added an **antigen × pool title** (top-left, using the
   freed whitespace), shrank rug x-labels (font 8), tightened top margin
   (160→140).
5. **Descriptions pass:** updated Background (two-CV explanation), Featured
   (historical overlay), Range-matrix legend, Picker (title/axis/top-labels).
   No stale/removed-feature text found elsewhere.

Verified: template + settings parse, config round-trip, two-plate end-to-end —
all markers present. **Not committed** — next release (v0.2.1/v0.3.0) will bundle
Phase 7 + the build.yml macOS-runner pin.

### Phase 7a — featured-grid spacing fix (post-v0.2.1, uncommitted)
- v0.2.1 shipped with the featured grid's Show all/Hide buttons + legend
  overlapping the first row of panels, and rows too tight (Dengue 2-row case).
- Fixed in `_make_curve_grid_interactive`: top margin 66→116 (buttons y=1.10,
  legend y=1.03 stacked above the grid); vertical_spacing 0.06→0.11; panel_h
  150→190; horizontal_spacing 0.04→0.055; figure height recomputed.
- Follow-up: on short (1-row) sections (Cholera/Typhoid) buttons still touched
  the legend because y was fractional (gap shrinks on short grids). Switched
  button/legend y to **pixel-based** offsets (legend 14 px, button 52 px above
  the grid, converted to paper fraction via grid height) → constant ~20 px gap
  for 1/2/4-row grids; button top ~76 px stays inside the 104 px top margin.
- Visual-only; eyeball on a real report before release. Target: **v0.2.2**.

### Still pending
- **build.yml:** pin macOS runner (`macos-14`) before the macos-latest→macOS 26
  migration (~Jun 2026). Low priority.
- (NIBSC done above.) Former placeholder — the NIBSC pool's
  on-plate sample name; maps to measles/diphtheria/rubella/tetanus) + Featured
  standard labels + Range-problem standard column + **pinned no-standard-scoring
  decision**. **Phase 6** picker polish (rug labels to top; X/Y axis titles).
- Task #7: background outlier "show both" layout.
- Lab Notes (lowest priority); sample-matching (needs master list).
- **Final docs pass before v0.2.0:** sync SPECIFICATION.md (report-sections
  list — Cholera High/Low count cards, Bead Count description box, run
  date/time semantics + parse-warning banner) and README for all Phase 1–6
  changes, THEN commit + tag v0.2.0 + verify CI. (User: fold SPEC/README sync
  into this final pass, not per-phase.)
- Nothing committed since v0.1.0 — user wants a v0.2.0 build once the batch is done.

## v0.3.0 — Phases 8, 9, 11 DELIVERED (uncommitted); Phase 10 → v0.4.0

**STATUS:** Phases 8, 9, 11 implemented + verified (template renders, config
round-trip passes, two-plate end-to-end on subsets). **Not committed.** Phase 10
(5PL) deferred to **v0.4.0** at the user's request. Delivered:
- **Phase 8:** Featured section rebuilt BY POOL (`_build_featured_grids` iterates
  pools; each antigen fit vs that pool via `fits[pool]`; dengue under both
  Dengue & Orpal; no-standard antigens excluded). Description rewritten.
- **Phase 9:** Summary = one table per pool over ALL antigens
  (`_build_summary_by_pool_all`) with a **Relevance** column (designated
  calibrator/reference, not best-fit), relevant-first + `row-flag-relevant`
  highlight, muted not-relevant, sortable; no-standard antigens never dropped.
  Stale "omitted"/per-mode summary intro removed.
- **Phase 11:** PC gains an Intra-plate %CV flag (via `cv_flag_threshold=nc_cv`);
  PC & NC gain the Inter-assay %CV column + heading badges (parity with
  Background). Range-problem SPECIMENS table gains a **Calibrated / best-fit**
  count column + per-antigen pool·tier tags in the detail
  (`n_calibrated`/`n_uncalibrated`/`detail_tagged` in `_format_range_summary`).
  Labels standardized to **Intra-plate %CV** / **Inter-assay %CV** across
  Background/PC/NC (no leftover "High CV"/"Dup. CV"/"High hist. CV"); descriptions
  updated. 4PL wording left as-is (Phase 10 deferred).

**Post-review fixes (from first v0.3.0 screenshots):**
- Featured panels were miniscule on large pool sections: `vertical_spacing` was
  a *fraction* of total height, so an 8-row (43-antigen Dengue) grid spent ~80%
  on gaps. Now pixel-based: fixed `panel_h=165` + `gap_px=44` → `plot_area_h`
  drives `fig_h` and `v_space=gap_px/plot_area_h`. Constant panel size for any
  row count.
- Range-problem specimens Antigens cell was a wall of 100+ tagged antigens.
  Now split: calibrated antigens (few, with pool) inline; best-fit ones collapsed
  behind a "+N best-fit (low-confidence)" expander; separate Calibrated/Best-fit
  count columns; plain-language "What this table is" explanation added.
  `_format_range_summary` now emits `detail_calibrated`/`detail_bestfit`.
- **Second review round:** (a) label standardization — "Intra-plate %CV" →
  **"Intra-assay %CV"** everywhere (parallel with Inter-assay), all cases in
  templates + report.py. (b) Specimens table reworked from a binary
  calibrated/best-fit (which lumped reference antigens into "calibrated" → still
  a 38-antigen inline dump) to the report-wide **3 tiers**: Dedicated / Reference
  / Best-fit count columns; only the **dedicated** antigens inline (the
  trustworthy signal); Reference and Best-fit each collapsed behind an expander;
  rewritten plain-language explanation with a worked example ("0 dedicated / 20
  reference / 83 best-fit" = normal seronegative vs "8 dedicated / …" = real
  problem). `_format_range_summary` now emits
  `n_dedicated`/`n_reference`/`n_bestfit` + `detail_dedicated`/`_reference`/`_bestfit`.

- **Third review round — Range-problem SPECIMENS redesigned to per-standard**
  (`_build_range_problem_by_pool` in report.py; new template block; old
  `range_summary.sample_*` specimens table removed). Rationale (user critical-
  thinking): the previous whole-panel "≥20% of a well's antigens out of range"
  metric conflated seronegativity + uncalibrated best-fit noise and was not a
  clean range-problem signal. New design assesses **each standard pool
  independently** and attributes the flag to a **specific standard**:
  - **Flag** = ≥ `problem_fraction_threshold` (20%) of that pool's **dedicated**
    antigens (cholera/typhoid vs Anti-OSP&cTxB&HlyE; dengue vs Dengue *and* vs
    Orpal, each independently) reading BELOW/ABOVE that pool's reportable range.
    One block per pool; a well can be flagged for one standard and not another.
  - **Reference antigens** (arbo/VPD + no-match FLU/MAL) are **not dropped**: for
    the reference pools (Dengue/Orpal) they are read against that reference curve
    and shown as an informational `n_out / n_ref` context column — they never
    drive the flag. Non-reference pools (cholera/typhoid) show no context column.
  - Both BELOW and ABOVE shown; per-specimen dedicated antigen names listed.
  - Count cards updated: "Specimens flagged BELOW/ABOVE" now = distinct wells
    flagged (dedicated, any standard) via `range_problem_counts`.
  - Verified end-to-end on the Plate-1 subset: all 5 pools render as separate
    blocks (Anti-OSP&cTxB&HlyE, Anti-OSP&cTxB, HlyE, Dengue, Orpal); Dengue/Orpal
    carry a 5-antigen reference-context column; example row F5 = 3/3 dengue BELOW.
  - **OBSERVED / for discussion:** BELOW flags ~230–247 of ~250 wells per pool —
    i.e. essentially all specimens — because seronegativity reads below range even
    for dedicated antigens. ABOVE flagged only 5 wells (the more specific signal).
    So the BELOW flag is near-non-discriminating; options if desired later: raise
    threshold, emphasise/segregate ABOVE, or cross-reference bead count.
  - Dead code left intact (low risk): `_format_range_summary` still computes the
    now-unused sample_below/sample_above tier fields; `range_summary.n_*_samples`
    no longer rendered. Trim in a later cleanup.

- **Fourth review round — five pre-v0.3.0 notes:**
  1. *Out-of-range detail list* — kept (user), but gained a **Standard
     (fit against)** column: pool + calibration tier in auto-select; the neutral
     "scoring pool (not pathogen-matched)" label in per_pool.
     `_format_range_problems` now takes `antigen_pool` + `pool_mode`. (Its data is
     otherwise fully in the downloadable `in_range` CSV + the Range Matrix.)
  2. *Standard-Curve Range Matrix* — confirmed it overlays all standards (one
     status per antigen against its matched pool; best-fit for no-standard
     antigens). Kept, labeling strengthened: desc-box auto-select branch now says
     it mixes standards + best-fit for no-standard antigens; in-plot legend made
     **mode-aware** (`_make_in_range_heatmap(pool_mode=…)`): matched-standard /
     best-fit wording in auto-select, single-scoring-pool wording in per_pool.
  3. *PC/NC & LOO* — **no change needed.** PC/NC flags are Intra-assay %CV +
     Inter-assay %CV + historical-IQR position; LOO (`_bg_well_outliers`) is
     Background-only, which is correct (LOO needs ≥3 wells; controls run in
     duplicate → %CV is the right tool). Descriptions already accurate.
  4. *%CV thresholds editable* — they already were (`nc_cv_threshold` drives
     PC+NC intra-assay; `hist_cv_threshold` inter-assay; `bg_cv_threshold`
     background intra). Relabeled Settings fields to standardized "intra/inter-
     assay %CV" wording + clarified PC/NC scope; added "editable on the Settings
     page" notes to the Background/PC/NC report descriptions.
  5. *DBS + cross-run gating* — per user, **hide entirely when absent, no note.**
     DBS already gated; cross-run now wrapped in `{% if cross_run_present %}`
     (previously always shown with an empty-state note — removed).
  - Verified both pool modes render consistently on the Plate-1 subset.
  - **NOTE for user:** the sandbox's saved config is `pool_mode: per_pool` (a
    leftover); production was set to `auto_select`. All new text is mode-aware, so
    both are correct — just confirm the app's saved setting is auto_select.

- **PINNED — `per_pool` / `scoring_pool` mode (decision: LEAVE IN for now).**
  Scoped the wiring: the only real branch point is `build_pool_map()` in
  qc_standard_curve.py (auto_select → `select_pool_per_antigen`; per_pool → one
  `default_scoring_pool` for all). `compute_in_range_table` /
  `compute_concentrations` are generic (consume the pool_map, no mode branch).
  Other mode-dependent surfaces: `_build_clean_results` (pipeline — **export
  master is wide/per-pool ONLY in per_pool**, tidy single-pool in auto_select;
  note `specimens_*.csv` always carries per-pool AU columns regardless of mode),
  report.py `selected_fits` + curve-summary/all-curves blocks + a few mode-aware
  text spots, ~7 report.html text branches, settings.html Mode select +
  scoring_pool input, app.py POST handler, config.py DEFAULTS. **Decision:** keep
  per_pool in (user will verify the app's saved mode = auto_select per run). All
  report text is now mode-aware so both render correctly. If we later remove it:
  default-and-lock the UI to auto_select + (if wanted) decouple
  `_build_clean_results` so the clean `results` master always includes per-pool
  RAU/status columns. → revisit at **v0.4.0**.

- **App icon rebrand (ochre + wordmark).** `scripts/make_icon.py` rewritten:
  lifts the white GDD antibody/curve motif out of the old pink logo (per-pixel
  min-channel mask) and recomposits it on an **icddr,b classic-ochre gradient**
  — a **single solid ochre** `OCHRE=#C67A28` (no gradient, no band). Layout:
  **"BANGLADESH NSL" wordmark across the BOTTOM**, white, in **Century Gothic
  (URW Gothic Demi), all-caps (no letter-spacing)**, sitting directly on the ochre;
  the motif is cropped to its true bounding box (source had ~32% h / ~46% v
  internal padding) and scaled at its native 1.25:1 aspect to a **medium** size
  (`MOTIF_FILL=0.80`) in the area above the text. Text only drawn at ≥ 128 px
  (small menu icons stay motif-only). Bundled fonts under `assets/fonts/`:
  **URWGothic-Demi.otf** (primary, Century Gothic equivalent) + Poppins-Bold +
  NimbusSans-Bold + LiberationSans-Bold fallbacks, so text renders reproducibly on
  CI. Tunables at the top of make_icon.py:
  `OCHRE`, `ICON_TEXT`, `MOTIF_FILL`, `TEXT_MIN_SIZE`. `app_icon.ico`
  regenerated here; **`app_icon.icns` is regenerated by the CI "Generate icons"
  step on macOS** (iconutil) — the committed .icns stays the old pink one until CI
  builds or the script is run on a Mac. (Exact icddr,b brand hex not confirmed —
  site is JS-rendered; hand-matched ochre in OCHRE_TOP/OCHRE_BOTTOM, easy to swap.)

Docs synced (DONE, uncommitted): README.md + SPECIFICATION.md updated for
Phase A (dedicated Dengue vs pan-arbo Institute Pasteur/Orpal; arbovirus own
group; M/D/R/T→NIBSC w/ pan-arbo fallback; other VPDs uncalibrated; dengue
dedicated-scoring preference), the per-standard range-problem specimens table,
the Summary Relevance column + featured-by-pool, the 5-card Bead Count section
(well A1→last ordering), calibration tiers, and 5PL noted as deferred (v0.4.0).
SPECIFICATION.html + BANGLADESH_TODO.html regenerated via pandoc. Version
strings left at 0.1.0-bangladesh (matches APP_VERSION; release decision).
Remaining v0.3.0 pre-release: user commits + tags v0.3.0.
(Original plan text retained below.)

## Planned — v0.3.0 (original plan text) — Phase 10 now targets v0.4.0

Suggested order 8 → 9 → 10 (presentation first, model last); 10 may go first if
we want the model locked before the display rework. One phase per session with a
check-in after each.

### Phase 8 — Featured section organized BY STANDARD POOL
Reorganize "Featured priority antigens" from per-pathogen-category grids into one
section **per standard pool present on the plate**; each antigen is shown fit
**against that section's pool**, so a dengue antigen appears under both Dengue and
Orpal (both fits visible). Pool → relevant antigens (same matching logic as
scoring):
- Anti-OSP & cTxB & HlyE → all cholera + typhoid
- Anti-OSP & cTxB (if separate) → cholera; HlyE (if separate) → typhoid
- Dengue → dengue + other arboviruses + **all VPDs (reference) when no NIBSC**
- Orpal → dengue + other arboviruses + **all VPDs (reference) when no NIBSC**
- NIBSC (when present) → measles/diphtheria/rubella/tetanus (moved out of Dengue/Orpal)
Keep past-plate grey overlay + Show all/Hide toggle + fixed spacing. No-standard
antigens (FLU/malaria/…) are NOT featured (they live in the Summary + collapsed
all-curves). Impl: rewrite `_build_featured_grids` to iterate pools, pulling each
antigen's fit vs that pool from `fits[pool][antigen]` + that pool's history.
**Decision:** VPDs with no NIBSC on the plate show under Dengue & Orpal (reference).

### Phase 9 — Summary tables: ALL antigens + Relevance column
One table per pool listing **every antigen** fit against that pool (all antigen ×
pool); no-standard antigens included via best-fit, **never dropped**. New
**Relevance** column meaning (corrected): **relevance = whether that pool is the
DESIGNATED calibrator/reference for the antigen's pathogen — it has NOTHING to do
with fit quality or best-fit.** Same pool→pathogen mapping as Phase 8:
- Dengue/Orpal table → dengue, other-arbovirus, (no-NIBSC) VPD antigens = relevant;
  cholera/typhoid/FLU/malaria/etc. = not relevant.
- Anti-OSP & cTxB & HlyE table → cholera + typhoid = relevant; rest not relevant.
- NIBSC table → measles/diphtheria/rubella/tetanus = relevant; rest not relevant.
A dengue antigen is "relevant" in BOTH the Dengue and Orpal tables; FLU/malaria are
"not relevant" in every table. Best-fit is used only for scoring/export, never for
this flag. In each table: relevant rows sorted first + coloured, not-relevant
muted, but every antigen's fit is listed; all columns sortable asc/desc on header
click.

### Phase 10 — 5PL model (REPLACE 4PL outright; user's choice, no 4PL fallback)
`five_pl(x,a,b,c,d,g) = d + (a−d)/(1+(x/c)^b)^g` + `invert_5pl`. Update: fitting
(5 params, bounds/initials for g), fit-QC, `compute_concentrations`, reportable
range, `_linear_range_box`, all curve grids, AND the picker's JS curve function.
History gains a `g` column; old 4-param entries read as **g=1** (5PL≡4PL) so past
overlays still render. Non-converging 5PL → NO_FIT (as today). CAVEATS: every
back-calculated RAU changes → prior 4PL reports/history not directly comparable;
needs a validation pass on real plates; g can be poorly constrained on a ~7-point
series (flagged; user chose outright replace anyway). Version the whole batch as
**v0.3.0**.

### Phase 11 — PC/NC variability parity + Range-problem specimens calibration info
Two smaller additions (agreed):
1. **PC & NC parity with Background on variability.** The shared
   `_format_control_stats` already computes intra-plate %CV and inter-assay
   (historical) %CV for PC/NC — just surface them like Background:
   - PC: add an **intra-plate %CV** flag (across its 2 duplicate wells). NC
     already has this as the **Dup. CV** flag.
   - PC **and** NC: add the **High hist. CV** (inter-assay/between-plate) flag
     column + a count card, matching Background.
   - Do NOT add Background's well-outlier or negative-net tables to PC/NC (LOO
     needs ≥3 wells; net-MFI is a specimen-vs-blank concept). Parity = the
     intra + inter %CV flags and cards only.
2. **Range-problem SPECIMENS table — calibration awareness** (a single Standard
   column doesn't fit, since a specimen spans many antigens/pools). Instead:
   - **Option 2 (headline):** per flagged specimen, show a count of its problem
     antigens split **calibrated vs best-fit/uncalibrated** (e.g. "48 problem:
     5 with a real standard, 43 best-fit"), so an all-uncalibrated flag reads as
     low-confidence rather than a real bad well.
   - **Option 1 (detail):** in the row's expandable "problem antigens" list, tag
     each antigen with its pool + tier (e.g. `ARB_DENV1_NS1 (Dengue · dedicated)`,
     `FLU_H1N1 (Orpal · best-fit)`).

### Cross-cutting acceptance criteria (ALL v0.3.0 phases)
- **Standardised labels across every section.** Use one consistent term for each
  concept in Background, PC, NC (cards, table columns, flags, tooltips) and the
  Summary/Featured/Range sections. Canonical terms to settle on and apply
  everywhere:
  - **Intra-plate %CV** (spread across a control's own wells this plate) — today
    called "High CV" in Background and "Dup. CV" in NC → unify wording (note the
    2-well controls' intra %CV *is* the duplicate %CV).
  - **Inter-assay %CV** (between-plate, historical) — today "High hist. CV" →
    unify.
  - Calibration tiers (**dedicated standard / reference / no calibrating
    standard**) and **relevance** (relevant / not relevant) wording identical
    across Summary, Featured, Range-matrix hover, Range-problem tables.
- **Descriptions kept current; no stale text.** Each phase updates the affected
  section's description box(es), and a FINAL sweep before release removes any
  stale/removed-feature wording. Known ones to catch:
  - After **Phase 8**: featured description says "by pathogen category / best-fit
    only" → change to "by standard pool".
  - After **Phase 9**: summary description says no-standard antigens are
    "omitted" → change to "all antigens shown, relevance-flagged".
  - After **Phase 10**: EVERY "4PL" mention in descriptions/labels/section text
    becomes "5PL" (and the `four_pl`→`five_pl` naming, fit-QC notes, picker text).
  - General: remove any lingering "best-fit only" / old per_pool-default wording.
- Regenerate `SPECIFICATION.html` / `BANGLADESH_TODO.html` (pandoc) and sync
  SPECIFICATION.md + README as part of the pre-release docs pass.

---

## Home page: two independent Fit dropdowns + Past-Reports "Fit" column (v0.3.0)

Split the single standard-curve-model selector into **two independent
dropdowns**, one per action, and surfaced the model each report used:

- **Generate Report** keeps its own `curve_model` dropdown (upload form).
- **Regenerate All** now has its own `Fit` dropdown beside the button
  (removed the hidden input + JS value-copy that mirrored the upload dropdown).
  Choosing a model here no longer touches the Generate Report selection, and
  vice-versa. Each defaults to the persisted Settings model.
- The registry (`plate_registry.json`) now stores `curve_model` per plate.
  `_register_plate` records it on upload; `regenerate_all` updates it for each
  regenerated plate. `_list_reports` maps it to a `fit_label` (5PL / 4PL / — for
  legacy reports generated before this change).
- Past Reports table gained a **Fit** column showing that label.

Verified: registry round-trip (update without a model keeps the stored one),
`_list_reports` labels (5PL/4PL/—), and index.html render (two `name="curve_model"`
selects present, hidden input gone, Fit header + cells render).

---

## New-machine naming convention support (dual-format)

The new instrument names each standard by its target instead of a shared
`Pilot Control:` prefix. Added first-class support for both formats with no
config change (small, backward-compatible code change; option chosen: relative
dilution for the mAb Mix series):

- **classify.py** — `_parse_pc` now recognizes `mAb Mix N (…)` (the combined
  cholera OSP/cTxB + typhoid HlyE monoclonal standard) as a 4-fold serial
  dilution: point N → `4^(N-1)` (1,4,…,16384), all eight points collapsing to a
  single `mAb Mix` pool on the same relative (RAU) footing as every other pool.
- **config.py** — default `PC_PATTERNS` expanded to also match `^mAb Mix`,
  `^Measles`, `^Diphtheria`, `^Rubella`, `^Tetanus`, `^Dengue`, `^Cholera Pool`
  (all `^`-anchored so specimens like `BA6208_1:1000_IgG` are never caught).
  Background/NC defaults already covered `Background` / `Negative 0/49`.
- **qc_standard_curve.py** — per-disease VPD scoring groups
  (measles/diphtheria/rubella/tetanus) so each disease-named NIBSC series
  calibrates its own antigens; `_pool_groups` maps the disease-named pools and
  `mAb Mix → {cholera, typhoid}`; `antigen_calibration` reads M/D/R/T scored
  against their disease (or pilot NIBSC) pool as a dedicated **standard**. Pilot
  combined-NIBSC / Orpal / Pasteur behavior unchanged.
- **report.py** — `_pool_target_label` labels the new pools (`mAb Mix` →
  “Cholera · Typhoid”; `Measles` → “Measles”; etc.).
- Docs: README, SPECIFICATION (+ .html), config.example.yaml, and the Settings
  page all note dual-format support.

Verified: unit checks (classification/parse/pool-selection/tier on the exact
new-machine names + no false-positive disease-token matches across the real
201-antigen panel); a full subset pipeline run on a synthesized new-format CSV
(mAb Mix fits one pool → Cholera · Typhoid; each disease standard → its antigen;
5PL banner intact); the pilot fixture still classifies correctly under the new
defaults (0 specimens misclassified); pytest 2/2.

---

## Report layout + content revisions (post new-machine support)

- **Background QC:** the **Background well outliers** table (with its
  explanation) now comes **before** the full per-antigen (202) Background table.
- **Positive Control QC:** in each **Cholera Pool High / Low** stats table, the
  cholera-specific antigens are surfaced at the **top** (rest follow in panel
  order).
- **Measles priority:** `VPD_measles_NP` is no longer a measles priority/featured
  antigen — the measles readout is anchored to **RES_measles_lysate** only.
  `VPD_measles_NP` is still fit and viewable, just never featured or marked
  relevant to the Measles standard (`_VPD_NONPRIORITY` in qc_standard_curve.py).
- **Standard-Curve Summary:** removed the **Range-problem antigens** table (and
  its two summary cards). The **Range-problem specimens — per standard**
  subsection now shows a table for **every dedicated standard** (mAb Mix, Dengue,
  Measles, Diphtheria, Rubella, Tetanus / pilot pools), assessed independently;
  standards with no flagged specimen show a "none flagged" note. Fixed the
  builder so per-disease NIBSC standards count as dedicated (previously only
  cholera/typhoid/dengue were, so disease pools were silently dropped).
- **All Curves Overview:** the **Featured priority antigens** grid is now
  **one curve per row** (room for age figures next to each curve later). The
  collapsed all-curve-fits grids are unchanged.
- **Removed the entire Standard-Curve Range Matrix section** (matrix heatmap,
  Out-of-range detail list, and Serum-vs-DBS comparison), plus its TOC link.
- **Explanation audit:** rewrote the control-pool-handling, per-standard
  range-problem, and Featured blurbs to describe both formats accurately (mAb Mix
  = combined cholera/typhoid; per-disease NIBSC standards; pan-arbovirus
  reference only when present) and removed text for deleted features. README and
  SPECIFICATION (+ .html) updated to match.

Verified end-to-end on a synthesized new-format plate: ordering, cholera-top,
measles priority (RES featured / VPD_measles_NP not), all six per-standard
tables present, removed sections gone, no stale blurbs; pytest 2/2, py_compile
clean.

---

## PC table greying + per-standard blocks for failed fits

- **PC (Cholera High/Low) tables:** cholera-specific antigens are bold at the top;
  the remaining antigens are **greyed (muted)** for context, matching how other
  "all antigens" tables de-emphasize non-focus rows.
- **Per-standard range-problem subsection:** now emits a block for **every**
  dedicated standard on the plate. A standard whose dedicated antigen(s) produced
  no usable reportable range (curve did not fit) shows a "No usable reportable
  range … cannot assess" note instead of being silently dropped; standards with a
  fit but no flagged specimen still show the "none flagged ✓" note.

---

## Phase 1 quick fixes (multi-tab report project)

- **Standard-Curve Picker rug labels** shortened via a new `_compact_plate_label`
  ("Multipathogen_plate1_IgG_8.9.25" → "plate1_8.9.25"); wired into
  `_short_plate_label` fallback so past-plate rug ticks + legends stay short
  (tickfont 8→7). Picker now passes short `pastlabels` for the rug ticks.
- **Cholera curve context lines:** cholera antigen curves in the All-Curves
  Overview now overlay 4 labelled horizontal lines — Cholera High, Cholera Low,
  and each negative control (mean of each control's replicate wells for that
  antigen) — via `_control_context_means` threaded into the featured grid.
- **VPD "concentrations":** confirmed with user these are the `1:N` dilutions
  already shown in hover; added **x/y axis titles** to the one-per-row featured
  All-Curves Overview plots ("Standard dilution (1:x)" / "MFI (log scale)").
  Dense collapsed grids left unlabelled to avoid clutter.

Next phases (agreed order): 2) tab architecture, 3) QA&QC flag tables,
4) plate concordance heatmaps, 5) background-correction comparison, 6) age bars
(UI now, wire age data later; groups 6mo–2y / 3–4y / 5–14y / 15+).

## Phase 1 follow-up fixes

- **Cholera curves showing 10^120 y-axis:** caused by the browser autoranging a
  log axis to include a degenerate fit's runaway curve. Fix: featured (one-per-row)
  panels now set an EXPLICIT y-range from observed data (standards + specimens +
  control lines, ×3 headroom). Context lines switched from `add_hline` to scatter
  traces. Verified cholera panels ~20–400 MFI, dengue ~10^4.9 — no blow-up.
- **Plot spacing:** one-per-row featured layout uses panel_h 210 + gap 100px so
  each plot's x-axis label clears the next plot's title.
- **Picker rug label bug:** `_short_plate_label` fell through to the full id when
  box_ids was an empty list `[]`; fixed (`not box_ids` covers None/""/[]), and box
  ids are appended to the compact `plate<N>_<date>` label when present.

## Phase 2 — tab architecture

Report split into 3 tabs via a sticky top tab bar + JS switching:
- **Plate Overview** — all existing content + its sidebar TOC (unchanged).
- **Quality Assurance & Control** — opens with a "Rerun plan" note (reruns are
  batched at the end of planned testing); placeholder sections "Plate Concordance"
  and "Flag summaries" to be filled in phases 3–4.
- **Background Correction Comparison** — placeholder for the raw/subtracted/divided
  concordance plot (phase 5).
Sidebar sticky offset moved below the tab bar (top:46px). QA/BG panels hidden by
default; overview active on load.

## Phase 3 — QA&QC flag summaries (Sample + Antigen check)

Renamed tab 1 "Plate Overview" → "Plate Report".

QA&QC "Flag summaries" now has two live tables (built in report.py from existing
flag data):
- **Sample check** (`_build_sample_check`) — one row per specimen well with ≥ 1
  flag: low bead count (red/yellow tier), background flag (negative net MFI),
  outside LOD (below/above reportable range); columns plate ID, well, sample ID,
  # flags, flagged antigens, + yes/no per flag. Multiply-flagged wells highlighted.
- **Antigen check** (`_build_antigen_check`) — antigens flagged in > 1 sample,
  high background (mean bg MFI > bg_max_mfi/300), or shifted between plates
  (inter-assay %CV > hist_cv_threshold, Settings-adjustable). yes/no columns.

**Plate check** and **Standard curve check** left as placeholders — they need the
plate-to-plate concordance (Lin's CCC) from Phase 4.

### Deferred (later)
- **Antigen check — dedicated "outside-LOD" column.** The current "flagged in
  >1 sample" column mixes all flag types (bead + background + outside-LOD) and
  trips at ≥2 samples (absolute). The removed Range-problem antigens table
  instead flagged antigens where ≥20% of samples fell outside the reportable
  range (a curve-placement signal). Option kept for later: add a dedicated
  "≥20% of samples outside LOD (yes/no)" column to Antigen check to restore that
  specific signal. Left as-is for now per user.

## Phase 4 — control concordance heatmap + Plate check

- **Lin's CCC** (`_lins_ccc`) on log10 MFI. `_control_profiles` builds 4 per-plate
  control profiles from history_nc/history_pc (Neg 0 / Neg 49 across ALL antigens;
  Cholera High / Low across CHOLERA antigens only), keeping each control a
  SEPARATE well per the user.
- **`_build_control_concordance`** — per plate-pair, one CCC per control; each
  heatmap cell = MEAN of the 4 CCCs (diagonal 1.0). Also computes per-plate
  overall/negative/cholera mean concordance + <0.95 flags, and a "% of plate-pairs
  ≥ 0.95" headline.
- **`_make_concordance_heatmap`** — one combined plate×plate heatmap, RdYlGn scale
  over [0.85,1.0] (red < 0.95), hover shows the 4 individual control CCCs.
- **Plate check table** now live: Plate ID; Low (overall) / Negative / Cholera-pool
  concordance < 0.95 (yes/no + the value). Both heatmap and table show a "needs
  ≥ 2 plates" state when only one plate has control data.
- Verified on the two pilot plates: Plate1 vs Plate2 mean CCC = 0.990 (Neg0 .994,
  Neg49 .990, CholHi .993, CholLo .984), 100% of pairs ≥ 0.95, no plate flagged.
  Full template render confirmed on synthetic 2-plate case; pytest 2/2.

Still a placeholder: **Standard curve check** (needs starting-dilution MFI %CV +
per-standard-curve concordance across plates — a separate cross-plate computation).

### Phase 4 follow-up — plate labels
Concordance heatmap axes, hover (via %{x}/%{y} → "Plate 1 vs Plate 2"), and the
Plate check table now show "Plate N" parsed from the CSV filename (helper
`plate_number_label`, stored as `plate_label` in nc/pc history so past plates are
labeled too; falls back to the short date label if no plate number is present).
Verified on pilots: PLATE_08212025_RUN000 → "Plate 1", PLATE_08252025_RUN000 → "Plate 2".

### Phase 4 follow-up — plate numbering fallback
Concordance plate labels now resolve in priority order: (1) "Plate N" parsed from
the filename / plate_id; (2) if NO plate carries a number, assign "Plate N" by
chronological run date/time from metadata (earliest run = Plate 1); (3) else the
short date label. Verified: two plates with no filename number but run dates get
Plate 1 (earlier run) / Plate 2 (later). Mixed cases keep parsed numbers and don't
collide with positional ones.

## Phase 4b — Standard curve check + shared plate labels

- Refactored plate labeling into shared helpers `_gather_plate_meta` +
  `_label_plates`; `generate_report` builds ONE label map (from nc/pc/std history)
  used by the concordance heatmap, Plate check AND Standard curve check, so all
  three number plates identically.
- **`_build_std_curve_check`** — per (control pool × its RELEVANT antigen)
  standard curve seen on ≥2 plates: starting-dilution MFI %CV across plates
  (> hist_cv_threshold, Settings-adjustable) and per-plate mean Lin's CCC vs
  other plates (log10 MFI over shared dilutions) < 0.95. One row per (plate ×
  curve); only flagged rows shown; empty-state / needs-≥2-plates messages.
- Assumptions (adjustable): "standard curve" = pool × relevant antigen (not
  per-pool, not every antigen); rows per plate×curve. VPD_measles_NP excluded
  (not a relevant/priority curve).
- Verified: 60% MFI shift between plates → 32.6% starting-CV flag + reduced
  concordance flags on shorter curves; full render shows the table; pytest 2/2.

## Descriptions: methodology + de-Orpal sweep

- **QA&QC methodology descriptions:** each section now states WHAT it shows and
  HOW the flags/estimates are derived — Sample check (per-flag derivation: bead
  tier cutoffs, negative net MFI = specimen − mean background, outside LOD vs
  LLOQ/ULOQ), Antigen check (>1-sample count, mean bg MFI > threshold, inter-assay
  %CV), Plate check (mean pairwise Lin's CCC vs other plates, overall/neg/cholera),
  Standard curve check (starting-dilution %CV; per-plate mean CCC over shared
  dilutions). Plate Concordance already had a methods box.
- **Removed stale "Orpal / Institute Pasteur" naming** from all user-facing
  descriptions (report.html, settings.html, config.example.yaml) and docs
  (README, SPECIFICATION + .html), replaced with generic "pan-arbovirus reference
  pool (when present)". Also fixed the SPEC `_pool_groups` map (was missing mAb
  Mix + disease-named NIBSC keywords). The internal keyword matching
  (orpal/pasteur/institut) stays for pilot back-compat; the factual "Pilot pools:"
  list in SPEC is retained as historical context.

### Retire pan-arbovirus reference from going-forward descriptions
Per user: there is no pan-arbovirus reference pool going forward. Removed all
"pan-arbovirus reference pool" mentions from user-facing descriptions (report.html,
settings.html, config.example.yaml, README, SPECIFICATION). Non-dengue arboviruses
now described (and scored) as "no calibrating standard — best-fit only". Code:
antigen_calibration for arbovirus returns "reference" ONLY when scored against a
pool whose groups include arbovirus (legacy pilot pan-arbo pool), else
"uncalibrated" (verified ARB_CHIKV_E2 -> uncalibrated; -> reference only on a
legacy Orpal pool). Legacy orpal/pasteur/institut keyword matching kept for pilot
back-compat and documented as "legacy" only in the technical SPEC.

### Fully retired "Institute Pasteur"
Removed all "Institute Pasteur" mentions from code + user-facing docs: updated
qc_standard_curve.py docstrings/comments (antigen_calibration, _pool_groups,
_antigen_scoring_groups, select_pool_per_antigen) to frame the pan-arbo pool as
legacy-pilot-only; dropped the `pasteur`/`institut` keyword tokens from
`_pool_groups` (kept only `orpal` — the actual pilot pool name — for back-compat);
genericized the SPEC legacy note; updated RELEASE_NOTES_v0.3.0.md. A pool named
"Institute Pasteur" no longer matches; "Orpal pool" still → {dengue, arbovirus}.
(The historical BANGLADESH_TODO dev log retains its Phase A mentions as a record.)

## Phase 5 — Background Correction Comparison tab

- **`_build_bg_correction_concordance`** — plate-pair Lin's CCC (LINEAR scale, so
  ≤0 subtracted values are fine) over the pooled control wells (Neg 0/49 +
  Cholera High/Low, mean per control × antigen) shared between two plates, under
  three methods: Raw MFI; Background subtracted (well MFI − mean blank per
  antigen); Background divided (well MFI ÷ mean blank). Blank = mean of the
  plate's Background wells per antigen (from history_background).
- **`_ccc_bootstrap_ci`** — 95% percentile bootstrap CI over the paired points.
- **`_make_bg_correction_plot`** — grouped scatter: x = plate pairs, y = CCC,
  one series per method (Okabe–Ito colors) with CI error bars + a 0.95 guide line;
  matches the example figure. Rendered in the Background Correction Comparison tab
  with a full "how it is derived" description; "needs ≥2 plates" fallback.
- Verified on the two pilot plates (Raw 0.989, Subtracted 0.989, Divided 0.986,
  CIs ~±0.01) and a synthetic 2-plate render; pytest 2/2.

All planned phases (1–5) complete. Remaining deferred: Phase 6 age-stratified bars
(needs age data; UI-now / wire-later, groups 6mo–2y / 3–4y / 5–14y / 15+); optional
Antigen-check "outside-LOD" column.

### Phase 5 correction — sample-based (not controls)
Per user: the background-correction comparison should reflect the SAMPLES, not the
controls. Rebuilt `_build_bg_correction_concordance` to use history_specimens:
each antigen summarised by the MEAN of that plate's specimen wells, then Lin's CCC
across antigens between plate pairs (linear scale), under raw / subtracted (mean
sample MFI − mean blank per antigen) / divided (÷ mean blank). Bootstrap resamples
antigens for the 95% CI. Description + fallback text updated (specimen-based).
Verified on pilots: Raw 0.989 / Subtracted 0.988 / Divided 0.989 (CIs ~0.96–0.995).

### Plate-label consistency + multi-plate verification
- `_label_plates` rewritten: use parsed "Plate N" ONLY if every plate has a
  distinct parsed number; otherwise number all plates by chronological run order
  (earliest = Plate 1). Fixes the mixed case (one plate parsed "Plate 2", another
  falling back to a date label) — labels are now always "Plate N" across the
  concordance heatmap, Plate check, Standard curve check, and Background
  Correction tabs. Also fixes stale-history plates (processed before plate_label
  existed) at render time.
- Verified with 3 plates: heatmap axes Plate 1/2/3; Background Correction shows
  all pairs (1v2, 1v3, 2v3). Concordance heatmap is a full N×N matrix and the
  correction plot covers all N·(N−1)/2 pairs, so both scale as more plates run.

## Phase 6 — age-stratified range-status bars

- **src/age.py** — loads the individual age form (lenient column detection: id =
  blood_sample_collection_id/etc., age = age_years_final); bins age into 4 groups
  (6 mo–2 yrs [0–2] / 3–4 / 5–14 / 15+); maps specimen sample name → id (leading
  token before "_") → age group.
- **Landing page:** optional "Individual age data CSV" upload; saved once as
  results/age_data.csv (global) and reused by every plate incl. Regenerate All.
- **Pipeline:** loads age_data.csv (default results/age_data.csv), builds
  {sample_name → age_group}, passes to generate_report (`specimen_age`).
- **Report:** `_age_status_counts(in_range, specimen_age)` →
  {antigen: {age_group: {status: count}}}. Featured All-Curves Overview becomes a
  2-column layout (curve | age bars) via `_make_curve_grid_interactive` age_mode;
  `_add_age_bars` draws horizontal stacked bars, one per age group, segmented by
  range status (Below/In/Above Range, No Fit — same colours/legend as the rug),
  x = % of samples, with "N (%)" labels; barmode=stack.
- Graceful when no age file (normal one-per-row curves). Verified end-to-end with
  48 specimens across all 4 groups matched from the real age form; pytest 2/2.
- Assumption: integer ages, 0–2 → "6 mo–2 yrs" (survey doesn't enrol <6 mo);
  specimens without a matched/parseable age are omitted from the bars.

### Phase 6 follow-up — age diagnostics + robustness
- Age id matching now case-insensitive / whitespace-tolerant.
- Featured section shows an age-status banner so it's clear WHY bars are/aren't
  shown: "No age data uploaded" / "loaded but 0 of N specimen IDs matched" /
  "M of N specimens matched" (age_info from pipeline).
- Upload handler now accepts the age CSV ON ITS OWN (no plate required) — saves it
  globally; user then Regenerate All. Verified via Flask test client.

### Phase 6 diagnostics v2
Age banner now distinguishes 4 states (and shows the resolved path):
(1) file not found at path — "No age data uploaded (Looked for <path>)";
(2) file found but unparseable — "could not be read (needs id + age columns)";
(3) loaded but 0 specimen IDs matched; (4) M of N matched (bars shown).
Pipeline resolves age_data.csv from output_dir.parent OR history_dir.parent.
Verified all four branches render correctly. (Full app flow upload→age→regenerate
also verified earlier via Flask test client.)

### Phase 6 fix — the actual bug: required plate field blocked age-only upload
Root cause: the plate-CSV file input had HTML `required`, so the browser refused
to submit the form when ONLY the age CSV was selected → age_data.csv never saved
(server-side age-only path was never reached). Removed `required` (server still
validates). Added a landing-page indicator: red "No age data loaded yet" / green
"✓ Age data currently loaded (N participants)" (index() checks results/age_data.csv).
Verified: reads the real form as 3882 participants; age-only submit now reaches
the server.

### Phase 6 — second age view (status → age breakdown)
Per user: keep the per-age bars AND add "of all samples below/within/above/no-fit,
what's the age breakdown?". Featured grid is now 3 columns per antigen:
curve | "Range status by age group" (col2, within-age %) | "Age breakdown by range
status" (col3, within-status % — `_add_status_age_bars`, segmented by age group,
distinct age-group colours). Both normalised to 100% along their own bars, N (%)
labels. Banner describes both views. Verified end-to-end render.

### Phase 6 — reverted the second age view (too much info)
Per user: dropped the "Age breakdown by range status" (status→age) third column;
back to 2-column featured layout (curve | "Range status by age group"). Removed
_add_status_age_bars + _AGE_GROUP_COLORS (no dead code) and the two-view banner
wording. Verified: single age chart renders, second gone, pytest 2/2.
