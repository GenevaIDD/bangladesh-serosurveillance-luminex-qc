"""Parse xPONENT CSV files from MagPix and Intelliflex Luminex instruments.

Both instrument families share the same xPONENT-style multi-block CSV
layout (`"DataType:","Median"` / `"Count"` / etc.) so a single parser
handles both. The `Program` header field is captured so downstream code
can branch on instrument type when needed.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd


def parse_xponent_csv(path: str | Path) -> dict:
    """Parse an xPONENT CSV file into metadata + merged long-format data.

    Returns dict with keys:
        metadata: dict of plate-level metadata (plate_id, batch, run_date,
                  operator, protocol, instrument_sn, instrument_program,
                  panel_name, ...)
        data: long-format DataFrame with columns
              [well, sample_name, analyte, mfi, count]
    """
    path = Path(path)
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    rows = list(csv.reader(lines))

    metadata = _parse_metadata(rows)
    metadata["file"] = path.name

    block_starts = _find_datatype_blocks(rows)
    if "Median" not in block_starts or "Count" not in block_starts:
        raise ValueError(
            f"Missing Median or Count data block in {path.name}; "
            f"found blocks: {sorted(block_starts)}"
        )

    mfi_wide = _parse_data_block(rows, block_starts["Median"])
    counts_wide = _parse_data_block(rows, block_starts["Count"])

    analytes = [c for c in mfi_wide.columns if c not in ("well", "sample_name", "total_events")]
    # Authoritative panel for this plate, in the order the instrument
    # exported them. Pipeline code uses this rather than the cached
    # config panel so the per-plate analyte list is always correct.
    metadata["analytes"] = list(analytes)

    mfi_long = _wide_to_long(mfi_wide, analytes, "mfi")
    counts_long = _wide_to_long(counts_wide, analytes, "count")

    merged = mfi_long.merge(counts_long, on=["well", "sample_name", "analyte"])

    return {"metadata": metadata, "data": merged}


def _parse_metadata(rows: list[list[str]]) -> dict:
    """Extract plate metadata from header rows (everything before first DataType:)."""
    meta: dict = {}
    field_map = {
        "Batch": "batch",
        "Date": "run_date",
        "Operator": "operator",
        "ProtocolName": "protocol",
        "ProtocolDescription": "protocol_description",
        "SN": "instrument_sn",
        "BatchStartTime": "batch_start_time",
        "BatchStopTime": "batch_stop_time",
        "PanelName": "panel_name",
        "BatchDescription": "batch_description",
    }
    for row in rows:
        if not row or not row[0].strip('"'):
            continue
        key = row[0].strip('"')
        if key == "DataType:":
            break  # metadata ends where the data blocks begin
        if key == "Program" and len(row) > 1:
            # "Program","xPONENT","","Intelliflex"  → instrument_program = "Intelliflex"
            # MagPix files have "Program","xPONENT" only.
            meta["instrument_program"] = (
                row[3].strip('"') if len(row) > 3 and row[3].strip('"') else row[1].strip('"')
            )
            continue
        if key == "Date" and len(row) > 2 and row[2].strip('"'):
            d = row[1].strip('"')
            t = row[2].strip('"')
            meta["run_date"] = f"{d} {t}"
            continue
        if key in field_map and len(row) > 1:
            meta[field_map[key]] = row[1].strip('"')
        if key == "Samples" and len(row) > 1:
            try:
                meta["n_samples"] = int(row[1].strip('"'))
            except ValueError:
                pass
    meta["plate_id"] = _extract_plate_id(meta.get("batch", ""))
    return meta


def _extract_plate_id(batch: str) -> str:
    """Derive a short plate ID from the batch string.

    MagPix convention:  'A260323-MP1822-KV02-Plate01-12PlxMPXVHIg' → 'A260323-MP1822-KV02-Plate01'
    Intelliflex convention:  'PLATE_05112026_RUN000' → 'PLATE_05112026_RUN000' (used verbatim)
    """
    if not batch:
        return ""
    m = re.match(r"(.+-Plate\d+)", batch)
    if m:
        return m.group(1)
    return batch


def _find_datatype_blocks(rows: list[list[str]]) -> dict[str, int]:
    blocks = {}
    for i, row in enumerate(rows):
        if len(row) >= 2 and row[0].strip('"') == "DataType:":
            dtype = row[1].strip('"')
            blocks[dtype] = i
    return blocks


def _parse_data_block(rows: list[list[str]], block_start: int) -> pd.DataFrame:
    header_row = rows[block_start + 1]
    col_names = [c.strip('"') for c in header_row]

    data_rows = []
    for i in range(block_start + 2, len(rows)):
        row = rows[i]
        if not row or not row[0].strip('"'):
            break
        data_rows.append([c.strip('"') for c in row])

    df = pd.DataFrame(data_rows, columns=col_names)
    df["well"] = df["Location"].apply(_parse_well_from_location)
    df = df.rename(columns={"Sample": "sample_name"})

    analyte_cols = [c for c in col_names if c not in ("Location", "Sample")]
    for col in analyte_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if "Total Events" in df.columns:
        df = df.rename(columns={"Total Events": "total_events"})

    df = df.drop(columns=["Location"])
    return df


def _parse_well_from_location(loc: str) -> str:
    """'1(1,A1)' → 'A1'."""
    m = re.search(r"\d+\(\d+,([A-H]\d+)\)", loc)
    if m:
        return m.group(1)
    return loc


def _strip_bead_prefix(name: str) -> str:
    """Strip numeric bead-region prefix when present: '01 MVA Ag' → 'MVA Ag'.

    Intelliflex names like 'RES_Ade3' have no numeric prefix and pass through.
    """
    m = re.match(r"^\d+\s+(.+)$", name)
    return m.group(1) if m else name


def _wide_to_long(df: pd.DataFrame, analyte_cols: list[str], value_name: str) -> pd.DataFrame:
    id_cols = ["well", "sample_name"]
    long = df[id_cols + analyte_cols].melt(
        id_vars=id_cols, var_name="analyte", value_name=value_name
    )
    long["analyte"] = long["analyte"].apply(_strip_bead_prefix)
    return long
