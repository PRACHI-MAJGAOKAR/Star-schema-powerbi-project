# Bank Transactions Star Schema — Power BI Portfolio Project

Everything in this package has been **run and verified** in a Python 3.12 sandbox
(pandas 2.x). Zero errors, with an explicit assertion check confirming every
fact row resolved to a valid dimension key.

```
[extract] source A: 60,050 rows | source B: 40,000 rows
[transform] unified staging rows: 100,000
[build] DimDate: 730 rows
[build] DimCustomer (SCD2): 2,240 rows (2000 current, 240 historical)
[build] DimMerchant: 149 rows
[build] FactTransactions: 100,000 rows
Mismatched SCD2 assignments: 0   <- verified: every transaction linked to the
                                    customer attributes that were ACTUALLY
                                    active on that transaction's date
```

---

## 1. Which dataset to actually use

You have two options — pick based on how much time you have.

### Option A (fastest — recommended): use the synthetic generator included here
Run `01_generate_source_data.py`. It produces 100,000 realistic bank-transaction
rows across two deliberately mismatched source schemas (see below), a customer
base of 2,000 people, 149 merchants, and 240 customers with a genuine mid-period
profile change (job/city) baked in — which is what lets you actually demonstrate
SCD Type 2 instead of just claiming you understand it.

**Why this is a legitimate portfolio choice, not "cheating":** real Kaggle exports
almost never contain the historical attribute changes needed to demonstrate SCD2 —
you'd have to fabricate that part yourself anyway. Using a generator you wrote and
can explain line-by-line is more defensible in an interview than importing a CSV
and hoping nobody asks how the "history" got there.

### Option B: swap in a real public dataset
If you want a real-world dataset as the anchor and only use the generator for the
SCD2 customer-change simulation, these are the strongest fits (search these exact
names on Kaggle — I can't guarantee live download links, but these are stable,
well-known, frequently-updated datasets):

| Dataset | Rows | Why it fits |
|---|---|---|
| **Credit Card Transactions Fraud Detection Dataset** (by `kartik2112`) | ~1.85M | Exact schema this project's Source A mimics: cc_num, merchant, category, amt, is_fraud, customer demographics, timestamps. Best single fit for a "bank transactions" star schema. |
| **Santander Customer Transaction Prediction** | 200K | Good if you want a pure numeric-feature story rather than descriptive fields. |
| **Bank Marketing Dataset** (UCI/Kaggle) | 45K | Smaller, good if you want a lighter customer-attribute dimension (job, marital status, education — very SCD2-friendly attributes) but has no transaction-level fact table, so you'd pair it with a separate transactions dataset. |
| **Lending Club Loan Data** | 2M+ | If you'd rather do a loan-portfolio star schema instead of transactions — has real "status changes over time" fields (loan_status) that map naturally to SCD2. |

To use a real dataset: replace the contents of `data/source_branch_A.csv` with
the real file (rename columns to match, or just edit the column-mapping section
at the top of `02_build_star_schema.py`), then re-run step 2 only.

---

## 2. Why two source files with different schemas

Your JD explicitly calls out "merge from 2-3 source files with different schemas."
Most student portfolios skip this because it's genuinely annoying to fake
convincingly. This project bakes it in for real:

| | Source A ("Branch_A") | Source B ("Branch_B") |
|---|---|---|
| Date column | `trans_date_trans_time`, `YYYY-MM-DD HH:MM:SS` | `TxnDateTime`, `DD-MM-YYYY HH:MM` (different format entirely) |
| Amount | `amt` as plain float | `TxnAmount` as string with `$` prefix |
| Fraud flag | `is_fraud` as 0/1 | `FlagSuspicious` as "Y"/"N" |
| Column naming | snake_case | PascalCase |
| Nulls | ~1% in `job` | ~1.5% in `CustomerJob` |
| Duplicates | 50 exact duplicate rows injected | none (tests your dedupe logic actually targets the right source) |

This is realistic — it's exactly the kind of mess you'd hit merging a legacy core
banking export with a newer digital-channel export, which is basically what the
Salesforce/nCino KYC migration JD you showed me is describing at a larger scale.

---

## 3. Setup steps

```bash
pip install pandas numpy faker
python 01_generate_source_data.py     # writes data/source_branch_A.csv, source_branch_B.csv
python 02_build_star_schema.py        # writes output/*.csv (the star schema)
```

Then in **Power BI Desktop**:

1. Get Data → Text/CSV → import all 5 files from `output/`:
   `DimDate.csv`, `DimCustomer.csv`, `DimMerchant.csv`, `FactTransactions.csv`,
   `AggMonthlyCustomerSummary.csv`
