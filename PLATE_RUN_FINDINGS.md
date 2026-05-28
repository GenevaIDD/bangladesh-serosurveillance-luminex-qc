# Uvira 200-plex — Plate-run findings log

Running historical record of observations from each plate processed
through the Uvira Luminex QC tool. Distinct from
[`UVIRA_TODO.md`](UVIRA_TODO.md) — that doc tracks the app's
development; this doc tracks **wet-lab** observations and any anomalies
the QC pipeline surfaced for each plate run.

**Audience:** the operators running the assay and anyone reviewing the
generated HTML reports. Each entry summarises what the report showed,
what looked good vs. broken, and any follow-up indicated.

**Conventions used below:**

- "S1/S2 ratio" = MFI(Standard1) / MFI(Standard2) for a given antigen.
  A clean 4-fold serial dilution should give roughly **4×**.
- "fit_ok" = Standard-Curve Summary verdict in the report (R² ≥ 0.95
  on log10 MFI, IC50 inside the tested range, Hill slope 0.3–5.0,
  dynamic range ≥ 3×).
- "Box1 xlsx" refers to `RENAMED-Box1_Uvira_sera_2023.xlsx`.

---

## Plate index

| # | Plate ID | Run date | PMT mode | Specimens | NCs | Status |
|---|---|---|---|---|---|---|
| 1 | `PLATE_05112026_RUN000` | 2026-05-11 | **High** | 84 | none | ✅ Standard curves clean, used as pilot baseline |
| 2 | `PLATE_05182026_RUN000` | 2026-05-18 | **High** | 82 | 2 (NI7, NI18) | ❌ **Standard curve broken** — S1 only, S2–S10 at noise floor |
| 3 | `PLATE_05272026_RUN000` | 2026-05-27 | **Low** ⚠ | 82 | 2 (NI7, NI18) | ⚠ **Wrong PMT mode**; standards also broken (S1 → S2 ~10× too big) |
| 4 | `PLATE_05272026_RUN002` | 2026-05-27 | **High** | 82 | 2 (NI7, NI18) | ⚠ **High-PMT re-read of plate 3**. Standards still broken (same wet-lab issue); Background levels now in line with other High-PMT plates |

> **⚠ Watch the PMT mode.** As of Session 15 the Plate Overview banner
> at the top of every report shows the **Operating mode** (`FLEXMAP 3D®
> High PMT` vs `Luminex® 200™ Low PMT`). Low-PMT plates report MFI
> roughly an order of magnitude lower than High-PMT, so Background
> levels, standards-curve dynamic range, and cross-plate overlays in
> the Background MFI scatter all need to be interpreted with the mode
> in mind. The report flags Low-PMT runs with a yellow `⚠ Low PMT`
> badge. **Do not compare a Low-PMT plate to High-PMT history at face
> value.**

---

## Bead counts — gating QC

**A plate isn't usable if its bead counts are bad** — every other QC
metric (curve fits, range classification, AU values) is derived
*per-bead* from the raw MFI of the matching bead region, so a well
that read only a handful of beads on a given antigen produces a
noisy, unreliable MFI for that cell. The report's Bead-Count Matrix
section is therefore the first thing to check on any new plate.

Thresholds (defaults; editable on the Settings page):

- **Red** — bead count `<` `bead_count_min` (default **30**). Bead
  loss / aspiration issue; the corresponding (well × antigen) MFI is
  not trustworthy.
- **Yellow** — `30 ≤` count `<` `bead_count_warn` (default **50**).
  Borderline; treat with caution.
- **Green** — count `≥ 50`. OK.

A plate-level flag fires when **≥ 20 %** (`problem_fraction_threshold`,
editable) of an antigen's wells are red+yellow, or vice-versa for
specimens.

### Bead-count summary across all plates

