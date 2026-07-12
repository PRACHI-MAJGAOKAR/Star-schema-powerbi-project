# Bank Transactions Star Schema  
# Power BI Portfolio Project

Everything in this package has been **run and verified** in a Python 3.12 sandbox
(pandas 2.x). Zero errors, with an explicit assertion check confirmed every
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

## 1. Dataset

You have two options :

### Option A : use the synthetic generator included here
Run `generate_source_data.py`. It produces 100,000 realistic bank-transaction
rows across two deliberately mismatched source schemas (see below), a customer
base of 2,000 people, 149 merchants, and 240 customers with a genuine mid-period
profile change (job/city) baked in which is what lets you actually demonstrate
SCD Type 2 instead of just claiming you understand it.

### Option B: swap in a real public dataset
If you want a real-world dataset as the anchor and only use the generator for the
SCD2 customer-change simulation, these are the strongest fits :

| Dataset | Rows | Why it fits |
|---|---|---|
| **Credit Card Transactions Fraud Detection Dataset** (by `kartik2112`) | ~1.85M | Exact schema this project's Source A mimics: cc_num, merchant, category, amt, is_fraud, customer demographics, timestamps. Best single fit for a "bank transactions" star schema. |
| **Santander Customer Transaction Prediction** | 200K | Good if you want a pure numeric-feature story rather than descriptive fields. |
| **Bank Marketing Dataset** (UCI/Kaggle) | 45K | Smaller, good if you want a lighter customer-attribute dimension (job, marital status, education, very SCD2-friendly attributes) but has no transaction-level fact table, so you'd pair it with a separate transactions dataset. |
| **Lending Club Loan Data** | 2M+ | If you'd rather do a loan-portfolio star schema instead of transactions and has real "status changes over time" fields (loan_status) that map naturally to SCD2. |

To use a real dataset: replace the contents of `data/source_branch_A.csv` with
the real file (rename columns to match, or just edit the column-mapping section
at the top of `build_star_schema.py`), then re-run step 2 only.

---

| | Source A ("Branch_A") | Source B ("Branch_B") |
|---|---|---|
| Date column | `trans_date_trans_time`, `YYYY-MM-DD HH:MM:SS` | `TxnDateTime`, `DD-MM-YYYY HH:MM` (different format entirely) |
| Amount | `amt` as plain float | `TxnAmount` as string with `$` prefix |
| Fraud flag | `is_fraud` as 0/1 | `FlagSuspicious` as "Y"/"N" |
| Column naming | snake_case | PascalCase |
| Nulls | ~1% in `job` | ~1.5% in `CustomerJob` |
| Duplicates | 50 exact duplicate rows injected | none (tests your dedupe logic actually targets the right source) |

---

## 3. Setup steps

```bash
pip install pandas numpy faker
python generate_source_data.py     # writes data/source_branch_A.csv, source_branch_B.csv
python build_star_schema.py        # writes output/*.csv (the star schema)
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

---

## 4. The 10 DAX measures (full code in `dax_measures.dax`)

1. `Total Amount`
2. `Transaction Count`
3. `Distinct Customers`
4. `Avg Transaction Value`
5. `Total Amount PY` + `YoY Growth %`
6. `Rolling 3M Avg Amount` 
7. `Fraud Rate %` 
8. `Recency Days` / `Frequency Count` / `Monetary Value` / `RFM Segment` 
9. `Current Job Title (via natural key)` 
10. `Total Amount (Agg Table)` 

---


## 5. File manifest

| File | What it does |
|---|---|
| `generate_source_data.py` | Generates two mismatched-schema source CSVs + a customer-change events file |
| `build_star_schema.py` | Full ETL: extract → clean/reconcile → SCD2 build → fact table with point-in-time key resolution → load |
| `dax_measures.dax` | All 10 DAX measures, commented, matching this exact schema |
| `power_query_M_reference.pq` | M code for doing the same schema-merge natively in Power Query, for a live walkthrough |
| `output/*.csv` | The finished star schema. import these directly into Power BI Desktop |
