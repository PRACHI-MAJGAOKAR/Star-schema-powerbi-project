// =================================================================
// POWER QUERY M REFERENCE
// -----------------------------------------------------------------
// The Python scripts (01_generate_source_data.py, 02_build_star_
// schema.py) already do the heavy ETL and hand Power BI five clean
// CSVs. That's the realistic pattern for a 100K-500K row dataset —
// doing SCD2 merge logic natively in M is painful and slow.
//
// BUT your JD explicitly asks for "Power Query / ETL processes"
// hands-on skill, so below is the M code that reproduces the SAME
// schema-reconciliation step (merging source_branch_A.csv and
// source_branch_B.csv, which have different column names/date
// formats/amount formats) natively inside Power Query. Use this if
// you want to demonstrate the transformation live in Power BI
// Desktop rather than pre-baking it in Python — good for a portfolio
// walkthrough video or interview screen-share.
// =================================================================

// ---- Query: "Staging_BranchA" ----
let
    Source = Csv.Document(File.Contents("C:\PowerBI_Project\data\source_branch_A.csv"),
        [Delimiter=",", Columns=14, Encoding=1252, QuoteStyle=QuoteStyle.None]),
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    ChangedTypes = Table.TransformColumnTypes(PromotedHeaders,{
        {"trans_date_trans_time", type datetime},
        {"cc_num", Int64.Type},
        {"amt", type number},
        {"dob", type date},
        {"is_fraud", Int64.Type}
    }),
    FilledJob = Table.ReplaceValue(ChangedTypes, null, "Unknown", Replacer.ReplaceValue, {"job"}),
    RemovedDuplicates = Table.Distinct(FilledJob),
    Renamed = Table.RenameColumns(RemovedDuplicates, {
        {"trans_date_trans_time", "txn_datetime"},
        {"merchant", "merchant_name"},
        {"amt", "amount"},
        {"first", "first_name"},
        {"last", "last_name"},
        {"trans_num", "txn_id"}
    }),
    AddedSourceCol = Table.AddColumn(Renamed, "source_system", each "Branch_A"),
    AddedFraudBool = Table.AddColumn(AddedSourceCol, "is_fraud_flag", each [is_fraud] = 1, type logical)
in
    AddedFraudBool

// ---- Query: "Staging_BranchB" ----
let
    Source = Csv.Document(File.Contents("C:\PowerBI_Project\data\source_branch_B.csv"),
        [Delimiter=",", Columns=14, Encoding=1252, QuoteStyle=QuoteStyle.None]),
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),

    // dd-mm-yyyy needs an explicit culture parse — this is the #1
    // silent-bug source when merging multi-region date exports
    ParsedDates = Table.TransformColumns(PromotedHeaders, {
        {"TxnDateTime", each DateTime.FromText(_, "en-GB"), type datetime},
        {"CustomerDOB", each Date.FromText(_, "en-GB"), type date}
    }),

    // strip "$" then convert to number
    CleanedAmount = Table.TransformColumns(ParsedDates, {
        {"TxnAmount", each Number.FromText(Text.Remove(_, "$")), type number}
    }),

    FilledJob = Table.ReplaceValue(CleanedAmount, null, "Unknown", Replacer.ReplaceValue, {"CustomerJob"}),
    RemovedDuplicates = Table.Distinct(FilledJob),

    Renamed = Table.RenameColumns(RemovedDuplicates, {
        {"TxnDateTime", "txn_datetime"},
        {"CardNumber", "cc_num"},
        {"MerchantName", "merchant_name"},
        {"MerchantCategory", "category"},
        {"TxnAmount", "amount"},
        {"CustomerFirstName", "first_name"},
        {"CustomerLastName", "last_name"},
        {"CustomerGender", "gender"},
        {"CustomerCity", "city"},
        {"CustomerState", "state"},
        {"CustomerJob", "job"},
        {"CustomerDOB", "dob"},
        {"TransactionID", "txn_id"}
    }),
    AddedSourceCol = Table.AddColumn(Renamed, "source_system", each "Branch_B"),
    AddedFraudBool = Table.AddColumn(AddedSourceCol, "is_fraud_flag", each [FlagSuspicious] = "Y", type logical),
    RemovedOldFlag = Table.RemoveColumns(AddedFraudBool, {"FlagSuspicious"})
in
    RemovedOldFlag

// ---- Query: "Staging_Unified" (combine both, now same schema) ----
let
    Combined = Table.Combine({Staging_BranchA, Staging_BranchB}),
    SelectedColumns = Table.SelectColumns(Combined, {
        "source_system", "txn_id", "txn_datetime", "cc_num", "merchant_name",
        "category", "amount", "first_name", "last_name", "gender", "city",
        "state", "job", "dob", "is_fraud_flag"
    }),
    RemovedNullKeys = Table.SelectRows(SelectedColumns, each [cc_num] <> null and [amount] <> null)
in
    RemovedNullKeys

// -----------------------------------------------------------------
// PERFORMANCE NOTE for Power Query specifically:
// - Disable "Enable load" on Staging_BranchA / Staging_BranchB /
//   Staging_Unified (right-click query > uncheck Enable Load) once
//   your Dim/Fact queries are built on top of them — this stops
//   Power BI from materializing three extra unused tables in the
//   model, which is a common beginner mistake that bloats the .pbix
//   and slows refresh.
// - Use "Table.Buffer" sparingly and only if you see query folding
//   break — for CSV sources folding doesn't apply anyway, so this
//   matters more if you later swap the source to a SQL database.
// =================================================================