| Plate | PMT | Red cells | Yellow cells | Antigens flagged ≥ 20 % | Specimens flagged ≥ 20 % |
|---|---|---|---|---|---|
| Pilot (05-11) | High | **430** | **856** | 7 | 6 |
| Re-run 1 (05-18) | High | 1 | 311 | 0 | 3 |
| Re-run 2 first try (05-27 RUN000) | Low | **0** | **4** | 0 | 0 |
| Re-run 2 high-PMT re-read (05-27 RUN002) | High | **19** | **1,028** | 6 | 6 |

**Trend**: bead counts improved dramatically from the pilot to
re-run 2 (first try). The 27-05 RUN000 plate was the cleanest so far
— 0 red cells and only 4 yellow cells across 19,400 (well × antigen)
pairs, no antigens flagged.

**Read-2 degradation, plate 4**: the high-PMT re-read of the same
physical plate (`PLATE_05272026_RUN002`) shows **19 red + 1,028
yellow** cells, plus 6 antigens and 6 specimens flagged. The plate
itself didn't change between reads — the second reading lost a
chunk of beads. This is expected behaviour for Luminex re-reads
(bead settling / aspiration losses on the second pass) and is a
**reason to prefer the first read whenever possible**, even if the
first read had a sub-optimal PMT setting. If a re-read is required,
expect bead counts to drop.

The pilot's higher bead-count failure rate is consistent with this
being the first plate run as the assay was being shaken down. The
two re-runs benefited from operational refinements (until plate 4's
re-read introduced its own bead-recovery issue).

### What to look for

- **Red cells clustered on a single well** → suspect a clogged
  aspirator or a mis-pipetted volume on that well.
- **Red cells clustered on a single antigen across many wells** →
  suspect a bead-prep issue specific to that region (low input,
  aggregation, etc.).
- **Whole-plate elevated red counts** → suspect bead handling /
  vortexing / dilution prep before plate loading.

Plates with `Antigens flagged ≥ 20 %` or `Specimens flagged ≥ 20 %`
should be flagged for review before any downstream interpretation.

---

## Background MFI — running history

Plate blanks (A11 / A12 with PBT only — no specimen, no standard)
should read at the bead noise floor for every antigen. Antigens
where the Background MFI consistently exceeds **300** are candidates
for either:

- **Cross-reactivity** in the bead region (the bead conjugate is
  picking up something from the buffer / detection antibody).
- **Sticky / contaminated bead lot** in the panel.
- **Carry-over** from neighbouring high-signal wells in the assay
  (less likely for plate-blank wells in Row A).

### Antigens with Background MFI > 300 (any plate, High-PMT only)

> **Compare High-PMT plates to High-PMT plates only.** The Low-PMT
> column (plate 3 RUN000) is shown for transparency but should
> *not* be used as a baseline for either flagging or trend analysis
> — Low-PMT MFI is ~10× lower than High-PMT for the same wells.

| Antigen | Pilot (05-11) **High** | Re-run 1 (05-18) **High** | Re-run 2 (05-27 RUN000) **Low ⚠** | Re-run 2 (05-27 RUN002) **High** |
|---|---|---|---|---|
| `SARS_CoV-2_Spike_Omicron` | **3,953** ⚠ | **1,516** ⚠ | 329 ⚠ | **2,775** ⚠ |
| `BAC_Chlamydia_pneumoniae` | **1,213** ⚠ | **1,282** ⚠ | 141 | **1,059** ⚠ |
| `FLU_H5N1_HA1_Hubei_2010` | **843** ⚠ | **781** ⚠ | 97 | **732** ⚠ |
| `ARB_YFV_NS1` | **618** ⚠ | **574** ⚠ | 62 | **469** ⚠ |
| `HHV_HHV7` | **509** ⚠ | **517** ⚠ | 50 | **333** ⚠ |
| `ENT_Norovirus_GII.6_VLP` | 57 | **349** ⚠ | 7 | 54 |
| `FLU_H3N2_HA1_Texas_1977` | **347** ⚠ | **315** ⚠ | 40 | 289 |

(7 antigens have crossed the 300 MFI threshold on at least one
High-PMT plate.)

### Key observations

