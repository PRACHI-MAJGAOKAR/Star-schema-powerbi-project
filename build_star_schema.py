"""
build_star_schema.py

Real ETL: cleans two differently-shaped source exports, reconciles
their schemas, deduplicates, and builds a proper star schema:

    DimDate          (standard date dimension)
    DimCustomer       (SCD Type 2 — full history preserved)
    DimMerchant
    FactTransactions  (grain: one row per transaction)

Output: CSVs in output/ ready to import into Power BI Desktop
(Get Data > Text/CSV, or Get Data > Folder if you prefer).

Run:
    python build_star_schema.py
"""

import pandas as pd
import numpy as np

pd.set_option("mode.chained_assignment", None)


# STEP 1 — EXTRACT: load both sources

src_a = pd.read_csv("data/source_branch_A.csv")
src_b = pd.read_csv("data/source_branch_B.csv")
changes = pd.read_csv("data/customer_profile_changes.csv", parse_dates=["change_date"])

print(f"[extract] source A: {len(src_a):,} rows | source B: {len(src_b):,} rows")


#TRANSFORM: reconcile schemas into one staging table


# clean source A 
src_a = src_a.drop_duplicates()                      # remove exact dupes injected earlier
src_a["job"] = src_a["job"].fillna("Unknown")         # handle nulls
src_a["trans_date_trans_time"] = pd.to_datetime(src_a["trans_date_trans_time"])
src_a["dob"] = pd.to_datetime(src_a["dob"])
src_a["is_fraud_flag"] = src_a["is_fraud"].astype(bool)

staging_a = pd.DataFrame({
    "source_system": "Branch_A",
    "txn_id": src_a["trans_num"],
    "txn_datetime": src_a["trans_date_trans_time"],
    "cc_num": src_a["cc_num"],
    "merchant_name": src_a["merchant"],
    "category": src_a["category"],
    "amount": src_a["amt"].astype(float),
    "first_name": src_a["first"],
    "last_name": src_a["last"],
    "gender": src_a["gender"],
    "city": src_a["city"],
    "state": src_a["state"],
    "job": src_a["job"],
    "dob": src_a["dob"],
    "is_fraud": src_a["is_fraud_flag"],
})

# clean source B: different names, dd-mm-yyyy dates, "$" amounts, Y/N flag 
src_b = src_b.drop_duplicates()
src_b["CustomerJob"] = src_b["CustomerJob"].fillna("Unknown")
src_b["TxnDateTime"] = pd.to_datetime(src_b["TxnDateTime"], format="%d-%m-%Y %H:%M")
src_b["CustomerDOB"] = pd.to_datetime(src_b["CustomerDOB"], format="%d-%m-%Y")
src_b["amount_clean"] = src_b["TxnAmount"].str.replace("$", "", regex=False).astype(float)
src_b["is_fraud_flag"] = src_b["FlagSuspicious"].map({"Y": True, "N": False})

staging_b = pd.DataFrame({
    "source_system": "Branch_B",
    "txn_id": src_b["TransactionID"],
    "txn_datetime": src_b["TxnDateTime"],
    "cc_num": src_b["CardNumber"],
    "merchant_name": src_b["MerchantName"],
    "category": src_b["MerchantCategory"],
    "amount": src_b["amount_clean"],
    "first_name": src_b["CustomerFirstName"],
    "last_name": src_b["CustomerLastName"],
    "gender": src_b["CustomerGender"],
    "city": src_b["CustomerCity"],
    "state": src_b["CustomerState"],
    "job": src_b["CustomerJob"],
    "dob": src_b["CustomerDOB"],
    "is_fraud": src_b["is_fraud_flag"],
})

# union into one staging fact-grain table 
staging = pd.concat([staging_a, staging_b], ignore_index=True)
staging = staging.dropna(subset=["cc_num", "amount", "txn_datetime"])   # required fields
staging = staging.drop_duplicates(subset=["source_system", "txn_id"])   # final safety dedupe

print(f"[transform] unified staging rows: {len(staging):,}")
print(f"[transform] date range: {staging['txn_datetime'].min()} to {staging['txn_datetime'].max()}")


