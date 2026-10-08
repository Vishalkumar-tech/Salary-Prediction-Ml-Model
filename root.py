from flask import Flask, render_template, request, jsonify, send_file

import pandas as pd

import numpy as np

import os

import re
import io
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MASTER_FILE = os.path.join(BASE_DIR, "Master_SKU.xlsx")

ALLOWED_EXTENSIONS = {"xlsx", "xls", "csv"}

# Running-weight control range requested for the dashboard/report.
# These are percentages around the supplied Spec value.
TOLERANCE_LOW_PERCENT = -5
TOLERANCE_HIGH_PERCENT = 5

BUCKETS = [

    "<-5%", "-5%", "-4%", "-3%", "-2%", "-1%", "0%",

    "1%", "2%", "3%", "4%", "5%", ">5%"

]

def allowed_file(filename):

    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def normalize_column_name(value):

    """Normalize Excel headers while preserving percentage bucket signs.



    In particular, <-5% and >5% must remain different headers.

    """

    value = str(value).strip().lower()

    value = value.replace("−", "-").replace("–", "-").replace("—", "-")

    value = value.replace("_", " ")

    # Normalize common variants such as "- 5 %" -> "-5%".

    value = re.sub(r"\s+", " ", value)

    value = re.sub(r"\s*([<>+-])\s*", r"\1", value)

    value = re.sub(r"\s*%\s*", "%", value)

    # Keep <, >, +, - and % because they are meaningful in the report.

    value = re.sub(r"[^a-z0-9%<>+\- ]+", " ", value)

    return re.sub(r"\s+", " ", value).strip()

def find_column(df, candidates):

    normalized = {normalize_column_name(c): c for c in df.columns}

    for candidate in candidates:

        key = normalize_column_name(candidate)

        if key in normalized:

            return normalized[key]

    for candidate in candidates:

        key = normalize_column_name(candidate)

        for n, original in normalized.items():

            if key == n or key in n or n in key:

                return original

    return None

def find_bucket_column(df, bucket):
    """Find a bucket column robustly.

    Excel may return percentage headers in several forms:
      <-5%, -0.05, -0.04, ..., 0, 0.01, ..., 0.05, >5%

    Numeric decimal headers are interpreted as percentage fractions:
      -0.05 -> -5%, 0.01 -> 1%, 0.05 -> 5%.
    """
    target = str(bucket).strip().lower()

    # Boundary buckets.
    if target in {"<-5%", ">5%"}:
        for col in df.columns:
            raw = str(col).strip().lower().replace("\xa0", " ")
            compact = re.sub(r"\s+", "", raw)
            compact = compact.replace("−", "-").replace("–", "-").replace("—", "-")
            compact = re.sub(r"\.\d+$", "", compact)
            if compact in {target, target[:-1]}:
                return col
        return None

    try:
        target_number = int(target.replace("%", "").strip())
    except (TypeError, ValueError):
        return None

    for col in df.columns:
        # First handle real numeric Excel headers.
        if isinstance(col, (int, float, np.integer, np.floating)) and not isinstance(col, bool):
            value = float(col)
            # Excel-style fraction: -0.05 means -5%.
            if abs(value) <= 1:
                pct = value * 100.0
                if abs(pct - target_number) < 1e-9:
                    return col
            # Also accept whole-number numeric headers such as -5, 0, 5.
            if abs(value - target_number) < 1e-9:
                return col
            continue

        raw = str(col).strip().lower().replace("\xa0", " ")
        compact = re.sub(r"\s+", "", raw)
        compact = compact.replace("−", "-").replace("–", "-").replace("—", "-")
        compact = re.sub(r"\.\d+$", "", compact)

        # Headers such as -5%, 0%, 5%.
        if compact.endswith("%"):
            try:
                if int(compact[:-1]) == target_number:
                    return col
            except ValueError:
                pass
            continue

        # Headers such as -0.05, 0.01, 0.05.
        try:
            value = float(compact)
            if abs(value) <= 1:
                pct = value * 100.0
                if abs(pct - target_number) < 1e-9:
                    return col
            if abs(value - target_number) < 1e-9:
                return col
        except ValueError:
            pass

    return None


def clean_number(value):

    if pd.isna(value):

        return np.nan

    if isinstance(value, (int, float, np.integer, np.floating)):

        return float(value)

    text = str(value).strip().replace(",", "")

    if not text:

        return np.nan

    text = re.sub(r"[^0-9.\-+eE]", "", text)

    try:

        return float(text)

    except Exception:

        return np.nan





def normalize_text(value):

    if pd.isna(value):

        return ""

    return str(value).strip()





def normalize_sku_value(value):

    return normalize_text(value)





def parse_month_value(value):
    """Normalize month labels while supporting both YYYY-MM and workbook labels such as 1-01."""
    if pd.isna(value):
        return None

    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "nat"}:
        return None

    # Important for the Ubuntu workbook: sheet names such as 1-01, 1-02,
    # 1-03 are valid month labels in this project.  pandas on Ubuntu can
    # return NaT for these labels, so handle them explicitly before calling
    # pd.to_datetime().
    legacy = re.fullmatch(r"(\d+)-(\d{1,2})", text)
    if legacy:
        year_part = int(legacy.group(1))
        month_part = int(legacy.group(2))
        if 1 <= month_part <= 12:
            return f"{year_part}-{month_part:02d}"

    dt = pd.to_datetime(text, errors="coerce")
    if pd.notna(dt):
        return dt.strftime("%Y-%m")

    return text