- **PMT setting explains the plate-3 anomaly.** In a previous review
  we observed that plate 3 (`PLATE_05272026_RUN000`) read
  dramatically lower Background MFI than the other plates. The
  high-PMT re-read of the same physical plate
  (`PLATE_05272026_RUN002`) brings Background levels back in line
  with the pilot and re-run 1 — confirming this was an instrument
  setting issue (Low PMT was selected by mistake), not an assay
  drift. The Operating Mode field in the Plate Overview banner now
  flags Low-PMT runs with a `⚠ Low PMT` badge so this is spottable
  at a glance on future plates.
- **The persistently-noisy antigens hold up across all three High-PMT
  plates:**
  - `SARS_CoV-2_Spike_Omicron` (1,516–3,953 MFI background)
  - `BAC_Chlamydia_pneumoniae` (1,059–1,282)
  - `FLU_H5N1_HA1_Hubei_2010` (732–843)
  - `ARB_YFV_NS1` (469–618)
  - `HHV_HHV7` (333–517)

  These five are strong candidates for the **persistently noisy bead
  region** investigation list — likely a bead-conjugate or
  cross-reactivity issue rather than per-plate prep variability.
- **The default `bg_max_mfi=100` flag (Settings page) catches ~93
  antigens on the pilot but only 7 cross the 300 MFI bar.** The
  300-MFI threshold used here is more conservative and may be a
  better default for the Uvira panel — worth revisiting once 5+
  High-PMT plates are in hand to gauge typical variance.

A new entry should be appended to this table whenever a new plate is
processed. Antigens consistently above 300 MFI across multiple
**High-PMT** plates are candidates for soft-flagging on the Settings
page.

---

## Plate 1 — `PLATE_05112026_RUN000` (Pilot, 2026-05-11)

### Layout
Row A — Standards A1–A10 (`Standard1`…`Standard10`), Background A11 / A12.
Rows B–H — 84 unknown specimens from **Box1** (row H of the Box1 xlsx
was intentionally omitted on this plate: box rows A–G shift to plate
rows B–H, columns stay 1:1).

### What the report showed
- **All 200 antigens** parsed from the `Median` block header.
- **Standard curves were clean.** S1/S2 ratios ≈ 2–4× for every antigen
  (HylE 2.4×, CtxB 3.0×, Inaba_OSP 2.4×, Ogawa_OSP 2.4×, HBsAg 3.7×,
  ZIKV NS1 4.0×, YFV E 2.6×, Ade5_hexon 1.7×, CMV 2.2×). Consistent
  with a clean 4-fold serial dilution.
- 4PL fits passed `fit_ok` for the great majority of antigens. The
  three soft-flagged "added in error" bead regions
  (`FLU_B_HA_Maryland_1959`, `FLU_B_NP_Brisbane_2008`, `VPD_Tet_tox`)
  read 0–3.6% in-range as expected and are visually muted in every
  table.
- Range matrix populated: 13,625 IN_RANGE / 2,159 ABOVE_RANGE / 764
  BELOW_RANGE / 252 NO_FIT (= 84 × 3 excluded analytes).
- 14 of 14 patient-ID spot-checks against the Box1 xlsx **passed**
  (Session 11 validation). Confirmed the expected **box-row → plate-row
  shift** (box A → plate B, …, box G → plate H, because plate row A
  holds Standards / Background).
- Background QC: 0 antigens CV-flagged at the default 25 % cutoff;
  93 antigens max-flagged at the default `bg_max_mfi=100` (default is
  aggressive for this panel — adjustable on the Settings page).

### Issues observed
- **None on the lab side**. This plate is the working reference for
  the assay.
- App-side observation: the default `bg_max_mfi=100` cut-off flags a
  lot of antigens (93/200). Worth revisiting whether the threshold
  should be panel-specific.

### Follow-up
- This plate is the **canonical "good" plate**. When comparing
  subsequent plates, use this one's Standard-Curve Summary and
  Background MFI overview as the reference baseline.

---

## Plate 2 — `PLATE_05182026_RUN000` (Re-run #1, 2026-05-18)