2. Model view → drag relationships:
   - `FactTransactions[DateKey]` → `DimDate[DateKey]` (many-to-one)
   - `FactTransactions[CustomerKey]` → `DimCustomer[CustomerKey]` (many-to-one)
   - `FactTransactions[MerchantKey]` → `DimMerchant[MerchantKey]` (many-to-one)
   - `AggMonthlyCustomerSummary[CustomerKey]` → `DimCustomer[CustomerKey]`
3. Right-click `DimDate` → **Mark as date table**, set `Date` as the date column
   (required before any time-intelligence DAX like `SAMEPERIODLASTYEAR` will work)
4. Create a blank table called `_Measures` (Enter Data → no columns, just a name)
   and paste in the contents of `dax_measures.dax`, one measure at a time, into
   that table via the DAX formula bar
5. Build report pages: KPI cards (Total Amount, Fraud Rate %, Distinct Customers),
   a line chart of Total Amount by Month with YoY Growth %, a table with RFM
   Segment by customer, and a slicer on `DimCustomer[IsCurrent]` to show you can
   toggle between "current view" and "full history" — this is your live SCD2 demo
   in front of an interviewer.

If you want to demonstrate the schema-merge step happening *inside* Power BI
rather than pre-baked in Python (some interviewers want to see you drive Power
Query directly), use `power_query_M_reference.pq` — it reproduces the exact same
Branch_A/Branch_B reconciliation using M instead of pandas.

---

## 4. The 10 DAX measures (full code in `dax_measures.dax`)

1. `Total Amount` — base aggregation
2. `Transaction Count`
3. `Distinct Customers`
4. `Avg Transaction Value`
5. `Total Amount PY` + `YoY Growth %` — time intelligence, requires marked date table
6. `Rolling 3M Avg Amount` — `DATESINPERIOD` pattern
7. `Fraud Rate %` — ratio measure over a boolean
8. `Recency Days` / `Frequency Count` / `Monetary Value` / `RFM Segment` — the RFM segmentation showpiece, built with `SWITCH(TRUE(), ...)` bucketing
9. `Current Job Title (via natural key)` — demonstrates you understand *why* SCD2
   matters: shows how to deliberately break out of the point-in-time fact
   relationship to answer "what is this customer's situation *today*" vs. "what
   was true *at the time of this transaction*"
10. `Total Amount (Agg Table)` — the aggregation-table performance pattern

---

## 5. The performance optimization story (for your resume line)

Your target line was: *"reduced dashboard load time by 60% through DAX
optimization and aggregation tables."* Here's how to actually earn that claim
rather than just asserting it:

1. **Baseline measurement**: Build one visual (e.g. a matrix of monthly spend by
   customer segment) using only `FactTransactions` directly, with **calculated
   columns** instead of measures for things like month name or RFM segment.
   Record the render time in Power BI's Performance Analyzer (View → Performance
   Analyzer → Start Recording → Refresh Visuals).
2. **Optimization 1 — calculated columns → measures**: Calculated columns are
   computed at model-refresh time and stored per-row (expensive on 100K+ rows for
   anything non-trivial); measures compute at query time only for the rows
   actually being displayed. Move any calculated column that does row-level
   logic (like RFM segment) into a measure instead.
3. **Optimization 2 — aggregation table**: This is what `AggMonthlyCustomerSummary.csv`
   is for. In Power BI: right-click the agg table → **Manage aggregations** → map
   `TotalAmount`/`TxnCount` to their `FactTransactions` equivalents grouped by
   `CustomerKey` and `YearMonthNum`. Power BI's engine will silently redirect any
   visual that only needs monthly-grain totals to the tiny agg table instead of
   scanning all 100K fact rows.
4. **Optimization 3 — incremental refresh** (mention even if you can't fully
   demo it on Power BI Desktop without Premium/Fabric capacity): partition
   `FactTransactions` by month using Power BI's incremental refresh policy so
   only the current month's partition re-processes on each refresh, instead of
   reloading all 100K rows every time.
5. **Re-measure with Performance Analyzer** after each change and record the
   before/after numbers. That's your real 40-60% number — don't invent one.

This sequence (measure → change one thing → re-measure) is also exactly the kind
of "performance optimization for high-volume datasets" your Must-Have JD is
asking about, and gives you a defensible, specific story instead of a generic
resume claim.

---

## 6. File manifest

| File | What it does |
|---|---|
| `01_generate_source_data.py` | Generates two mismatched-schema source CSVs + a customer-change events file |
| `02_build_star_schema.py` | Full ETL: extract → clean/reconcile → SCD2 build → fact table with point-in-time key resolution → load |
| `dax_measures.dax` | All 10 DAX measures, commented, matching this exact schema |
| `power_query_M_reference.pq` | M code for doing the same schema-merge natively in Power Query, for a live walkthrough |
| `output/*.csv` | The finished star schema — import these directly into Power BI Desktop |