def month_parts(value):
    """Return (year, month) for supported month labels, otherwise (None, None)."""
    parsed = parse_month_value(value)
    if not parsed:
        return None, None

    match = re.fullmatch(r"(\d{4})-(\d{2})", parsed)
    if match:
        return int(match.group(1)), int(match.group(2))

    match = re.fullmatch(r"(\d+)-(\d{2})", parsed)
    if match:
        year_part = int(match.group(1))
        month_part = int(match.group(2))
        if 1 <= month_part <= 12:
            return year_part, month_part

    return None, None


def month_sort_value(value):
    """Sortable numeric key for YYYY-MM and labels such as 1-01."""
    year, month = month_parts(value)
    if year is None or month is None:
        return None
    return year * 12 + month


def continuous_months(month_values):
    """Return all months between the first and last supplied month label."""
    cleaned = []
    for value in month_values:
        parsed = parse_month_value(value)
        if parsed and parsed not in cleaned:
            cleaned.append(parsed)

    if not cleaned:
        return []

    # Normal four-digit calendar labels.
    iso = [x for x in cleaned if re.fullmatch(r"\d{4}-\d{2}", x)]
    if len(iso) >= 2:
        start = pd.Period(min(iso), freq="M")
        end = pd.Period(max(iso), freq="M")
        return [str(x) for x in pd.period_range(start, end, freq="M")]

    # Workbook labels such as 1-01, 1-02, ... . Treat the first number as
    # the year/series number and the second as the month number. This keeps
    # the original workbook naming while allowing missing months to be shown.
    legacy = []
    for x in cleaned:
        match = re.fullmatch(r"(\d+)-(\d{2})", x)
        if match and 1 <= int(match.group(2)) <= 12:
            legacy.append((int(match.group(1)), int(match.group(2))))

    if legacy and len(legacy) == len(cleaned):
        start = min(legacy)
        end = max(legacy)
        result = []
        y, m = start
        while (y, m) <= end:
            result.append(f"{y}-{m:02d}")
            m += 1
            if m > 12:
                y += 1
                m = 1
        return result

    return sorted(cleaned, key=lambda x: (month_sort_value(x) is None, month_sort_value(x) or 0, x))





def load_master_count():

    try:

        if not os.path.exists(MASTER_FILE):

            return 0

        df = pd.read_excel(MASTER_FILE)

        return int(len(df))

    except Exception:

        return 0





