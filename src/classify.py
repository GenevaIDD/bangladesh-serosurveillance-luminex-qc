"""Classify wells as PC standard, background, NC, or specimen.

Classification priority:

1. **Authoritative — input file Type column.** When the Intelliflex
   ``*_inputfile.csv`` is uploaded, its ``Type`` field for each well is
   carried into a ``plate_well_type`` column by
   ``parse_layout.build_layout`` (lower-cased). When present it is the
   primary signal and maps as:

       Type=Standard    → well_type = pc
       Type=Background  → well_type = background
       Type=Control     → well_type = nc
       Type=Unknown     → well_type = specimen

   This lets operators name a Control well anything (e.g. ``NI7``,
   ``Pool_B``) and still have it classified correctly.

2. **Fallback — sample-name regex.** When the input file is absent,
   or for any well whose ``plate_well_type`` is missing / unrecognised,
   the per-well ``sample_name`` is matched against the configured
   regex patterns:

       PC          : '^Standard\\d+$'
       Background  : '^Background'
       NC          : '^NC' / '^Negative' / '^Control'
       Specimen    : everything else (typically 'FD########' barcodes)

   Patterns are editable on the Settings page.

Dilution for PC wells is looked up by the trailing integer of the
``Standard{N}`` name into ``config['standard']['dilutions']``. This is
the same in both classification paths because Intelliflex auto-generates
``Standard1`` .. ``Standard10`` as the sample name for Standard-type
wells even when the operator left ``Description`` blank.
"""

from __future__ import annotations

import re

import pandas as pd

from .config import (
    PC_PATTERNS,
    BACKGROUND_PATTERNS,
    NC_PATTERNS,
    STANDARD_DILUTIONS,
)


# Authoritative mapping from the Intelliflex input file's `Type`
# column (lower-cased) to our internal well_type enum. Anything not
# in this map falls back to sample-name regex classification.
_PWT_TO_WELL_TYPE: dict[str, str] = {
    "standard":   "pc",
    "background": "background",
    "control":    "nc",
    "unknown":    "specimen",
}


def classify_wells(df: pd.DataFrame, config: dict | None = None) -> pd.DataFrame:
    """Add ``well_type`` and ``dilution`` columns.

    See module docstring for the classification priority (input-file
    ``plate_well_type`` column wins; sample-name regex is the
    fallback).
    """
    pc_pats = PC_PATTERNS
    bg_pats = BACKGROUND_PATTERNS
    nc_pats = NC_PATTERNS
    dilution_series = STANDARD_DILUTIONS
    if config is not None:
        wc = config.get("well_classification", {})
        pc_pats = wc.get("pc_patterns", pc_pats)
        bg_pats = wc.get("background_patterns", bg_pats)
        nc_pats = wc.get("nc_patterns", nc_pats)
        std_dils = config.get("standard", {}).get("dilutions")
        if isinstance(std_dils, list) and std_dils:
            dilution_series = [float(d) for d in std_dils]

    df = df.copy()

    # Start with the regex-derived classification. This always runs —
    # it's the source of truth when no input file was uploaded, and
    # the fallback for any plate_well_type the input file leaves
    # blank or labels with an unrecognised value.
    df["well_type"] = df["sample_name"].apply(
        lambda n: _classify_sample(n, pc_pats, bg_pats, nc_pats)
    )

    # When the input file is present, ``plate_well_type`` is the
    # authoritative signal — override the regex result for every row
    # whose plate_well_type maps to a known well_type.
    if "plate_well_type" in df.columns:
        pwt = df["plate_well_type"].astype(str).str.strip().str.lower()
        mapped = pwt.map(_PWT_TO_WELL_TYPE)
        override_mask = mapped.notna()
        df.loc[override_mask, "well_type"] = mapped[override_mask]

    df["dilution"] = df["sample_name"].apply(lambda n: _dilution_for_pc(n, dilution_series))

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
    for pat in pc_patterns:
        if re.match(pat, name, re.IGNORECASE):
            return "pc"
    for pat in background_patterns:
        if re.match(pat, name, re.IGNORECASE):
            return "background"
    for pat in nc_patterns:
        if re.match(pat, name, re.IGNORECASE):
            return "nc"
    return "specimen"


def _dilution_for_pc(name: str, dilution_series: list[float]) -> float:
    """Standard1 → dilution_series[0]; Standard10 → dilution_series[9].

    Returns NaN for non-Standard names.
    """
    m = re.match(r"^Standard(\d+)$", (name or "").strip(), re.IGNORECASE)
    if not m:
        return float("nan")
    idx = int(m.group(1)) - 1
    if 0 <= idx < len(dilution_series):
        return float(dilution_series[idx])
    return float("nan")