# BUILD DimDate
date_min = staging["txn_datetime"].min().normalize()
date_max = staging["txn_datetime"].max().normalize()
all_dates = pd.date_range(date_min, date_max, freq="D")

dim_date = pd.DataFrame({"Date": all_dates})
dim_date["DateKey"] = dim_date["Date"].dt.strftime("%Y%m%d").astype(int)
dim_date["Year"] = dim_date["Date"].dt.year
dim_date["Quarter"] = dim_date["Date"].dt.quarter
dim_date["Month"] = dim_date["Date"].dt.month
dim_date["MonthName"] = dim_date["Date"].dt.strftime("%B")
dim_date["MonthYear"] = dim_date["Date"].dt.strftime("%b-%Y")
dim_date["Day"] = dim_date["Date"].dt.day
dim_date["DayOfWeek"] = dim_date["Date"].dt.day_name()
dim_date["IsWeekend"] = dim_date["Date"].dt.dayofweek.isin([5, 6])
dim_date["YearMonthNum"] = dim_date["Date"].dt.strftime("%Y%m").astype(int)
dim_date = dim_date[["DateKey", "Date", "Year", "Quarter", "Month", "MonthName",
                     "MonthYear", "Day", "DayOfWeek", "IsWeekend", "YearMonthNum"]]

print(f"[build] DimDate: {len(dim_date):,} rows")


# BUILD DimCustomer with SCD TYPE 2
# Base (original) attributes — one row per distinct customer as first seen
base_cust = (
    staging.sort_values("txn_datetime")
    .drop_duplicates(subset="cc_num", keep="first")
    [["cc_num", "first_name", "last_name", "gender", "city", "state", "job", "dob"]]
    .reset_index(drop=True)
)

scd_rows = []
surrogate_key = 1
GLOBAL_START = pd.Timestamp("1900-01-01")
GLOBAL_END = pd.Timestamp("9999-12-31")

changes_by_cust = changes.set_index("cc_num")

for _, cust in base_cust.iterrows():
    cc = cust["cc_num"]

    if cc in changes_by_cust.index:
        # customer HAS a mid-period change -> two SCD2 rows
        chg = changes_by_cust.loc[cc]
        change_date = pd.Timestamp(chg["change_date"])

        # Row 1: original attributes, valid from beginning of time to day before change
        scd_rows.append({
            "CustomerKey": surrogate_key,
            "cc_num": cc,
            "FirstName": cust["first_name"],
            "LastName": cust["last_name"],
            "Gender": cust["gender"],
            "City": cust["city"],
            "State": cust["state"],
            "Job": cust["job"],
            "DOB": cust["dob"],
            "EffectiveDate": GLOBAL_START,
            "EndDate": change_date - pd.Timedelta(days=1),
            "IsCurrent": False,
        })
        surrogate_key += 1

        # Row 2: updated attributes (new job / new city), valid from change date onward
        scd_rows.append({
            "CustomerKey": surrogate_key,
            "cc_num": cc,
            "FirstName": cust["first_name"],
            "LastName": cust["last_name"],
            "Gender": cust["gender"],
            "City": chg["new_city"],
            "State": cust["state"],
            "Job": chg["new_job"],
            "DOB": cust["dob"],
            "EffectiveDate": change_date,
            "EndDate": GLOBAL_END,
            "IsCurrent": True,
        })
        surrogate_key += 1
    else:
        # no change -> single row, always current
        scd_rows.append({
            "CustomerKey": surrogate_key,
            "cc_num": cc,
            "FirstName": cust["first_name"],
            "LastName": cust["last_name"],
            "Gender": cust["gender"],
            "City": cust["city"],
            "State": cust["state"],
            "Job": cust["job"],
            "DOB": cust["dob"],
            "EffectiveDate": GLOBAL_START,
            "EndDate": GLOBAL_END,
            "IsCurrent": True,
        })
        surrogate_key += 1

dim_customer = pd.DataFrame(scd_rows)
print(f"[build] DimCustomer (SCD2): {len(dim_customer):,} rows "
      f"({dim_customer['IsCurrent'].sum()} current, "
      f"{(~dim_customer['IsCurrent']).sum()} historical)")


#BUILD DimMerchant