def prepare_supplied_dataframe(df, month_label):

    """Read the supplied report exactly as provided by Excel.



    The workbook is the source of truth. No bucket, adherence, total, spec,

    actual, difference or tolerance value is reconstructed.

    """

    # Keep the original Excel column objects. Do not convert headers globally,

    # because Excel percentage headers can be read by pandas in several forms.

    size_col = find_column(df, ["Size", "Tyre Size", "Tire Size"])

    spec_col = find_column(df, ["Spec (kg)", "Spec kg", "Spec"])

    actual_col = find_column(df, ["Actual (kg)", "Actual kg", "Actual"])

    total_col = find_column(df, ["Total tyres", "Total tyre", "Total tires", "Total tire"])

    adherence_col = find_column(df, ["% adher.", "% adherence", "Adherence %", "Adherence"])

    sku_col = find_column(df, ["SKU", "Tyre SKU", "Tire SKU", "Model", "Pattern"])

    month_col = find_column(df, ["Month", "Date", "Month Year", "Month-Year"])



    required = []

    if size_col is None: required.append("Size")
    if spec_col is None: required.append("Spec (kg)")
    if actual_col is None: required.append("Actual (kg)")

    # Total tyres and % adherence are optional for the running-weight report.
    if required:
        raise ValueError("Missing required supplied-data column(s): " + ", ".join(required))

    print("\n========================================")

    print("INPUT COLUMNS")

    print("========================================")

    for i, col in enumerate(df.columns):

        print(i, repr(col), "TYPE:", type(col).__name__)

    print("========================================\n")



    out = pd.DataFrame(index=df.index)

    out["size"] = df[size_col].map(normalize_text)

    out["sku"] = df[sku_col].map(normalize_sku_value) if sku_col is not None else out["size"]

    out["spec"] = df[spec_col].map(clean_number)

    out["actual"] = df[actual_col].map(clean_number)

    out["total_tyres"] = (
        df[total_col].map(clean_number) if total_col is not None else np.nan
    )

    out["adherence"] = (
        df[adherence_col].map(clean_number) if adherence_col is not None else np.nan
    )

    # The workbook is organized month-wise by sheet. Use the sheet name as the
    # authoritative month label (for example, sheet "1-01" -> month "1-01").
    # This prevents an empty/differently formatted Month column from removing
    # the month information on Ubuntu.
    out["month"] = parse_month_value(month_label)



    bucket_aliases = {

        "<-5%": ["<-5%", "< -5%", "< -5 %", "less than -5%", "less than -5"],

        "-5%": ["-5%", "-5 %", "-5"],

        "-4%": ["-4%", "-4 %", "-4"],

        "-3%": ["-3%", "-3 %", "-3"],

        "-2%": ["-2%", "-2 %", "-2"],

        "-1%": ["-1%", "-1 %", "-1"],

        "0%": ["0%", "0 %", "0"],

        "1%": ["1%", "1 %", "1"],

        "2%": ["2%", "2 %", "2"],

        "3%": ["3%", "3 %", "3"],

        "4%": ["4%", "4 %", "4"],

        "5%": ["5%", "5 %", "5"],

        ">5%": [">5%", "> 5%", "> 5 %", "greater than 5%", "greater than 5"],

    }



    # --------------------------------------------------------

    # First try the actual Excel header names.

    # --------------------------------------------------------

    bucket_columns = {}

    for bucket in BUCKETS:

        col = find_bucket_column(df, bucket)

        if col is None:

            col = find_column(df, bucket_aliases[bucket])

        bucket_columns[bucket] = col



    # Do NOT use positional bucket mapping. The uploaded workbook contains
    # meaningful numeric headers (-0.05 ... 0.05), and mapping by position can
    # silently assign the wrong bucket. Every bucket must be identified from
    # its actual Excel header.
    missing_buckets = [b for b in BUCKETS if bucket_columns[b] is None]
    if missing_buckets:
        raise ValueError(
            "Could not identify Excel bucket column(s): "
            + ", ".join(missing_buckets)
            + ". Expected headers such as <-5%, -0.05 ... 0.05, >5%."
        )

    for bucket in BUCKETS:

        col = bucket_columns[bucket]

        print(f"Bucket {bucket:>5} --> Excel column = {col!r}")

        out[bucket] = df[col].map(clean_number) if col is not None else np.nan



    # Optional tolerance columns: only read if supplied in Excel.

    minus2_col = find_column(df, ["-2% Limit", "Minus 2% Limit", "-2% limit (kg)", "-2% (kg)"])

    plus2_col = find_column(df, ["+2% Limit", "Plus 2% Limit", "+2% limit (kg)", "+2% (kg)"])

    out["minus_2_limit"] = df[minus2_col].map(clean_number) if minus2_col is not None else np.nan
    out["plus_2_limit"] = df[plus2_col].map(clean_number) if plus2_col is not None else np.nan

    out["minus_5_limit"] = np.where(
        out["spec"].notna(),
        out["spec"] * (1 + TOLERANCE_LOW_PERCENT / 100.0),
        np.nan,
    )
    out["plus_5_limit"] = np.where(
        out["spec"].notna(),
        out["spec"] * (1 + TOLERANCE_HIGH_PERCENT / 100.0),
        np.nan,
    )



    out = out[out["size"].ne("")].copy()

    out["source_row"] = np.arange(1, len(out) + 1)

    out["valid"] = (
        out["size"].astype(str).str.strip().ne("")
        & pd.to_numeric(out["spec"], errors="coerce").notna()
        & pd.to_numeric(out["actual"], errors="coerce").notna()
    )

    print("ROW VALIDATION:", {
        "rows_read": int(len(out)),
        "size_present": int(out["size"].astype(str).str.strip().ne("").sum()),
        "spec_numeric": int(pd.to_numeric(out["spec"], errors="coerce").notna().sum()),
        "actual_numeric": int(pd.to_numeric(out["actual"], errors="coerce").notna().sum()),
        "valid": int(out["valid"].sum()),
    })

    return out





def row_json(row):

    def num(v, digits=None):

        if pd.isna(v):

            return None

        x = float(v)

        return round(x, digits) if digits is not None else x



    result = {

        "size": row.get("size", ""),

        "sku": row.get("sku", ""),

        "month": row.get("month", ""),

        "spec": num(row.get("spec"), 3),

        "actual": num(row.get("actual"), 3),

        "total_tyres": num(row.get("total_tyres")),

        "adherence": num(row.get("adherence"), 2),

        "minus_2_limit": num(row.get("minus_2_limit"), 3),

        "plus_2_limit": num(row.get("plus_2_limit"), 3),

    }

    for bucket in BUCKETS:

        result[bucket] = num(row.get(bucket))

    return result





def build_size_summary(df):

    """Return supplied rows in SKU/month order; do not aggregate them."""

    work = df.copy()

    work["sku_sort"] = work["sku"].fillna("").astype(str).str.casefold()

    work["month_sort"] = work["month"].fillna("").astype(str)

    work["month_order"] = work["month_sort"].map(month_sort_value)

    work = work.sort_values(

        ["sku_sort", "month_order", "month_sort", "source_row"],

        kind="stable", na_position="last"

    )

    rows = []

    for i, (_, row) in enumerate(work.iterrows(), 1):

        result = row_json(row)

        result["s_no"] = i

        rows.append(result)

    return rows





