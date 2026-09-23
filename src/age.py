"""Individual age metadata: load the participant form and map each specimen to
an age group for the age-stratified range-status bars.

The age form (uploaded once on the home page) has one row per participant with a
blood-sample collection id and an age in years. Specimens on a Luminex plate are
named like ``DH1867_1:1000_IgG``; the leading token (``DH1867``) is the
collection id we join on.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

# Ordered age groups (young → old). Kept as an ordered list so plots and tables
# always show them in the same sequence.
AGE_GROUPS = ["6 mo–2 yrs", "3–4 yrs", "5–14 yrs", "15+ yrs"]


def age_group(age) -> str | None:
    """Bin an age in years into one of ``AGE_GROUPS`` (None if not parseable).

    Integer ``age_years_final`` values are assumed, so 0–2 yrs → "6 mo–2 yrs"
    (the survey does not enrol infants under 6 months), 3–4 → "3–4 yrs",
    5–14 → "5–14 yrs", ≥ 15 → "15+ yrs".
    """
    try:
        a = float(age)
    except (TypeError, ValueError):
        return None
    if a != a or a < 0:
        return None
    if a < 3:
        return AGE_GROUPS[0]
    if a < 5:
        return AGE_GROUPS[1]
    if a < 15:
        return AGE_GROUPS[2]
    return AGE_GROUPS[3]


def specimen_id_from_sample(sample_name) -> str:
    """Extract the collection id from a Luminex sample name.

    ``DH1867_1:1000_IgG`` → ``DH1867``; ``10012_r3_Serum`` → ``10012``. The id is
    the leading token before the first underscore.
    """
    s = str(sample_name or "").strip()
    if not s:
        return ""
    return re.split(r"[_\s]", s, maxsplit=1)[0]


def load_age_data(path) -> pd.DataFrame | None:
    """Load the age form, returning a tidy DataFrame with columns
    ``[id, age, age_group]``, or None when the file is missing / unreadable.

    Column names are detected leniently: the id column is the one containing
    "collection_id" / "blood_sample" / "sample_id" / "barcode" (else the first
    column), and the age column contains "age".
    """
    path = Path(path)
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except Exception:
        try:
            df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="latin-1")
        except Exception:
            return None
    if df.empty:
        return None
    cols = {c.lower().strip(): c for c in df.columns}

    def _find(preds, fallback=None):
        for want in preds:
            for lc, orig in cols.items():
                if want in lc:
                    return orig
        return fallback

    id_col = _find(["blood_sample_collection_id", "collection_id", "sample_id",
                    "barcode", "individual_id"], fallback=df.columns[0])
    age_col = _find(["age_years", "age"])
    if age_col is None:
        return None

    out = pd.DataFrame({
        "id": df[id_col].astype(str).str.strip(),
        "age": pd.to_numeric(df[age_col], errors="coerce"),
    })
    out["age_group"] = out["age"].apply(age_group)
    out = out[(out["id"] != "") & out["id"].notna()]
    # Keep the first non-null age per id.
    out = out.sort_values("age", na_position="last").drop_duplicates("id", keep="first")
    return out.reset_index(drop=True)


def specimen_age_groups(age_df: pd.DataFrame | None, sample_names) -> dict:
    """Map each sample name to its age group via the collection id.

    Returns ``{sample_name: age_group}`` (only sample names that match an id with
    a parseable age). ``age_df`` is the output of :func:`load_age_data`.
    """
    if age_df is None or age_df.empty:
        return {}
    # Case-insensitive / whitespace-tolerant id matching.
    lut = {str(i).strip().upper(): g
           for i, g in zip(age_df["id"], age_df["age_group"]) if g}
    out = {}
    for name in set(map(str, sample_names)):
        g = lut.get(specimen_id_from_sample(name).strip().upper())
        if g:
            out[name] = g
    return out
