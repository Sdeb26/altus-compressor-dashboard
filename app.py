"""
Altus Compressor Validation Tool — Python/Streamlit dashboard.
Replicates Altus_Compressor_Validation_Tool__v3.xlsx (Dashboard tab) using the
same tags, formulas, and tolerances, covering the full fleet of Compressors
C1-C14, running against the full-resolution Sigma historian export instead of
a downsampled, pre-recalculated workbook.
"""
import datetime as dt

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from calc_engine import METRICS, METRIC_BY_KEY, load_equipment_config, compute_compressor, apply_flags
from data_prep import build_raw_csv

st.set_page_config(page_title="Altus Compressor Validation Tool", layout="wide")

OBSERVED_INTERVAL_SEC = 101  # Input_Config!$B$18 — median gap in the source export


# ---------------------------------------------------------------------------
# Cached data loading / calc
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _load_raw():
    df = pd.read_csv("raw_data.csv.gz", compression="gzip")
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


@st.cache_data(show_spinner=False)
def _load_cfg():
    return load_equipment_config()


@st.cache_data(show_spinner=False)
def _compute(comp: int, tol_overrides_key: tuple):
    raw = _load_raw()
    cfg = _load_cfg()
    calc = compute_compressor(raw, comp, cfg)
    tol_overrides = dict(tol_overrides_key) if tol_overrides_key else {}
    calc = apply_flags(calc, tol_overrides)
    return calc


def fmt_pct(x):
    return f"{x * 100:.1f}%"


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("Altus Compressor Validation Tool")
st.caption("Bar-S Foods — Altus, OK  |  Ammonia Refrigeration Compressor Fleet (C1-C14)  |  Python/Streamlit version")

# ---------------------------------------------------------------------------
# Upload a new weekly historian export — replaces raw_data.csv.gz for everyone
# viewing this dashboard (there's no per-person data; it's one shared app).
# ---------------------------------------------------------------------------
with st.expander("🔄 Upload a new weekly historian export"):
    st.caption(
        "Upload the raw Sigma compressor export (.xlsx). This reprocesses it and "
        "replaces the data behind the dashboard for **everyone currently viewing "
        "it** — there's no per-person copy and no undo, so double-check the file "
        "before confirming. Equipment nameplate data (equipment_config.csv) is "
        "unaffected; only the historian readings refresh."
    )
    uploaded = st.file_uploader("Historian export (.xlsx)", type=["xlsx"], key="historian_upload")
    if uploaded is not None:
        st.write(f"Selected: **{uploaded.name}** ({uploaded.size / 1e6:.1f} MB)")
        confirm = st.checkbox("I've checked this is the correct file — replace the dashboard's data with it.")
        if confirm and st.button("Process and refresh data", type="primary"):
            try:
                with st.spinner("Processing upload…"):
                    new_df = build_raw_csv(uploaded, out_path="raw_data.csv.gz")
                st.cache_data.clear()
                st.success(
                    f"Data refreshed: {new_df.shape[0]:,} rows, {new_df.shape[1]} columns, "
                    f"{new_df['timestamp'].min()} to {new_df['timestamp'].max()}."
                )
                st.rerun()
            except Exception as e:
                st.error(
                    f"Could not process this file — it doesn't look like a Sigma historian "
                    f"export (expected a sheet named 'in' with comp{{n}}/ref_comp_c{{n}}_{{tag}} "
                    f"columns). Details: {e}"
                )

raw = _load_raw()
cfg = _load_cfg()
data_min, data_max = raw["timestamp"].min(), raw["timestamp"].max()

# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------
c1, c2 = st.columns(2)
with c1:
    comp = st.selectbox("Select Compressor", options=list(range(1, 15)), index=2, format_func=lambda x: f"Compressor {x}")
with c2:
    metric_labels = [m[1] for m in METRICS]
    metric_label = st.selectbox("Select Metric", options=metric_labels, index=2)
metric_key, _, ttype, unit, tol1_def, tol2_def, const_exp, denom = next(m for m in METRICS if m[1] == metric_label)

c3, c4 = st.columns(2)
with c3:
    period_start = st.datetime_input("Validation Period Start", value=data_min) if hasattr(st, "datetime_input") else st.text_input(
        "Validation Period Start (YYYY-MM-DD HH:MM)", value=str(data_min))
with c4:
    period_end = st.datetime_input("Validation Period End", value=data_max) if hasattr(st, "datetime_input") else st.text_input(
        "Validation Period End (YYYY-MM-DD HH:MM)", value=str(data_max))

if not isinstance(period_start, (dt.datetime, pd.Timestamp)):
    period_start = pd.to_datetime(period_start)
if not isinstance(period_end, (dt.datetime, pd.Timestamp)):
    period_end = pd.to_datetime(period_end)
period_start, period_end = pd.Timestamp(period_start), pd.Timestamp(period_end)