def build_monthly_summary(df):

    """Return supplied month rows without calculating a monthly aggregate."""

    work = df.copy()

    work["month_sort"] = work["month"].fillna("").astype(str)

    work["sku_sort"] = work["sku"].fillna("").astype(str).str.casefold()

    work["month_order"] = work["month_sort"].map(month_sort_value)

    work = work.sort_values(["month_order", "month_sort", "sku_sort", "source_row"], kind="stable", na_position="last")

    return [

        {

            "month": str(row["month"]) if pd.notna(row["month"]) else "",

            "sku": str(row["sku"]),

            "total_tyres": float(row["total_tyres"]) if pd.notna(row["total_tyres"]) else None,

            "adherence": float(row["adherence"]) if pd.notna(row["adherence"]) else None,

        }

        for _, row in work.iterrows()

        if pd.notna(row["month"]) and str(row["month"]).strip()

    ]





def build_sku_month_summary(df):

    """Arrange supplied rows by SKU and month.



    Spec and Actual remain supplied values from Excel. The +/-2% control-limit

    lines are derived from the supplied Spec only. If the same SKU occurs more

    than once in a month, the first source row is used for the monthly graph

    and table, and the duplicate is reported in metadata rather than being

    mathematically combined.

    """

    if df.empty:

        return [], []



    work = df.copy()

    work["sku_sort"] = work["sku"].fillna("").astype(str).str.casefold()

    work["month_sort"] = work["month"].fillna("").astype(str)

    work["month_order"] = work["month_sort"].map(month_sort_value)

    work = work.sort_values(

        ["sku_sort", "month_order", "month_sort", "source_row"],

        kind="stable",

        na_position="last",

    )



    rows = []

    duplicates = []

    for (sku, month), group in work.groupby(["sku", "month"], sort=False, dropna=False):

        if not sku or not month:

            continue

        first = group.iloc[0]

        row = {

            "sku": str(sku),

            "month": str(month),

            # These values come directly from the selected source row.

            "spec": float(first["spec"]) if pd.notna(first["spec"]) else None,

            "average_running_weight": float(first["actual"]) if pd.notna(first["actual"]) else None,

            "actual": float(first["actual"]) if pd.notna(first["actual"]) else None,

            # Control limits are derived only from supplied Spec.
            # Default range is -5% to +5%.
            "minus_5_percent": (
                float(first["spec"]) * (1 + TOLERANCE_LOW_PERCENT / 100.0)
                if pd.notna(first["spec"]) else None
            ),
            "plus_5_percent": (
                float(first["spec"]) * (1 + TOLERANCE_HIGH_PERCENT / 100.0)
                if pd.notna(first["spec"]) else None
            ),
            # Legacy aliases retained for compatibility with older HTML.
            "minus_2_percent": (
                float(first["spec"]) * (1 + TOLERANCE_LOW_PERCENT / 100.0)
                if pd.notna(first["spec"]) else None
            ),
            "plus_2_percent": (
                float(first["spec"]) * (1 + TOLERANCE_HIGH_PERCENT / 100.0)
                if pd.notna(first["spec"]) else None
            ),

            "total_tyres": float(first["total_tyres"]) if pd.notna(first["total_tyres"]) else None,

            "adherence": float(first["adherence"]) if pd.notna(first["adherence"]) else None,

            "source_row": int(first["source_row"]),

        }

        for bucket in BUCKETS:

            row[bucket] = float(first[bucket]) if pd.notna(first[bucket]) else None

        rows.append(row)



        if len(group) > 1:

            duplicates.append({

                "sku": str(sku),

                "month": str(month),

                "rows": int(len(group)),

                "source_rows": [int(x) for x in group["source_row"].tolist()],

            })



    return rows, duplicates







def build_monthly_average_chart(df):
    """Average supplied Actual (kg) by month, including workbook labels such as 1-01."""
    if df.empty:
        return []

    work = df.copy()
    work["actual_num"] = pd.to_numeric(work["actual"], errors="coerce")
    work["month_order"] = work["month"].map(month_sort_value)
    work = work.dropna(subset=["actual_num", "month_order"])
    if work.empty:
        return []

    grouped = (
        work.groupby(["month", "month_order"], as_index=False)["actual_num"]
        .mean()
        .sort_values("month_order")
    )

    return [
        {
            "month": str(month),
            "average_running_weight": float(value),
        }
        for month, value in zip(grouped["month"], grouped["actual_num"])
    ]


def build_yearly_average_chart(df):
    """Average supplied Actual (kg) by year/series for both YYYY-MM and 1-01 style labels."""
    if df.empty:
        return []

    work = df.copy()
    work["actual_num"] = pd.to_numeric(work["actual"], errors="coerce")
    work["year"] = work["month"].map(lambda x: month_parts(x)[0])
    work = work.dropna(subset=["actual_num", "year"])
    if work.empty:
        return []

    grouped = (
        work.groupby("year", as_index=False)["actual_num"]
        .mean()
        .sort_values("year")
    )

    return [
        {
            "year": int(year),
            "average_running_weight": float(value),
        }
        for year, value in zip(grouped["year"], grouped["actual_num"])
    ]