dim_merchant = (
    staging[["merchant_name", "category"]]
    .drop_duplicates()
    .reset_index(drop=True)
)
dim_merchant.insert(0, "MerchantKey", range(1, len(dim_merchant) + 1))
dim_merchant.columns = ["MerchantKey", "MerchantName", "Category"]

print(f"[build] DimMerchant: {len(dim_merchant):,} rows")


# BUILD FactTransactions (point-in-time SCD2 lookup)
# For each transaction, find the DimCustomer row that was EFFECTIVE
# on the transaction date (this is the whole point of SCD2: a
# transaction from before the change links to the OLD attributes).

dim_customer_sorted = dim_customer.sort_values(["cc_num", "EffectiveDate"])

def lookup_customer_key(cc_num, txn_date, lookup_df):
    candidates = lookup_df[
        (lookup_df["cc_num"] == cc_num)
        & (lookup_df["EffectiveDate"] <= txn_date)
        & (lookup_df["EndDate"] >= txn_date)
    ]
    if len(candidates) == 0:
        return None
    return candidates.iloc[0]["CustomerKey"]

# Vectorized approach for performance: merge_asof per customer group
# is much faster than row-by-row lookup_customer_key on 100k rows.
staging_sorted = staging.sort_values("txn_datetime")
fact_parts = []
for cc, grp in staging_sorted.groupby("cc_num"):
    cust_hist = dim_customer_sorted[dim_customer_sorted["cc_num"] == cc][
        ["CustomerKey", "EffectiveDate"]
    ].sort_values("EffectiveDate")
    merged = pd.merge_asof(
        grp.sort_values("txn_datetime"),
        cust_hist,
        left_on="txn_datetime",
        right_on="EffectiveDate",
        direction="backward",
    )
    fact_parts.append(merged)

fact_with_keys = pd.concat(fact_parts, ignore_index=True)

fact_with_keys = fact_with_keys.merge(
    dim_merchant, left_on=["merchant_name", "category"],
    right_on=["MerchantName", "Category"], how="left"
)
fact_with_keys["DateKey"] = fact_with_keys["txn_datetime"].dt.strftime("%Y%m%d").astype(int)

fact_transactions = fact_with_keys[[
    "txn_id", "source_system", "DateKey", "CustomerKey", "MerchantKey",
    "amount", "is_fraud", "txn_datetime"
]].rename(columns={
    "txn_id": "TransactionID",
    "source_system": "SourceSystem",
    "amount": "Amount",
    "is_fraud": "IsFraud",
    "txn_datetime": "TransactionDateTime",
})
fact_transactions.insert(0, "TransactionKey", range(1, len(fact_transactions) + 1))

print(f"[build] FactTransactions: {len(fact_transactions):,} rows")

# sanity check: no null keys after the joins
assert fact_transactions["CustomerKey"].isna().sum() == 0, "Unmatched customer keys found!"
assert fact_transactions["MerchantKey"].isna().sum() == 0, "Unmatched merchant keys found!"
assert fact_transactions["DateKey"].isna().sum() == 0, "Unmatched date keys found!"


# LOAD: write star schema to output/

dim_date.to_csv("output/DimDate.csv", index=False)
dim_customer.to_csv("output/DimCustomer.csv", index=False)
dim_merchant.to_csv("output/DimMerchant.csv", index=False)
fact_transactions.to_csv("output/FactTransactions.csv", index=False)

# Pre-aggregated monthly summary table -> used for the performance
# optimization section (aggregation tables speed up high-level
# visuals so Power BI doesn't scan the full fact table every time).
monthly_agg = fact_transactions.merge(dim_date, on="DateKey").groupby(
    ["YearMonthNum", "MonthYear", "CustomerKey"], as_index=False
).agg(
    TotalAmount=("Amount", "sum"),
    TxnCount=("TransactionKey", "count"),
    FraudCount=("IsFraud", "sum"),
)
monthly_agg.to_csv("output/AggMonthlyCustomerSummary.csv", index=False)

print("\n[load] Star schema written to output/:")
for f in ["DimDate.csv", "DimCustomer.csv", "DimMerchant.csv",
          "FactTransactions.csv", "AggMonthlyCustomerSummary.csv"]:
    print(f"   - {f}")

