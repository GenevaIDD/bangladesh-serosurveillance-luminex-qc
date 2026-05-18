"""Classify wells as PC standard, background, NC, or specimen from sample names.

Uvira / Intelliflex sample-name conventions:
    PC standards : 'Standard1' .. 'Standard10'  (one well each, no replicate)
    Background   : 'Background'                 (A11 / A12 plate blanks)
    NC           : 'NC*' / 'Negative*'          (optional — known seronegative sample)
    Specimen     : everything else              (typically 'FD########' barcodes)

The pilot plate has only Background wells.  NC wells, when present on
future plates, are the named negative control sample and get a
dedicated section in the QC report.

Dilution for PC wells is looked up by the trailing integer of the
'Standard{N}' name into config['standard']['dilutions'].
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


def classify_wells(df: pd.DataFrame, config: dict | None = None) -> pd.DataFrame:
    """Add well_type and dilution columns based on sample_name."""
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
    df["well_type"] = df["sample_name"].apply(
        lambda n: _classify_sample(n, pc_pats, bg_pats, nc_pats)
    )
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