def create_download_workbook(data):
    """Create the detailed Excel export from the processed dashboard payload."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    wb = Workbook()
    ws = wb.active
    ws.title = "Detailed Results"

    details = data.get("details", [])
    columns = [
        ("S.No", "s_no"),
        ("SKU", "sku"),
        ("Size", "size"),
        ("Month", "month"),
        ("Spec (kg)", "spec"),
        ("Actual (kg)", "actual"),
        ("-5% Limit (kg)", "minus_5_limit"),
        ("+5% Limit (kg)", "plus_5_limit"),
        ("Total tyres", "total_tyres"),
        ("% adher.", "adherence"),
    ] + [(b, b) for b in BUCKETS]

    headers = [x[0] for x in columns]
    ws.append(headers)

    for i, row in enumerate(details, 1):
        ws.append([i if key == "s_no" else row.get(key) for _, key in columns])

    header_fill = PatternFill("solid", fgColor="1F2937")
    for cell in ws[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    for column in ws.columns:
        letter = column[0].column_letter
        ws.column_dimensions[letter].width = min(
            max(len(str(c.value or "")) for c in column) + 2, 28
        )

    def add_sheet(name, headers, rows):
        sh = wb.create_sheet(name)
        sh.append(headers)
        for row in rows:
            sh.append(row)
        for cell in sh[1]:
            cell.font = Font(color="FFFFFF", bold=True)
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")
        sh.freeze_panes = "A2"
        for column in sh.columns:
            letter = column[0].column_letter
            sh.column_dimensions[letter].width = min(
                max(len(str(c.value or "")) for c in column) + 2, 28
            )
        return sh

    monthly = data.get("monthly_average_chart", [])
    add_sheet(
        "Monthly Average",
        ["Month", "Average Running Weight (kg)"],
        [[r.get("month"), r.get("average_running_weight")] for r in monthly],
    )

    yearly = data.get("yearly_average_chart", [])
    add_sheet(
        "Yearly Average",
        ["Year", "Average Running Weight (kg)"],
        [[r.get("year"), r.get("average_running_weight")] for r in yearly],
    )

    sku_rows = data.get("sku_running_weight_chart", [])
    add_sheet(
        "SKU Monthly Analysis",
        [
            "SKU",
            "Month",
            "Spec (kg)",
            "Average Running Weight (kg)",
            "-5% Limit (kg)",
            "+5% Limit (kg)",
            "Total tyres",
        ],
        [
            [
                r.get("sku"),
                r.get("month"),
                r.get("spec"),
                r.get("average_running_weight"),
                r.get("minus_5_percent"),
                r.get("plus_5_percent"),
                r.get("total_tyres"),
            ]
            for r in sku_rows
        ],
    )

    bucket_totals = data.get("bucket_totals", {})
    add_sheet(
        "Bucket Summary",
        ["Bucket", "Total"],
        [[b, bucket_totals.get(b)] for b in BUCKETS],
    )

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output


def _safe_filename(name):
    base = os.path.splitext(os.path.basename(name or "analysis"))[0]
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("_")
    return base or "analysis"


def _report_image_from_chart(title, labels, values, spec=None, low=None, high=None):
    fig, ax = plt.subplots(figsize=(11, 4.8))
    x = range(len(labels))
    ax.plot(x, values, marker="o", linewidth=2, label="Average Running Weight")
    if spec is not None:
        ax.plot(x, spec, linestyle="--", linewidth=1.8, label="Spec")
    if low is not None:
        ax.plot(x, low, linestyle=":", linewidth=1.6, label=f"{TOLERANCE_LOW_PERCENT}% Limit")
    if high is not None:
        ax.plot(x, high, linestyle=":", linewidth=1.6, label=f"+{TOLERANCE_HIGH_PERCENT}% Limit")
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_ylabel("Weight (kg)")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def create_pdf_report(data):
    """Create a professional PDF report containing graphs and written analysis."""
    filename = data.get("filename", "Analysis.xlsx")
    base = _safe_filename(filename)

    pdf = io.BytesIO()
    doc = SimpleDocTemplate(
        pdf,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="JK Tyre SKU Monthly Running Weight Analysis Report",
        author="JK Tyre R&D",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontSize=20,
        leading=24,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#111827"),
        spaceAfter=8,
    )
    subtitle_style = ParagraphStyle(
        "Subtitle",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#64748B"),
        spaceAfter=16,
    )
    heading_style = ParagraphStyle(
        "Heading",
        parent=styles["Heading2"],
        fontSize=14,
        leading=18,
        textColor=colors.HexColor("#B91C1C"),
        spaceBefore=10,
        spaceAfter=7,
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontSize=9.5,
        leading=14,
        textColor=colors.HexColor("#334155"),
        spaceAfter=7,
    )

    story = [
        Paragraph("JK TYRE", title_style),
        Paragraph("SKU Monthly Running Weight Analysis Report", subtitle_style),
        Paragraph(
            f"Generated on {datetime.now().strftime('%d %B %Y, %I:%M %p')}",
            subtitle_style,
        ),
    ]

    details = data.get("details", [])
    sku_rows = data.get("sku_running_weight_chart", [])
    monthly = data.get("monthly_average_chart", [])
    yearly = data.get("yearly_average_chart", [])
    kpis = data.get("kpis", {})

    story.append(Paragraph("1. Executive Summary", heading_style))
    story.append(
        Paragraph(
            "This report presents the monthly running-weight performance from the "
            "uploaded JK Tyre inspection workbook. The supplied Spec and Actual "
            "values are used as the source data. The running-weight control band "
            f"is set from {TOLERANCE_LOW_PERCENT}% to +{TOLERANCE_HIGH_PERCENT}% "
            "of the supplied Spec. No supplied bucket or adherence value is "
            "recalculated.",
            body_style,
        )
    )

    kpi_data = [
        ["Metric", "Value"],
        ["Processed records", str(len(details))],
        ["SKUs", str(len(data.get("sku_values", [])))],
        ["Months", str(len(data.get("month_values", [])))],
        [
            "Total tyres",
            f"{kpis.get('total_tyres'):,.0f}" if kpis.get("total_tyres") is not None else "N/A",
        ],
        [
            "Adherent tyres",
            f"{kpis.get('adherent_tyres'):,.0f}" if kpis.get("adherent_tyres") is not None else "N/A",
        ],
    ]
    table = Table(kpi_data, colWidths=[80 * mm, 70 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F8FAFC")),
                ("PADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)

    # Month-wise graph
    if monthly:
        labels = [r["month"] for r in monthly]
        vals = [r["average_running_weight"] for r in monthly]
        img = _report_image_from_chart(
            "Month-wise Average Running Weight",
            labels,
            vals,
        )
        story.append(Paragraph("2. Month-wise Average Running Weight", heading_style))
        story.append(Image(img, width=175 * mm, height=76 * mm))
        story.append(
            Paragraph(
                "The graph shows the mean of the supplied Actual (kg) values for "
                "each month. It is a descriptive aggregation of the uploaded "
                "Actual values and does not recalculate the inspection buckets.",
                body_style,
            )
        )

    # Year-wise graph
    if yearly:
        labels = [str(r["year"]) for r in yearly]
        vals = [r["average_running_weight"] for r in yearly]
        img = _report_image_from_chart(
            "Year-wise Average Running Weight",
            labels,
            vals,
        )
        story.append(Paragraph("3. Year-wise Average Running Weight", heading_style))
        story.append(Image(img, width=175 * mm, height=76 * mm))
        story.append(
            Paragraph(
                "The yearly graph summarizes the supplied Actual (kg) values by "
                "calendar year and is intended to show the longer-term running "
                "weight trend.",
                body_style,
            )
        )

    # Overall SKU chart
    if sku_rows:
        # Only include the first/selected SKU if the frontend sent one.
        selected_sku = data.get("selected_sku")
        filtered = [
            r for r in sku_rows
            if not selected_sku or str(r.get("sku")) == str(selected_sku)
        ]
        if filtered:
            labels = [r["month"] for r in filtered]
            vals = [r["average_running_weight"] for r in filtered]
            specs = [r["spec"] for r in filtered]
            lows = [r["minus_5_percent"] for r in filtered]
            highs = [r["plus_5_percent"] for r in filtered]
            title = (
                f"SKU Monthly Running Weight — {selected_sku}"
                if selected_sku
                else "SKU Monthly Running Weight Analysis"
            )
            img = _report_image_from_chart(
                title, labels, vals, specs, lows, highs
            )
            story.append(Paragraph("4. SKU Monthly Running Weight", heading_style))
            story.append(Image(img, width=175 * mm, height=76 * mm))

    story.append(Paragraph("5. Interpretation and Control Range", heading_style))
    story.append(
        Paragraph(
            f"The control range used in this report is {TOLERANCE_LOW_PERCENT}% "
            f"to +{TOLERANCE_HIGH_PERCENT}% around the supplied Spec. For a Spec "
            f"value S, the lower control limit is S × {1 + TOLERANCE_LOW_PERCENT / 100:.2f} "
            f"and the upper control limit is S × {1 + TOLERANCE_HIGH_PERCENT / 100:.2f}. "
            "These limits are analytical reference lines for the running-weight "
            "graphs; they do not replace or alter the supplied Excel bucket values.",
            body_style,
        )
    )

    if details:
        below = 0
        above = 0
        inside = 0
        for r in details:
            actual = r.get("actual")
            spec = r.get("spec")
            if actual is None or spec is None:
                continue
            low = spec * (1 + TOLERANCE_LOW_PERCENT / 100)
            high = spec * (1 + TOLERANCE_HIGH_PERCENT / 100)
            if actual < low:
                below += 1
            elif actual > high:
                above += 1
            else:
                inside += 1
        story.append(
            Paragraph(
                f"Based on the supplied Spec and Actual values, {inside} records "
                f"fall inside the ±5% control band, {below} fall below the lower "
                f"limit, and {above} exceed the upper limit. This classification "
                "is used only for this report's analytical interpretation.",
                body_style,
            )
        )

    story.append(Paragraph("6. Methodology", heading_style))
    story.append(
        Paragraph(
            "The uploaded workbook remains the source of truth for supplied "
            "Size, Spec, Actual, Total tyres, adherence and bucket values. "
            "Monthly and yearly average running weight graphs are calculated "
            "only as descriptive means of supplied Actual values. The PDF "
            "contains the graphical representation and written interpretation "
            "so it can be saved and shared as a formal analysis report.",
            body_style,
        )
    )

    doc.build(story)
    pdf.seek(0)
    return pdf, f"{base}_Analysis_Report.pdf"


@app.route("/download", methods=["POST"])
def download_excel():
    try:
        data = request.get_json(force=True) or {}
        output = create_download_workbook(data)
        filename = _safe_filename(data.get("filename", "Analysis.xlsx"))
        return send_file(
            output,
            as_attachment=True,
            download_name=f"{filename}_Analysis.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/download_report", methods=["POST"])
def download_report():
    try:
        data = request.get_json(force=True) or {}
        output, filename = create_pdf_report(data)
        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype="application/pdf",
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500

@app.route("/")

def index():

    return render_template("dashboard.html")





@app.route("/upload", methods=["POST"])

@app.route("/analyze", methods=["POST"])

def analyze():

    if "file" not in request.files:

        return jsonify({"success": False, "error": "No file uploaded."}), 400



    file = request.files["file"]

    if not file.filename:

        return jsonify({"success": False, "error": "Please select a file."}), 400

    if not allowed_file(file.filename):

        return jsonify({"success": False, "error": "Only XLSX, XLS or CSV files are supported."}), 400



    try:

        if file.filename.lower().endswith(".csv"):

            sheets = {"Data": pd.read_csv(file)}

        else:

            sheets = pd.read_excel(file, sheet_name=None)



        parts = []

        invalid = []

        sheet_stats = []

        for sheet_name, raw in sheets.items():

            try:

                prepared = prepare_supplied_dataframe(raw, sheet_name)

                parts.append(prepared)

                sheet_stats.append({"month": str(sheet_name), "rows": int(len(raw)), "valid": int(prepared["valid"].sum()), "invalid": int(len(prepared) - prepared["valid"].sum())})

            except Exception as exc:

                invalid.append({"month": str(sheet_name), "row": "all", "size": "", "reason": str(exc)})



        if not parts:

            return jsonify({
                "success": False,
                "error": "No readable report sheets were found.",
                "invalid": invalid,
                "sheet_statistics": sheet_stats,
            }), 400



        data = pd.concat(parts, ignore_index=True)

        valid = data[data["valid"]].copy()

        print("\n========== MONTH/SKU DEBUG ==========")
        print("MONTH VALUES:", valid["month"].dropna().unique().tolist())
        print("SKU VALUES:", valid["sku"].dropna().unique().tolist())
        print("VALID ROWS:", len(valid))
        print("=====================================\n")

        if valid.empty:
            diagnostics = []
            for sheet_name, raw in sheets.items():
                try:
                    size_col = find_column(raw, ["Size", "Tyre Size", "Tire Size"])
                    spec_col = find_column(raw, ["Spec (kg)", "Spec kg", "Spec"])
                    actual_col = find_column(raw, ["Actual (kg)", "Actual kg", "Actual"])
                    diagnostics.append({
                        "sheet": str(sheet_name),
                        "rows": int(len(raw)),
                        "size_column": str(size_col),
                        "spec_column": str(spec_col),
                        "actual_column": str(actual_col),
                    })
                except Exception as exc:
                    diagnostics.append({"sheet": str(sheet_name), "error": str(exc)})

            return jsonify({
                "success": False,
                "error": "No valid rows found after reading Size, Spec (kg), and Actual (kg). Check the ROW VALIDATION lines in the terminal.",
                "sheet_statistics": sheet_stats,
                "diagnostics": diagnostics,
            }), 400



        size_summary = build_size_summary(valid)

        monthly_summary = build_monthly_summary(valid)

        sku_month_summary, duplicate_sku_month_rows = build_sku_month_summary(valid)

        print("SKU MONTH SUMMARY ROWS:", len(sku_month_summary))
        print("SKU MONTH SAMPLE:", sku_month_summary[:10])

        # Dedicated SKU Monthly Running Weight graph payload.

        # Each point uses the supplied Spec and Actual. The +/-2% lines are

        # fixed limits derived from that supplied Spec for each month.

        sku_running_weight_chart = []

        for r in sku_month_summary:

            sku_running_weight_chart.append({

                "sku": r["sku"],

                "month": r["month"],

                "spec": r["spec"],

                "average_running_weight": r["average_running_weight"],

                "minus_2_percent": r["minus_2_percent"],

                "plus_2_percent": r["plus_2_percent"],

                "total_tyres": r["total_tyres"],

            })



        # The uploaded workbook remains the source of truth for supplied

        # Spec/Actual/bucket/Total tyres/% adherence fields. The only derived

        # values here are the requested +/-2% graph control limits.

        # For the distribution chart, supplied bucket counts are summed across

        # rows only to place all mixed-SKU rows into one dashboard chart. No

        # bucket or adherence value is reconstructed from Spec/Actual.

        # KPI values are taken from the supplied report fields.

        # Summing supplied row values is only an aggregation for the dashboard;

        # nothing is reconstructed from Spec/Actual.

        total_series = pd.to_numeric(valid["total_tyres"], errors="coerce").dropna()

        total_tyres = float(total_series.sum()) if not total_series.empty else None



        bucket_totals = {}

        for bucket in BUCKETS:

            vals = pd.to_numeric(valid[bucket], errors="coerce").dropna()

            bucket_totals[bucket] = float(vals.sum()) if not vals.empty else None



        # The report supplies % adherence per row, not necessarily one overall

        # percentage. Do not invent a weighted/average overall percentage.

        # If the workbook contains exactly one supplied adherence value, it is

        # safe to display that value directly. Otherwise the UI reports that

        # multiple supplied values exist.

        adherence_values = pd.to_numeric(valid["adherence"], errors="coerce").dropna().tolist()

        unique_adherence = []

        for value in adherence_values:

            if not any(abs(float(value) - x) < 1e-12 for x in unique_adherence):

                unique_adherence.append(float(value))

        overall_adherence = unique_adherence[0] if len(unique_adherence) == 1 else None



        # Adherent tyres are represented by the supplied -5% through +5%

        # bucket counts. This is an aggregation of supplied counts, not a

        # recalculation from Spec and Actual.

        adherence_bucket_values = [bucket_totals[b] for b in BUCKETS[1:-1] if bucket_totals[b] is not None]

        adherent_tyres = float(sum(adherence_bucket_values)) if adherence_bucket_values else None



        # Monthly chart uses every supplied % adher. value as-is. When several

        # SKUs occur in the same month, their supplied values remain separate

        # points; nothing is averaged or recalculated.

        monthly_chart = []

        chart_work = valid.copy()

        chart_work["month_order"] = chart_work["month"].map(month_sort_value)

        chart_work = chart_work.sort_values(["month_order", "month", "sku", "source_row"], kind="stable", na_position="last")

        for _, r in chart_work.iterrows():

            if pd.notna(r["adherence"]):

                monthly_chart.append({

                    "month": str(r["month"]),

                    "sku": str(r["sku"]),

                    "adherence": float(r["adherence"]),

                    "source_row": int(r["source_row"]),

                })



        graph = []

        for _, r in valid.iterrows():

            graph.append({

                "label": r["size"],

                "size": r["size"],

                "spec": float(r["spec"]) if pd.notna(r["spec"]) else None,

                "actual": float(r["actual"]) if pd.notna(r["actual"]) else None,

                "adherence": float(r["adherence"]) if pd.notna(r["adherence"]) else None,

            })



        details = [row_json(r) for _, r in valid.iterrows()]

        months = [str(x) for x in valid["month"].dropna().tolist()]

        # Unique SKU list is collected across ALL uploaded sheets, then sorted.

        skus = sorted({str(x) for x in valid["sku"].dropna().tolist() if str(x).strip()}, key=str.casefold)

        # Arrange the detailed records by SKU first and month second.

        details = sorted(details, key=lambda r: (str(r.get("sku", "")).casefold(), str(r.get("month", "")), str(r.get("size", "")).casefold()))

        monthly_average_chart = build_monthly_average_chart(valid)
        yearly_average_chart = build_yearly_average_chart(valid)



        return jsonify({

            "success": True,

            "message": "Excel processed. Supplied report values were used without recalculating the bucket/adherence fields.",

            "filename": file.filename,

            "kpis": {

                "total_tyres": total_tyres,

                "adherent_tyres": adherent_tyres,

                "non_adherent_tyres": (total_tyres - adherent_tyres) if total_tyres is not None and adherent_tyres is not None else None,

                "adherence": overall_adherence,

            },

            "summary": size_summary,

            "size_summary": size_summary,

            "monthly": monthly_summary,

            "monthly_summary": monthly_summary,

            "sku_month_summary": sku_month_summary,

            "sku_running_weight_chart": sku_running_weight_chart,

            "sku_values": skus,

            "month_values": list(dict.fromkeys(months)),

            "continuous_months": continuous_months(months),

            "graph": graph,

            "bucket_totals": bucket_totals,

            "monthly_chart": monthly_chart,

            "details": details,

            "invalid": invalid,

            "meta": {

                "master_count": load_master_count(),

                "sheet_count": len(sheets),

                "sheets": [str(x) for x in sheets.keys()],

                "bucket_order": BUCKETS,

                "source_of_truth": "uploaded Excel supplied values",

                "calculation_mode": "no reconstruction of supplied report metrics",
                "control_range_percent": {"low": TOLERANCE_LOW_PERCENT, "high": TOLERANCE_HIGH_PERCENT},

                "sheet_statistics": sheet_stats,

                "duplicate_sku_month_rows": duplicate_sku_month_rows,

                "pagination": {

                    "default_page_size": 20,

                    "page_size_options": [10, 20, 50, 100],

                    "mode": "client-side table pagination",

                },

            }

        })

    except Exception as exc:

        return jsonify({"success": False, "error": str(exc)}), 500





if __name__ == "__main__":

    app.run(debug=True, host="127.0.0.1", port=5000)