tol_applicable = ttype in ("PercentDeviation", "CeilingPercent")
c5, c6 = st.columns(2)
with c5:
    tol1_override = st.number_input(
        f"Tolerance 1 Override % (blank/0 = default {tol1_def*100:.0f}%)",
        min_value=0.0, max_value=100.0, value=0.0, step=1.0, disabled=not tol_applicable,
    )
with c6:
    tol2_override = st.number_input(
        f"Tolerance 2 Override % (blank/0 = default {tol2_def*100:.0f}%)",
        min_value=0.0, max_value=100.0, value=0.0, step=1.0, disabled=not tol_applicable,
    )

tol_overrides = {}
if tol_applicable:
    t1 = tol1_override / 100 if tol1_override > 0 else tol1_def
    t2 = tol2_override / 100 if tol2_override > 0 else tol2_def
    tol_overrides[metric_key] = (t1, t2)
tol1_eff, tol2_eff = tol_overrides.get(metric_key, (tol1_def, tol2_def))

# Cache key must be hashable
tol_key = tuple(sorted(tol_overrides.items())) if tol_overrides else None
calc = _compute(comp, tol_key)

# ---------------------------------------------------------------------------
# Period filter + summary stats (mirrors Dashboard rows 23-45)
# ---------------------------------------------------------------------------
mask = (calc["timestamp"] >= period_start) & (calc["timestamp"] <= period_end)
period = calc.loc[mask]

live_col, exp_col, flag_col = f"{metric_key}_live", f"{metric_key}_expected", f"{metric_key}_flag"

total_in_period = len(period)
count_normal = (period[flag_col] == "Normal").sum()
count_warning = (period[flag_col] == "Warning").sum()
count_invalid = (period[flag_col] == "Invalid").sum()
count_na = (period[flag_col] == "N/A").sum()

denom_count = total_in_period - count_na
valid_pct_t1 = count_normal / denom_count if denom_count else 0.0
valid_pct_t2 = (count_normal + count_warning) / denom_count if denom_count else 0.0

actual_samples = period[live_col].notna().sum()
elapsed_sec = (period_end - period_start).total_seconds()
expected_samples = elapsed_sec / OBSERVED_INTERVAL_SEC + 1 if elapsed_sec > 0 else 0
missing_pct = max(0.0, (expected_samples - actual_samples)) / expected_samples if expected_samples else 0.0

valid_pairs = period[[live_col, exp_col]].dropna()
avg_dev = (valid_pairs[exp_col] - valid_pairs[live_col]).mean() if len(valid_pairs) else 0.0
if pd.isna(avg_dev):
    avg_dev = 0.0

if ttype == "RangeCheck":
    suggestion = (
        "All readings within physical range - no action needed."
        if valid_pct_t1 >= 0.99 else
        "Out-of-range readings detected - verify sensor/transmitter wiring and scaling."
    )
elif missing_pct > 0.2:
    suggestion = "Significant logging gaps (over 20% missing) in this period - verify historian communication before trusting the result below."
elif valid_pct_t1 >= 0.9:
    suggestion = "Data validates well within tight tolerance - no action needed."
elif valid_pct_t2 >= 0.9:
    suggestion = "Mostly within acceptable range but frequently outside the tight tolerance - review sensor calibration or the formula fit."
elif abs(avg_dev) > 0:
    direction = "higher than" if avg_dev > 0 else "lower than"
    suggestion = f"Calculated value consistently runs {direction} the live reading - verify the formula/coefficient table assigned to this equipment, or confirm whether the controller uses its own internal calculation."
else:
    suggestion = "Data falls outside tolerance without a clear consistent pattern - verify sensor/input readings and instrumentation."

# ---------------------------------------------------------------------------
# Summary tiles
# ---------------------------------------------------------------------------
st.subheader("Data Validation Summary")
t1, t2, t3, t4 = st.columns(4)
t1.metric("Valid % — Tolerance 1 (tight)", fmt_pct(valid_pct_t1))
t2.metric("Valid % — Tolerance 2 (incl. warning)", fmt_pct(valid_pct_t2))
t3.metric("Missing Data %", fmt_pct(missing_pct))
t4.metric("Readings in period", f"{total_in_period:,}")
st.info(f"**Suggestion:** {suggestion}")
st.caption(
    f"Period: {period_start:%m/%d/%Y %H:%M} – {period_end:%m/%d/%Y %H:%M}  |  "
    f"Normal: {count_normal:,}  Warning: {count_warning:,}  Invalid: {count_invalid:,}  N/A: {count_na:,}"
)
st.markdown("Legend: :green[**Green**] = healthy / within tolerance &nbsp;&nbsp; :orange[**Amber**] = borderline, review &nbsp;&nbsp; :red[**Red**] = action needed")

# ---------------------------------------------------------------------------
# Chart — hourly-average Live vs Expected, same logic as Chart_Data
# ---------------------------------------------------------------------------
st.subheader(f"Live vs. Expected — Hourly Average ({unit})")

chart_df = period.set_index("timestamp")[[live_col, exp_col]].resample("1h").mean().reset_index()
chart_df.columns = ["hour", "live", "expected"]

