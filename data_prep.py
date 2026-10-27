"""
Run this whenever you have a NEW historian export to refresh the dashboard's
data. It rebuilds raw_data.csv.gz from a Sigma compressor export (same
column convention: comp{n}/ref_comp_c{n}_{tag}).

Usage:
    python data_prep.py /path/to/new_export.xlsx
"""
import re
import sys

import pandas as pd

TAG_PATTERN = re.compile(r"comp(\d+)/ref_comp_c\d+_(\w+)")


def build_raw_csv(xlsx_source, out_path: str = "raw_data.csv.gz"):
    """xlsx_source: a file path, or a file-like object (e.g. a Streamlit
    UploadedFile) — pandas/openpyxl accept both. Returns the processed
    DataFrame (also written to out_path as a gzip-compressed CSV)."""
    df = pd.read_excel(xlsx_source, sheet_name="in", engine="openpyxl")
    if df.shape[1] < 2:
        raise ValueError("Sheet 'in' has no tag columns beyond the timestamp column.")
    df.rename(columns={df.columns[0]: "timestamp"}, inplace=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    newcols = {"timestamp": "timestamp"}
    matched = 0
    for col in df.columns[1:]:
        m = TAG_PATTERN.search(str(col))
        if m:
            newcols[col] = f"C{m.group(1)}_{m.group(2)}"
            matched += 1
    if matched == 0:
        raise ValueError(
            "No columns matched the expected comp{n}/ref_comp_c{n}_{tag} naming "
            "convention — this doesn't look like a Sigma compressor historian export."
        )
    df.rename(columns=newcols, inplace=True)
    df.to_csv(out_path, index=False, compression="gzip")
    print(f"Wrote {out_path}: {df.shape[0]:,} rows x {df.shape[1]} columns, "
          f"{df['timestamp'].min()} to {df['timestamp'].max()}")
    return df


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python data_prep.py /path/to/new_export.xlsx")
        sys.exit(1)
    build_raw_csv(sys.argv[1])
