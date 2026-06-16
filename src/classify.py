"""Classify wells as PC standard, background, NC, or specimen.

Bangladesh National Serosurveillance assay (384-well, Intelliflex). There
is no Intelliflex input file, so the per-well ``sample_name`` from the CSV
is the only classification signal. Each name is matched against the
configured regex patterns, checked in this order:

    Background  : '^Background'                    → background  ('Background0')
    NC          : 'Negative'                       → nc          ('Pilot Control: Negative 0 , 1:1000')
    PC/standard : '^Pilot Control:'                → pc          ('Pilot Control: Dengue pool 1:4000')
    Specimen    : everything else                  → specimen    ('12602_r3_Serum')

NC is checked *before* PC on purpose: both NC and PC samples share the
'Pilot Control:' prefix, so the more-specific 'Negative' match must win.
Patterns are matched with ``re.search`` (not anchored) and are editable on
the Settings page.

For PC wells, the **pool** and **dilution** are parsed from the sample name
(``pc_pool``, ``dilution`` columns):

    'Pilot Control: Dengue pool 1:4000'                  → pool='Dengue pool',  dilution=4000,  x_kind='dilution'
    'Pilot Control: Orpal pool 1:800'                    → pool='Orpal pool',   dilution=800
    'Pilot Control: Anti-OSP & cTxB & HlyE pool 1:16'    → pool='Anti-OSP & cTxB & HlyE pool', dilution=16
    'Pilot Control: HlyE 50 ng/mL'                       → pool='HlyE', dilution=50, x_kind='concentration'
    'Pilot Control: Cholera High (1:1000)'               → pool='Cholera High', dilution=NaN, single_point=True

A descriptive parenthetical (e.g. '(Anti OSP IgG-125ng/ml …)') is stripped
before parsing so the pool label is stable across plates. Single-point
controls (e.g. Cholera High/Low) get ``dilution=NaN`` and are flagged via
``pc_single_point`` so the report shows them as reference markers rather
than fitting a curve to a single point.
"""

from __future__ import annotations

import re

import pandas as pd

from .config import (
    PC_PATTERNS,
    BACKGROUND_PATTERNS,
    NC_PATTERNS,
)


# Authoritative mapping from an Intelliflex input file's `Type` column
# (lower-cased) to our internal well_type enum, kept for any future plate
# that ships an input file. Bangladesh pilots have none, so the
# sample-name regex below is the working path.
_PWT_TO_WELL_TYPE: dict[str, str] = {
    "standard":   "pc",
    "background": "background",
    "control":    "nc",
    "unknown":    "specimen",
}


def classify_wells(df: pd.DataFrame, config: dict | None = None) -> pd.DataFrame:
    """Add ``well_type``, ``dilution``, ``pc_pool``, ``pc_single_point`` and
    ``pc_x_kind`` columns. See module docstring for the rules."""
    pc_pats = PC_PATTERNS
    bg_pats = BACKGROUND_PATTERNS
    nc_pats = NC_PATTERNS
    if config is not None:
        wc = config.get("well_classification", {})
        pc_pats = wc.get("pc_patterns", pc_pats)
        bg_pats = wc.get("background_patterns", bg_pats)
        nc_pats = wc.get("nc_patterns", nc_pats)

    df = df.copy()

    df["well_type"] = df["sample_name"].apply(
        lambda n: _classify_sample(n, pc_pats, bg_pats, nc_pats)
    )

    # When an input file is present (future plates), its plate_well_type
    # is authoritative and overrides the regex result.
    if "plate_well_type" in df.columns:
        pwt = df["plate_well_type"].astype(str).str.strip().str.lower()
        mapped = pwt.map(_PWT_TO_WELL_TYPE)
        override_mask = mapped.notna()
        df.loc[override_mask, "well_type"] = mapped[override_mask]

    # Parse pool / dilution from PC sample names.
    is_pc = df["well_type"] == "pc"
    parsed = df.loc[is_pc, "sample_name"].apply(_parse_pc)
    df["pc_pool"] = None
    df["dilution"] = float("nan")
    df["pc_single_point"] = False
    df["pc_x_kind"] = None
    if is_pc.any():
        df.loc[is_pc, "pc_pool"] = parsed.apply(lambda p: p["pool"])
        df.loc[is_pc, "dilution"] = parsed.apply(lambda p: p["dilution"])
        df.loc[is_pc, "pc_single_point"] = parsed.apply(lambda p: p["single_point"])
        df.loc[is_pc, "pc_x_kind"] = parsed.apply(lambda p: p["x_kind"])

    if config is not None:
        spec_dil = config.get("specimens", {}).get("default_dilution")
        if spec_dil is not None:
            df.loc[df["well_type"] == "specimen", "dilution"] = float(spec_dil)
    return df


def _classify_sample(
    name: str,
    pc_patterns: list[str],
    background_patterns: list[str],
    nc_patterns: list[str],
) -> str:
    name = (name or "").strip()
    # Order matters: background → nc → pc → specimen. NC must beat PC
    # because both share the "Pilot Control:" prefix.
    for pat in background_patterns:
        if re.search(pat, name, re.IGNORECASE):
            return "background"
    for pat in nc_patterns:
        if re.search(pat, name, re.IGNORECASE):
            return "nc"
    for pat in pc_patterns:
        if re.search(pat, name, re.IGNORECASE):
            return "pc"
    return "specimen"


def _parse_pc(name: str) -> dict:
    """Parse a PC sample name into pool label, dilution, and x-axis kind.

    Returns dict: {pool, dilution, single_point, x_kind} where
    ``x_kind`` ∈ {'dilution', 'concentration', 'single'}.
    """
    s = (name or "").strip()
    # Drop the shared "Pilot Control:" prefix.
    s = re.sub(r"^\s*Pilot Control:\s*", "", s, flags=re.IGNORECASE)
    # Strip any descriptive parenthetical, e.g. "(Anti OSP IgG-125ng/ml …)"
    # or "(1:1000)". This normalizes the pool label across plates.
    paren = re.findall(r"\(([^)]*)\)", s)
    s_noparen = re.sub(r"\([^)]*\)", "", s).strip().strip(",").strip()

    # 1) Dilution series: trailing "1:N" (commas allowed in N).
    m = re.search(r"1\s*:\s*([\d,]+)\s*$", s_noparen)
    if m:
        dil = float(m.group(1).replace(",", ""))
        pool = s_noparen[: m.start()].strip().strip(",").strip()
        return {"pool": pool, "dilution": dil, "single_point": False, "x_kind": "dilution"}

    # 2) Concentration series: trailing "N ng/mL" (HlyE).
    m = re.search(r"([\d.]+)\s*ng\s*/?\s*m?l\s*$", s_noparen, flags=re.IGNORECASE)
    if m:
        conc = float(m.group(1))
        pool = s_noparen[: m.start()].strip().strip(",").strip()
        return {"pool": pool, "dilution": conc, "single_point": False, "x_kind": "concentration"}

    # 3) Single-point control (e.g. "Cholera High", "Cholera high/ low: High").
    #    No fittable series; show as a reference marker. If the original had
    #    a "(1:N)" parenthetical, surface that dilution for context.
    dil = float("nan")
    for p in paren:
        mm = re.search(r"1\s*:\s*([\d,]+)", p)
        if mm:
            dil = float(mm.group(1).replace(",", ""))
            break
    pool = s_noparen if s_noparen else s.strip()
    return {"pool": pool, "dilution": dil, "single_point": True, "x_kind": "single"}
