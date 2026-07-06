"""
generate_source_data.py

Generates two synthetic "source system" files that deliberately use
DIFFERENT schemas (column names / date formats / casing) to simulate
a real-world scenario where you're merging exports from two banking
branches / systems into one warehouse. 
If you have a real dataset (e.g. Kaggle "Credit Card Transactions Fraud
Detection Dataset" by kartik2112), you can skip this script and point
build_star_schema.py at your real CSV instead — see the README.

Run:
    python 01_generate_source_data.py
Output:
    data/source_branch_A.csv
    data/source_branch_B.csv
"""

import numpy as np
import pandas as pd
from faker import Faker
import random

fake = Faker()
Faker.seed(42)
np.random.seed(42)
random.seed(42)

N_CUSTOMERS = 2000
N_MERCHANTS = 150
N_TXNS_A = 60000
N_TXNS_B = 40000
START_DATE = pd.Timestamp("2023-01-01")
END_DATE = pd.Timestamp("2024-12-31")

CATEGORIES = [
    "grocery", "gas_transport", "entertainment", "food_dining",
    "health_fitness", "home", "kids_pets", "misc_net", "misc_pos",
    "personal_care", "shopping_net", "shopping_pos", "travel"
]
JOBS = [fake.job() for _ in range(80)]


# 1. Build a shared customer master (so both branches reference
#    overlapping real customers) with a mid-year profile change
#    baked in for a subset of customers -> this is what lets us
#    demonstrate SCD Type 2 later, since real Kaggle exports don't
#    ship historical attribute changes.

customers = []
for i in range(1, N_CUSTOMERS + 1):
    cc_num = 4000_0000_0000_0000 + i
    customers.append({
        "cc_num": cc_num,
        "first_name": fake.first_name(),
        "last_name": fake.last_name(),
        "gender": random.choice(["M", "F"]),
        "city": fake.city(),
        "state": fake.state_abbr(),
        "job": random.choice(JOBS),
        "dob": fake.date_of_birth(minimum_age=18, maximum_age=85),
    })
customers_df = pd.DataFrame(customers)

# ~12% of customers get a profile change (job change or relocation)
# at a random point in the transaction window. We store this as a
# separate "change event" table that the star-schema builder will
# use to construct SCD Type 2 history.
n_changes = int(N_CUSTOMERS * 0.12)
changed_customers = customers_df.sample(n=n_changes, random_state=1).copy()
changed_customers["change_date"] = [
    fake.date_between_dates(date_start=START_DATE + pd.Timedelta(days=60),
                             date_end=END_DATE - pd.Timedelta(days=60))
    for _ in range(n_changes)
]
changed_customers["new_job"] = [random.choice(JOBS) for _ in range(n_changes)]
changed_customers["new_city"] = [fake.city() for _ in range(n_changes)]
changed_customers[["cc_num", "change_date", "new_job", "new_city"]].to_csv(
    "data/customer_profile_changes.csv", index=False
)

# 2. Merchant master

merchants = []
for i in range(1, N_MERCHANTS + 1):
    merchants.append({
        "merchant_name": f"{fake.company()} {random.choice(['Inc','LLC','Ltd','Co'])}",
        "category": random.choice(CATEGORIES),
        "merch_lat": round(fake.latitude(), 6),
        "merch_long": round(fake.longitude(), 6),
    })
merchants_df = pd.DataFrame(merchants).drop_duplicates(subset="merchant_name").reset_index(drop=True)


# 3. SOURCE A — "legacy core banking export" schema
#    Columns: trans_date_trans_time, cc_num, merchant, category, amt,
#             first, last, gender, city, state, job, dob, trans_num,
#             is_fraud   (mirrors the well-known Kaggle fraud dataset)

def random_dates(n, start, end):
    delta = (end - start).days
    offsets = np.random.randint(0, delta * 24 * 60, size=n)  # minute-level randomness
    return [start + pd.Timedelta(minutes=int(o)) for o in offsets]

rows_a = []
cust_sample_a = customers_df.sample(n=N_TXNS_A, replace=True, random_state=2).reset_index(drop=True)
merch_sample_a = merchants_df.sample(n=N_TXNS_A, replace=True, random_state=3).reset_index(drop=True)
dates_a = random_dates(N_TXNS_A, START_DATE, END_DATE)

for i in range(N_TXNS_A):
    c = cust_sample_a.iloc[i]
    m = merch_sample_a.iloc[i]
    amt = round(np.random.exponential(scale=65) + 1, 2)
    is_fraud = 1 if np.random.rand() < 0.006 else 0
    rows_a.append({
        "trans_date_trans_time": dates_a[i].strftime("%Y-%m-%d %H:%M:%S"),
        "cc_num": c["cc_num"],
        "merchant": m["merchant_name"],
        "category": m["category"],
        "amt": amt,
        "first": c["first_name"],
        "last": c["last_name"],
        "gender": c["gender"],
        "city": c["city"],
        "state": c["state"],
        "job": c["job"],
        "dob": c["dob"].strftime("%Y-%m-%d"),
        "trans_num": f"A{i:08d}",
        "is_fraud": is_fraud,
    })

source_a = pd.DataFrame(rows_a)

# Inject some realistic dirtiness: nulls + a handful of exact duplicates
dirty_idx = source_a.sample(frac=0.01, random_state=4).index
source_a.loc[dirty_idx, "job"] = np.nan
dup_rows = source_a.sample(n=50, random_state=5)
source_a = pd.concat([source_a, dup_rows], ignore_index=True)

source_a.to_csv("data/source_branch_A.csv", index=False)

# 4. SOURCE B — "newer digital channel export" schema
#    Deliberately different column names, date format (dd-mm-yyyy),
#    amount as string with currency symbol, and no is_fraud column
#    (has a "flag_suspicious" Y/N instead) — forces real schema
#    reconciliation in the ETL step.

rows_b = []
cust_sample_b = customers_df.sample(n=N_TXNS_B, replace=True, random_state=6).reset_index(drop=True)
merch_sample_b = merchants_df.sample(n=N_TXNS_B, replace=True, random_state=7).reset_index(drop=True)
dates_b = random_dates(N_TXNS_B, START_DATE, END_DATE)

for i in range(N_TXNS_B):
    c = cust_sample_b.iloc[i]
    m = merch_sample_b.iloc[i]
    amt = round(np.random.exponential(scale=80) + 1, 2)
    suspicious = "Y" if np.random.rand() < 0.008 else "N"
    rows_b.append({
        "TxnDateTime": dates_b[i].strftime("%d-%m-%Y %H:%M"),
        "CardNumber": c["cc_num"],
        "MerchantName": m["merchant_name"],
        "MerchantCategory": m["category"],
        "TxnAmount": f"${amt}",
        "CustomerFirstName": c["first_name"],
        "CustomerLastName": c["last_name"],
        "CustomerGender": c["gender"],
        "CustomerCity": c["city"],
        "CustomerState": c["state"],
        "CustomerJob": c["job"],
        "CustomerDOB": c["dob"].strftime("%d-%m-%Y"),
        "TransactionID": f"B{i:08d}",
        "FlagSuspicious": suspicious,
    })

source_b = pd.DataFrame(rows_b)
null_idx_b = source_b.sample(frac=0.015, random_state=8).index
source_b.loc[null_idx_b, "CustomerJob"] = None
source_b.to_csv("data/source_branch_B.csv", index=False)

print(f"Source A rows: {len(source_a)}  |  Source B rows: {len(source_b)}")
print(f"Customers: {len(customers_df)}  |  Merchants: {len(merchants_df)}  |  Profile changes: {n_changes}")
print("Done. Files written to data/")