fig = go.Figure()
if const_exp:
    # Bar for live + dashed reference line + shaded Normal/Warning zones (matches
    # the v3 "constant reference line" chart mode for Discharge Pressure / Motor kW)
    ref = chart_df["expected"].dropna().iloc[0] if chart_df["expected"].notna().any() else None
    fig.add_trace(go.Bar(x=chart_df["hour"], y=chart_df["live"], name="Live", marker_color="#4C78A8"))
    if ref is not None:
        if ttype == "CeilingPercent":
            normal_lo, warn_lo = ref * (1 - tol1_eff), ref * (1 - tol2_eff)
            fig.add_hrect(y0=0, y1=warn_lo, fillcolor="red", opacity=0.08, line_width=0)
            fig.add_hrect(y0=warn_lo, y1=normal_lo, fillcolor="orange", opacity=0.08, line_width=0)
            fig.add_hrect(y0=normal_lo, y1=ref * 1.1, fillcolor="green", opacity=0.08, line_width=0)
        else:
            lo2, lo1, hi1, hi2 = ref * (1 - tol2_eff), ref * (1 - tol1_eff), ref * (1 + tol1_eff), ref * (1 + tol2_eff)
            fig.add_hrect(y0=lo1, y1=hi1, fillcolor="green", opacity=0.08, line_width=0)
            fig.add_hrect(y0=lo2, y1=lo1, fillcolor="orange", opacity=0.08, line_width=0)
            fig.add_hrect(y0=hi1, y1=hi2, fillcolor="orange", opacity=0.08, line_width=0)
        fig.add_hline(y=ref, line_dash="dash", line_color="gray", annotation_text="Expected (design)")
else:
    fig.add_trace(go.Bar(x=chart_df["hour"], y=chart_df["live"], name="Live", marker_color="#4C78A8"))
    if ttype != "RangeCheck":
        fig.add_trace(go.Bar(x=chart_df["hour"], y=chart_df["expected"], name="Expected", marker_color="#F58518"))

fig.update_layout(barmode="group", height=420, xaxis_title="Time", yaxis_title=unit, legend=dict(orientation="h"))
st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Footer / notes
# ---------------------------------------------------------------------------
with st.expander("Formula / source notes for this metric"):
    notes = {
        "suct_press": "Live suct_press compared to the compressor's own live suct_press_sp (control setpoint tag). No nameplate data required.",
        "disc_temp": "Isentropic compression-ratio ceiling: T2=(T1_K)×((P2+14.696)/(P1+14.696))^(0.3/1.3); k=1.3 for NH3. One-sided: live should stay below this ideal. 10°F Warning threshold is a working estimate calibrated on one day of Comp5 data — flagged as not yet fully validated.",
        "tr_fl": "SOO PDF Sec 3.4/3.5 polynomial, coefficients from Equipment_Config (correct Table 1-5 per compressor). SCT input uses live Discharge Temp in place of a derived-from-pressure estimate (validated within ~1-2% on Comp1). Flag divides by the LIVE reading (shows N/A when the compressor is idle, live=0) — this matches the original workbook's own logic, not a bug.",
        "tr_pl": "TR_FL(calc) × Slide Valve % / 100. Same live-denominator flag logic as TR_FL.",
        "kw_per_ton": "Measured Motor kW / TR_PL(calc). Same live-denominator flag logic as TR_FL/TR_PL.",
        "slide_vlv": "Physical range sanity check only: valid = 0-100%.",
        "suct_temp": "Live suct_temp vs the compressor's own documented Design SST (Equipment_Config). Compressor 8 has no documented Design SST and will show N/A.",
        "disc_press": "Live disc_press vs the pressure equivalent of the design condensing temp (95°F for all 14 units), via (Design_SCT-19.5)/0.575.",
        "motor_kw": "Live motor_kw vs nameplate-rated motor kW (Motor HP × 0.7457). One-sided ceiling check — margin = Rated − Live.",
        "kwh": "Re-integrated cumulative energy (Σ Motor kW × elapsed hours), anchored to the PLC's own first reading in the dataset, self-compared against the PLC's own running kWh meter.",
        "motor_kw_sv": "Working proportional estimate (no manual-sourced formula exists): Expected kW = Nameplate Rated kW × (Slide Valve % / 100). Treat as directional.",
    }
    st.write(notes.get(metric_key, ""))
    st.caption(f"Comparison method: {ttype}  |  Tolerance 1: {tol1_eff if tol_applicable else '—'}  Tolerance 2: {tol2_eff if tol_applicable else '—'}")

st.caption(
    "Known data-quality notes (apply to all compressors): the source historian export has duplicate-timestamp buckets "
    "(two real samples sharing one rounded label) — not deduplicated here, same as the original workbook. "
    "Suction Pressure Setpoint occasionally reports a physically impossible ~-14.7 placeholder value; this is not filtered "
    "and will show as Invalid when it occurs."
)