### Layout
Same as the pilot, with two **`Control`** wells added in H11 / H12
(named `NI7` and `NI18` in the input file's `Description` column). Row
H specimens (H1–H10) were now loaded, so the plate carries the same
82 unknown samples that the pilot did + 2 NCs.

### What the report showed
- **NC QC section populated for the first time**. NI7 / NI18 each get
  a per-antigen MFI row in the heatmap; values are appended to
  `nc_well_history.json` for cross-plate tracking.
- 82 specimens (not 84) — H11 / H12 are now NCs, not unknowns.
- Patient-ID resolution: 82/82 (every unknown matched the Box1 xlsx).

### Issues observed
**Standard curves were broken.** Only Standard1 received the
standards-+mAbs pool — Standards 2–10 sat at the bead noise floor,
statistically indistinguishable from the Background wells (A11 / A12).

S1 → S2 ratios for the mAbs and a few strong-signal standards
(should be ~4× for a 4-fold dilution):

| Antigen | S1 MFI | S2 MFI | **S1/S2** |
|---|---|---|---|
| BAC_S.typhi_HlyE *(mAb)* | 26,861 | 67 | **402×** |
| CHO_CtxB *(mAb)* | 7,986 | 128 | **63×** |
| CHO_Inaba_OSP *(mAb)* | 56,677 | 84 | **676×** |
| CHO_Ogawa_OSP *(mAb)* | 61,307 | 81 | **761×** |
| HEP_HBsAg | 1,291 | 46 | 28× |
| ARB_YFV_E | 6,315 | 73 | 86× |
| RES_Ade5_hexon | 11,472 | 95 | 121× |
| HHV_CMV | 24,721 | 154 | 161× |

**Smoking gun**: rows A2 through A10 are statistically indistinguishable
from A11 / A12 (Background). Example, HHV_CMV across A2–A10:
154 / 153 / 142 / 155 / 158 / 146 / 150 / 154 / 151 — same population
as Background's 151 / 155 for the same antigen.

### Most likely cause
The serial dilution from A1 → A2 → A3 → … → A10 **did not propagate**.
A1 received the standards+mAb pool correctly (signal magnitudes
roughly tracking the pilot's S1), but A2–A10 contain PBT diluent only.
Possible operational causes (any one of these matches the pattern):

1. The carryover transfer step (`5 µL pool + 15 µL PBT`) was skipped
   after the first dilution — only A1 was inoculated, A2–A10 were
   filled with PBT only.
2. The pipette tip went into the wrong source tube when transferring
   from A1 → A2, aspirating buffer instead of A1's standard mix. Every
   subsequent carryover then propagated buffer.

### App behaviour on this plate
- Standard-Curve Summary lists most antigens as `fit_ok = FAIL`
  (R² and dynamic-range criteria can't be satisfied with one signal
  point above a flat tail).
- LLOQ / ULOQ are uncalculable → Range Matrix shows mostly `NO_FIT`.
- **Bead-count QC, Background QC, and NC QC (NI7 / NI18) remain
  valid** and are useful on their own.
- The Background MFI overview shows this plate sitting at a similar
  level to its own "standards" — visual corroboration of the
  diagnosis.

### Recommendation
**Re-run with the standards dilution series performed correctly.**
Specifically: verify that each step `A{n} → A{n+1}` actually transfers
5 µL from A{n} into the 15 µL PBT in A{n+1}, with the **same pipette
tip path** every step.

Specimen interpretations (AU, range classification) from this plate
**should not be trusted**.

---

## Plate 3 — `PLATE_05272026_RUN000` (Re-run #2, 2026-05-27)

### Layout
Identical to Plate 2 — same 82 unknown specimens, same NC wells
(`NI7` / `NI18` in H11 / H12), same Standards / Background convention.

### What the report showed
- NC QC section continues to populate (now showing 2 plates of NC
  history — Plate 2 and Plate 3).
- All cross-plate overlays now show **3 plates** (pilot + Plate 2 +
  Plate 3) in the curve picker legend, Background MFI overview, etc.
- 82 specimens, 197 antigens parsed.

### Issues observed
**Standard curves are better than Plate 2 but still off.** The
dilution series partially propagated this time, but the step from
S1 → S2 is much too big (≈10× larger than the expected 4×):

| Antigen | S1 MFI | S2 MFI | **S1/S2** | S1/S10 |
|---|---|---|---|---|
| BAC_S.typhi_HlyE *(mAb)* | 4,973 | 130 | **38×** | 828× |
| CHO_CtxB *(mAb)* | 1,725 | 46 | **38×** | 130× |
| CHO_Inaba_OSP *(mAb)* | 8,059 | 188 | **43×** | 833× |
| CHO_Ogawa_OSP *(mAb)* | 9,373 | 207 | **45×** | 1,327× |
| ARB_YFV_E | 698 | 19 | **37×** | 81× |
| RES_Ade5_hexon | 1,365 | 52 | **26×** | 313× |
| HHV_CMV | 3,400 | 71 | **48×** | 791× |

**A strong second clue** that this is a wet-lab issue and not an
instrument issue: **A3 reads higher than A2** for multiple antigens.
Example values for HylE: 4,973 / 130 / 376 / 13 / 7 / 6 / 6 / 6 / 5 / 6
across A1..A10. A3 = 376 is **2.9× A2's 130** — mechanically impossible
for a clean serial dilution down the row (A3 should be ¼ of A2).

CtxB shows the same pattern: 1,725 / 46 / 106 / 19 / 14 / 14 / 15 / 14
/ 15 / 13. Inaba_OSP: 8,059 / 188 / 578 / 19 / 9 / 8 / 8 / 8 / 9 / 10.

### Most likely cause
A2 received less standard than A3 (or A3 received an over-volume),
i.e. the second dilution step wasn't a clean 5 µL carry-over. Possible
operational variants:

1. The second-dilution transfer aspirated **less than 5 µL** out of
   A1, leaving A2 under-inoculated; the third step took a normal 5 µL
   out of A2 but the A2 → A3 step compounded the under-volume, so A3
   ended up *closer* to what A2 should have been if the second step
   had worked correctly.
2. The volume of PBT in A2 was higher than the protocol's 15 µL,
   diluting the carry-over excessively.
3. Independent (wrong-tip-or-source) errors at A2 specifically —
   consistent with the non-monotonic A2 < A3 pattern.

### App behaviour on this plate
- Most antigens will fail `fit_ok` — there's effectively a 2-point
  curve (A1 high, A3 lower) followed by 7 points at noise. The
  dynamic-range and R² criteria don't tolerate this shape.
- The cross-plate Background MFI overview shows this plate as a
  third trace (toggleable). Patterns there look comparable to the
  pilot for most antigens — i.e. the *background bead reads*
  themselves look normal on this plate; only the standards row
  failed.

### Recommendation
**Re-run again** with the dilution series performed correctly. Pay
particular attention to **A1 → A2 → A3** — that's where this plate
fell off. As before, specimen interpretations should not be trusted
until a working curve is in hand.

---

## Plate 4 — `PLATE_05272026_RUN002` (High-PMT re-read of Plate 3, 2026-05-28)

### Layout
Same physical plate as Plate 3, re-read on the Intelliflex with the
**High PMT** setting (`FLEXMAP 3D® High PMT`) instead of Plate 3's
incorrect Low PMT. Identical sample layout: 82 specimens (B1–H10) +
2 NCs in H11 / H12 (`NI7`, `NI18`) + Standards A1–A10 + Background
A11 / A12. Batch ID: `PLATE_05272026_RUN002`; ran 18:32 → 19:41 on
the same day as Plate 3's first read.

### What the report showed
- **Operating mode badge confirms `FLEXMAP 3D® High PMT`** in the
  Plate Overview banner (green text, no warning badge).
- Background MFI levels are back in line with the pilot / Plate 2
  for the noisy antigens — `SARS_CoV-2_Spike_Omicron` 2,775,
  `BAC_Chlamydia_pneumoniae` 1,059, etc. Cross-plate Background
  overview now shows 4 traces with the Low-PMT outlier (Plate 3) and
  three comparable High-PMT plates.
- NC QC populated (NI7 / NI18) for the third plate in a row; the
  cross-plate NC heatmap now shows 3 plates of NC history.

### Issues observed

**Issue 1 — Standards curve is still broken.** Re-reading at High
PMT did not recover the dilution series. S1/S2 ratios on the new
plate (should be ~4×):

| Antigen | S1 MFI | S2 MFI | **S1/S2** | S3 MFI |
|---|---|---|---|---|
| BAC_S.typhi_HlyE *(mAb)* | 35,756 | 959 | **37×** | 2,727 *(↑ vs S2)* |
| CHO_CtxB *(mAb)* | 11,999 | 292 | **41×** | 691 *(↑ vs S2)* |
| CHO_Inaba_OSP *(mAb)* | 59,988 | 1,312 | **46×** | 4,217 *(↑ vs S2)* |
| CHO_Ogawa_OSP *(mAb)* | 76,504 | 1,515 | **51×** | 4,668 *(↑ vs S2)* |
| HHV_CMV | 23,004 | 424 | **54×** | 1,253 *(↑ vs S2)* |
| ARB_YFV_E | 4,470 | 116 | **39×** | 228 *(↑ vs S2)* |
| RES_Ade5_hexon | 9,589 | 290 | **33×** | 890 *(↑ vs S2)* |

Same pathology as Plate 3's first read: **A3 reads higher than A2**
for every checked antigen, S1 → S2 is ~10× the expected step. This
**rules out PMT or detection** as the cause of the standards problem
— it's definitively the wet-lab dilution preparation. The same
broken series is now visible at higher dynamic range, but the shape
is unchanged.

**Issue 2 — Read-2 bead recovery degraded.** Re-reading the same
physical plate at High PMT shows **19 red + 1,028 yellow** bead-count
cells (vs **0 red + 4 yellow** on Plate 3's first read). 6 antigens
and 6 specimens are now flagged at the ≥ 20 % threshold. The plate
sat for several hours between reads, and bead losses on a second
read are well known. **Prefer first reads.** If a re-read is
necessary (e.g. because the first read had a wrong PMT), expect bead
counts to drop and treat the second-read data accordingly.

### Most likely cause (standards)
Same as Plate 3 — the A1 → A2 carryover step under-transferred or
the A2 well was over-volume diluent. Independent of detection
mode; this is a pipetting protocol issue.

### App behaviour on this plate
- Standard-Curve Summary will fail `fit_ok` for nearly every
  antigen (same reason as Plate 3).
- LLOQ / ULOQ are bogus → Range Matrix will show many false
  IN_RANGE cells against the broken curve bounds (this is the
  same false-confidence issue called out in
  [`UVIRA_TODO.md`](UVIRA_TODO.md) Section 9; the proposed strict
  `fit_ok` gating would resolve it).
- Bead-count summary cards flag this plate's bead-count issue
  prominently (6 antigens / 6 specimens flagged).
- Background QC heatmap and cross-plate Background overview both
  show the persistent-noise pattern restored to expected magnitudes
  (`SARS_CoV-2_Spike_Omicron` etc.).

### Recommendation
This plate's specimen-level interpretation should still **not** be
trusted because the standards series is broken (same root cause as
Plate 3). The high-PMT re-read does confirm the PMT mistake on
Plate 3 was the explanation for the Background-MFI anomaly there,
which is useful for the cross-plate trend record.

**For the next re-run**: fix the A1 → A2 carryover step (verify
pipette tip path, volume, and PBT pre-fill volume in A2), and keep
the operating mode on `FLEXMAP 3D® High PMT` from the start.

---

## Cross-plate observations

### Standard-curve dilution pattern
After four plates, the dilution-series-execution failure has been
seen on every re-run; only the pilot has a working curve:

| Plate | PMT | S1/S2 ratio (mAbs) | Verdict |
|---|---|---|---|
| Pilot (05-11) | High | **2.4 – 3.0×** | ✅ Correct |
| Re-run 1 (05-18) | High | **63 – 760×** | ❌ Series didn't propagate past A1 |
| Re-run 2 first try (05-27 RUN000) | Low ⚠ | **38 – 45×** | ⚠ A2 partial; A2 < A3 in many antigens |
| Re-run 2 re-read (05-27 RUN002) | High | **33 – 54×** | ⚠ Same broken series visible at higher PMT — confirms wet-lab not detection |

The high-PMT re-read of Plate 3 (Plate 4) confirms the standards
problem on Plate 3 is **wet-lab**, not instrument-related — same
broken series shape at both PMT settings, with A3 > A2 on every
mAb antigen. Worth reviewing the wet-lab protocol with whoever ran
the re-runs:

- Was the same operator on Plates 2 and 3? Same pipette / tips /
  buffer prep?
- Was the A1 → A2 carryover step verified for the right volume +
  source well?
- Was the PBT pre-fill in A2..A10 the expected 15 µL?

### NC tracking
`nc_well_history.json` now has 3 plates of NI7 / NI18 readings.
With more plates, the cross-plate NC heatmap in the report will let
you spot drift on any antigen. Pre-empt the moment when a
particular antigen starts reading consistently above noise in the
NCs — that's the early-warning signal for cross-reactivity /
contamination / plate-setup error.

### PMT operating mode — new gating check
As of Session 15 the Plate Overview banner shows the **Operating
mode** for every plate, flagged with a yellow `⚠ Low PMT` badge
when on the Luminex 200 Low PMT setting. **Always confirm PMT mode
matches the rest of the history** before interpreting cross-plate
trends; a single Low-PMT run mixed into a High-PMT history will
look like a Background / signal drop of ~10× when it's really
just a detection-settings difference.

### Antigens flagged on every plate
The three default soft-flagged ("added in error") bead regions
have been visually muted on every plate so far:

- `FLU_B_HA_Maryland_1959`
- `FLU_B_NP_Brisbane_2008`
- `VPD_Tet_tox`

These are not assay failures — the panel was built with these regions
present in error. They remain in the data and CSVs but are excluded
from any laboratory decision.

### Background-MFI default threshold
`bg_max_mfi=100` flags ~93 antigens on every plate. Either:

1. The default is too aggressive for the Uvira panel (raise on the
   Settings page), or
2. There's a population of antigens where the bead/buffer
   combination genuinely sits above 100 — worth investigating
   panel-wide once the standards problem is resolved.

---

## Open lab questions

**Operating mode**
- The Operating Mode field in the Plate Overview now flags
  Low-PMT runs. **Before every run, confirm the protocol on the
  Intelliflex is set to `FLEXMAP 3D® High PMT`** (or whichever mode
  the project standardises on). The Low-PMT mistake on Plate 3
  cost a re-read.

**Standards-curve protocol** (Plates 2, 3, and 4 all show the
dilution-series failure — independent of PMT mode):
- Was the same operator on Plates 2 / 3 / 4? Same pipette / tips /
  buffer prep?
- Was the standards+mAb pre-dilution (`5 µL MAbs + 11.8 µL PBT +
  3.2 µL Stds pool`) performed in a separate tube each time, then
  loaded into A1 — or was it prepared once in A1 directly?
- Was the carry-over series (`5 µL pool + 15 µL PBT` from A1
  onward) done with a clean tip change between each well, or a
  single tip?
- Could there be an issue with the PBT volume dispensed into
  A2..A10 before the carry-over step started?
- On Plates 3 and 4 specifically: why does **A3 read higher than
  A2** for the mAbs? This is mechanically inconsistent with a
  serial dilution down the row — A2 received less standard, or A3
  received extra. Worth checking the pipette / tip alignment on
  the A1 → A2 step in particular.

**Re-reads**
- Bead recovery degraded substantially on the second read of Plate 3
  (Plate 4). **Prefer first reads.** If a re-read is unavoidable
  (e.g. wrong PMT mode), expect the bead-count summary to flag
  more antigens / specimens.

---

*Last updated: Session 15 (2026-05-28). Append a new entry below this
line for each subsequent plate run.*
