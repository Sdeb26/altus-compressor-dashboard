# Altus Compressor Validation Tool — Python/Streamlit version

This is a Python rebuild of `Altus_Compressor_Validation_Tool__v3.xlsx` as a live
web dashboard instead of an Excel workbook. Covers the full fleet (C1-C14), same
11 validated metrics, same formulas, same tolerances, same known data-quality
caveats — pulled directly from the v3 workbook's own Calc_Engine / Input_Config
/ Equipment_Config sheets and checked line-by-line against its cached values.

## What's different from the Excel version

- Runs against the **full-resolution** historian export (11,853 rows, every
  real sample) — no downsampling needed, unlike the Excel file.
- Recalculates in under a second when you change the compressor, metric, or
  date range — no multi-minute LibreOffice recalc step.
- Opens as a webpage instead of a file you have to re-download each time.
- A new week's data can be loaded straight from the browser (see "Uploading
  a new week of data" below) — no one needs file/terminal access to refresh
  it, once it's hosted.

## How to run it

1. Install Python 3.10+ if you don't already have it.
2. Open a terminal in this folder and run:
   ```
   pip install -r requirements.txt
   streamlit run app.py
   ```
3. It opens automatically in your browser at `http://localhost:8501`. Anyone
   on the same network can also open it at the "Network URL" Streamlit prints.

## Files

- `app.py` — the dashboard itself (dropdowns, summary tiles, chart).
- `calc_engine.py` — the formula logic. Every metric's Live/Expected/Flag
  calculation, validated against the original workbook's cached values.
- `equipment_config.csv` — the per-compressor nameplate/coefficient table
  for all 14 compressors, pulled from the v3 workbook's Equipment_Config sheet.
- `raw_data.csv.gz` — the historian export, pre-converted to a compressed CSV
  (deliberately not a `.parquet` file — some locked-down company PCs block
  the pyarrow library's native DLL, so this sticks to plain CSV which needs
  nothing beyond pandas' built-in reader). Rebuild this with `data_prep.py`
  whenever you have a new export.
- `data_prep.py` — run `python data_prep.py new_export.xlsx` to refresh the
  data behind the dashboard with a fresh historian export.

## Known quirk reproduced on purpose

In the original workbook, three metrics — TR_FL, TR_PL, and kW/Ton — compare
Live against Expected using **Live** as the denominator (not Expected), and
show "N/A" whenever the compressor is idle (Live = 0) rather than flagging a
huge, meaningless deviation. Every other percent-deviation metric divides by
Expected instead. This is reproduced exactly here, matching the delivered
Excel tool's own behavior — not something I "fixed," since changing it would
make this version disagree with the tool your team is already using.

## Known data-quality notes (carried over from the Excel version)

- The source historian export has ~5,853 of 6,000 timestamp buckets where two
  distinct real samples share one rounded timestamp label — kept as separate
  rows, not deduplicated.
- Suction Pressure Setpoint occasionally reports a physically impossible
  ~-14.7 placeholder value for a few samples at a time. Not filtered out —
  will show as Invalid when it happens.
- Compressors 8, 10, and 14 read as idle for the whole exported week (Motor
  kW = 0, Discharge Pressure/Suction Temp stuck at bad-quality placeholder
  values). Their flags are technically correct (0 kW is trivially "Normal"
  against a ceiling check) but don't assume the unit is actually running.
- Compressor 8 has no documented Design SST anywhere in the reference files —
  its Suction Temp check will always show N/A, by design.

## Uploading a new week of data (in the browser)

Open the "🔄 Upload a new weekly historian export" panel at the top of the
dashboard, choose the new `.xlsx` export, tick the confirmation checkbox, and
click "Process and refresh data." It reprocesses the file the same way
`data_prep.py` does and immediately refreshes the dashboard.

Two things worth knowing if this is hosted for a team (e.g. on Streamlit
Community Cloud) rather than run locally:
- **There's one shared copy of the data, not one per person.** If this app is
  hosted centrally and several people have it open, an upload replaces the
  data for everyone currently viewing it, immediately. There's no undo — the
  confirmation checkbox is the only safeguard, so double-check the file first.
- **It's not a permanent archive.** The uploaded file becomes `raw_data.csv.gz`
  on whatever server is running the app. On a free Streamlit Community Cloud
  app this generally survives until the app restarts/redeploys, but isn't
  guaranteed long-term storage — keep your own copy of each week's original
  historian export somewhere durable (e.g. wherever Sigma/the historian
  itself keeps its exports) rather than treating the dashboard as the backup.

If a file doesn't look like a Sigma historian export (wrong sheet name, no
recognizable compressor tags), it's rejected with an error and the dashboard's
existing data is left untouched.

## Extending it

- **New week of data (command line):** run
  `python data_prep.py new_export.xlsx`, restart the app. Equivalent to the
  in-browser upload above, useful for local/offline use.
- **New/changed equipment specs:** edit `equipment_config.csv` directly —
  same columns as the Excel Equipment_Config sheet. Not exposed in the
  browser upload (nameplate data changes rarely and shouldn't be editable by
  just anyone), so this still needs direct file access.
- **Automatic refresh / alerting:** `app.py` and `calc_engine.py` are plain
  Python — a scheduled job can import `calc_engine` directly, compute flags
  for all 14 compressors, and email/Slack on any new Red, without a person
  having to open the dashboard at all.
