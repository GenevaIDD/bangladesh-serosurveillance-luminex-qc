"""JSON-based historical tracking of QC metrics across plates."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def load_history(path: str | Path) -> pd.DataFrame:
    """Load history from a JSON file. Returns empty DataFrame if file doesn't exist."""
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data:
        return pd.DataFrame()
    return pd.DataFrame(data)


def append_history(existing: pd.DataFrame, new: pd.DataFrame, key_cols: list[str]) -> pd.DataFrame:
    """Append new data to history, deduplicating on key_cols."""
    if existing.empty:
        return new.copy()
    if new.empty:
        return existing.copy()
    combined = pd.concat([existing, new], ignore_index=True)
    combined = combined.drop_duplicates(subset=key_cols, keep="last")
    return combined


def save_history(df: pd.DataFrame, path: str | Path) -> None:
    """Save history DataFrame to JSON file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    records = df.to_dict(orient="records")
    # Convert any numpy types to native Python for JSON serialization
    cleaned = []
    for rec in records:
        cleaned.append({k: _to_native(v) for k, v in rec.items()})
    path.write_text(json.dumps(cleaned, indent=2), encoding="utf-8")


def _to_native(val):
    """Convert numpy/pandas types to native Python for JSON."""
    import numpy as np
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    if isinstance(val, (np.bool_,)):
        return bool(val)
    if pd.isna(val):
        return None
    return val
