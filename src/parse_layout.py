"""Read plate-layout files: the Intelliflex 'inputfile' CSV and (optional)
Box barcode-to-patient-ID xlsx.

The Intelliflex software exports an *inputfile.csv* alongside the result
CSV; it maps each well to a ``Type`` (Standard / Background / Unknown)
and a ``Description`` (the on-plate barcode for Unknown wells). Each
plate is filled from one physical Box, so a separate Box xlsx maps the
on-plate barcodes to patient IDs (the ``Barcode`` and ``ID`` columns).

Both files are uploaded manually by the user; no auto-matching is done.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def read_inputfile_csv(path: str | Path) -> pd.DataFrame | None:
    """Read an Intelliflex *_inputfile.csv.

    Returns a DataFrame with columns:
        well, plate_well_type, barcode

    ``plate_well_type`` is normalized to lowercase: 'standard', 'background',
    'unknown'. ``barcode`` is the ``Description`` column (the FD-prefixed
    on-plate barcode for Unknown wells; empty for Standards/Backgrounds).

    Returns None if the file can't be parsed.
    """
    path = Path(path)
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception as exc:
        logger.warning("Could not parse inputfile CSV '%s': %s", path, exc)
        return None

    cols = {c.lower().strip(): c for c in df.columns}
    if "location" not in cols or "type" not in cols:
        logger.warning("inputfile CSV '%s' missing required columns Location/Type", path)
        return None

    out = pd.DataFrame({
        "well": df[cols["location"]].astype(str).str.strip(),
        "plate_well_type": df[cols["type"]].astype(str).str.strip().str.lower(),
    })
    if "description" in cols:
        out["barcode"] = df[cols["description"]].astype(str).str.strip()
        out.loc[out["barcode"].isin(("", "nan", "NaN")), "barcode"] = ""
    else:
        out["barcode"] = ""

    return out.reset_index(drop=True)


def read_box_xlsx(path: str | Path) -> pd.DataFrame | None:
    """Read a Renamed_*_Box_*_Sera_*.xlsx barcode-map workbook.

    Expected columns include (case-insensitive, leading/trailing whitespace
    tolerated): ``Barcode`` and ``ID`` (the patient ID). Optionally also
    ``Row``, ``Column``, ``Container Id``, ``Scan Time`` — kept for
    traceability.

    Returns a DataFrame with columns:
        barcode, patient_id, box_id (when available), source_row, source_col

    Returns None if the file can't be parsed.
    """
    path = Path(path)
    if not path.exists():
        return None
    try:
        df = pd.read_excel(path, sheet_name=0)
    except Exception as exc:
        logger.warning("Could not parse Box xlsx '%s': %s", path, exc)
        return None

    cols = {str(c).lower().strip(): c for c in df.columns}
    if "barcode" not in cols or "id" not in cols:
        logger.warning("Box xlsx '%s' missing Barcode/ID columns", path)
        return None

    out = pd.DataFrame({
        "barcode": df[cols["barcode"]].astype(str).str.strip(),
        "patient_id": df[cols["id"]].astype(str).str.strip(),
    })
    if "container id" in cols:
        out["box_id"] = df[cols["container id"]].astype(str).str.strip()
    if "row" in cols:
        out["source_row"] = df[cols["row"]].astype(str).str.strip()
    if "column" in cols:
        out["source_col"] = df[cols["column"]].astype(str).str.strip()

    # Drop empty/NaN barcodes
    out = out[out["barcode"].notna() & (out["barcode"] != "") & (out["barcode"].str.lower() != "nan")]
    return out.reset_index(drop=True)


def build_layout(
    inputfile_path: str | Path | None,
    box_xlsx_path: str | Path | None = None,
) -> pd.DataFrame | None:
    """Build a unified well-level layout table.

    Returns DataFrame with columns:
        well, plate_well_type, barcode, patient_id, box_id (when known)

    ``patient_id`` is left as an empty string when no Box xlsx is provided
    or the barcode isn't present in it.

    Returns None if the inputfile CSV is missing / unparseable.
    """
    inputs = read_inputfile_csv(inputfile_path) if inputfile_path else None
    if inputs is None:
        return None

    if box_xlsx_path:
        box = read_box_xlsx(box_xlsx_path)
    else:
        box = None

    if box is not None and not box.empty:
        merged = inputs.merge(box, on="barcode", how="left")
    else:
        merged = inputs.copy()
        merged["patient_id"] = ""

    if "patient_id" not in merged.columns:
        merged["patient_id"] = ""
    merged["patient_id"] = merged["patient_id"].fillna("")
    return merged


# ---- Backward-compat shim ---------------------------------------------------
# Old callers (pipeline.py) use ``read_plate_layout(path)`` and expect a
# layout with a ``sample_id`` column. Keep the name but route it through
# ``build_layout``, returning ``well`` + ``sample_id`` (= patient_id when
# present, else barcode).

def read_plate_layout(path: str | Path) -> pd.DataFrame | None:
    """Compatibility wrapper.

    Treats ``path`` as an Intelliflex inputfile CSV. Returns a DataFrame
    with columns [well, sample_id], where ``sample_id`` falls back to the
    on-plate barcode (no patient-ID lookup — that requires a Box xlsx, see
    ``build_layout``).
    """
    layout = build_layout(path, box_xlsx_path=None)
    if layout is None:
        return None
    out = layout[["well", "barcode"]].rename(columns={"barcode": "sample_id"})
    return out
