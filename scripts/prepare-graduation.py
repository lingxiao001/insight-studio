"""Prepare the pinned public Graduation workbook locally; never publish student rows."""
import argparse
import hashlib
from pathlib import Path
import re

import pandas as pd

WORKBOOK_SHA256 = "e131105640e0a4c43064897e1d5871844b9b4ff98698831687ace8ff85453450"


def prepare(path):
    if hashlib.sha256(path.read_bytes()).hexdigest() != WORKBOOK_SHA256:
        raise ValueError("Input does not match the published Graduation V1 Data.xlsx checksum.")
    frame = pd.read_excel(path, sheet_name="Various Scores", header=1, engine="openpyxl")
    if frame.shape != (253, 86):
        raise ValueError("Expected the original 253-row, 86-column course sheet with two header rows.")
    frame.columns = [re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_") for name in frame.columns]
    frame = frame.rename(columns={"name": "student_id", "cet_4": "cet4", "cet_6": "cet6"})
    if not frame.columns.is_unique:
        raise ValueError("Normalized column names must be unique.")
    averages = {
        "career_guidance_mean": [c for c in frame if c.startswith("career_development_and_employment_guidance_for_college_students_part_")],
        "situation_policy_mean": [c for c in frame if c.startswith("situation_and_policy_")],
    }
    if [len(c) for c in averages.values()] != [5, 7]:
        raise ValueError("Expected five career-guidance and seven situation-policy columns.")
    for name in frame:
        if name not in {"student_id", "gender"}:
            frame[name] = pd.to_numeric(frame[name], errors="raise")
    starts = {columns[0]: target for target, columns in averages.items()}
    members = {column for columns in averages.values() for column in columns}
    result = pd.DataFrame(index=frame.index)
    for name in frame:
        if name in starts:
            target = starts[name]
            result[target] = frame[averages[target]].mean(axis=1, skipna=False)
        elif name not in members:
            result[name] = frame[name]
    if result.shape != (253, 76):
        raise ValueError("Prepared shape must be 253 rows and 76 columns.")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Original Data.xlsx from Graduation V1, DOI 10.17632/c8ypkyswv3.1")
    parser.add_argument("--output", type=Path, required=True, help="Private local CSV path; do not commit the prepared rows")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.output.exists() and not args.overwrite:
        parser.error("Output already exists; choose another path or explicitly pass --overwrite.")
    try:
        result = prepare(args.input)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    result.to_csv(args.output, index=False, encoding="utf-8", lineterminator="\n")
    args.output.chmod(0o600)
    print("Prepared 253 rows and 76 fields locally; no rows were uploaded or published.")


if __name__ == "__main__":
    main()
