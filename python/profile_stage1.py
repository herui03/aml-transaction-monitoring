import duckdb
con = duckdb.connect()
CSV = "data/raw/SAML-D.csv"
src = f"read_csv_auto('{CSV}', header=true)"

def q(sql): return con.execute(sql).fetchdf()

print("="*70); print("1. SHAPE & SCHEMA"); print("="*70)
print(q(f"SELECT count(*) AS rows FROM {src}").to_string(index=False))
print()
print(q(f"DESCRIBE SELECT * FROM {src}").to_string(index=False))

print("\n"+"="*70); print("2. GRAIN CHECK - is one row one transaction?"); print("="*70)
print(q(f"""
SELECT count(*) AS total_rows,
       count(*) - count(DISTINCT (Time,Date,Sender_account,Receiver_account,Amount)) AS exact_dupes
FROM {src}
""").to_string(index=False))

print("\n"+"="*70); print("3. MISSINGNESS (% null per column)"); print("="*70)
cols = q(f"DESCRIBE SELECT * FROM {src}")["column_name"].tolist()
sel = ", ".join([f"round(100.0*sum(CASE WHEN \"{c}\" IS NULL THEN 1 ELSE 0 END)/count(*),4) AS \"{c}\"" for c in cols])
print(q(f"SELECT {sel} FROM {src}").T.rename(columns={0:"pct_null"}).to_string())

print("\n"+"="*70); print("4. AMOUNT DISTRIBUTION  <-- decides the threshold"); print("="*70)
print(q(f"""
SELECT count(*) AS n, round(min(Amount),2) AS min, round(avg(Amount),2) AS mean,
       round(quantile_cont(Amount,0.25),2) AS p25, round(quantile_cont(Amount,0.50),2) AS median,
       round(quantile_cont(Amount,0.75),2) AS p75, round(quantile_cont(Amount,0.90),2) AS p90,
       round(quantile_cont(Amount,0.95),2) AS p95, round(quantile_cont(Amount,0.99),2) AS p99,
       round(quantile_cont(Amount,0.999),2) AS p999, round(max(Amount),2) AS max
FROM {src}
""").T.rename(columns={0:"value"}).to_string())

print("\n"+"="*70); print("5. DATE RANGE & TIME GRANULARITY"); print("="*70)
print(q(f"""
SELECT min(Date) AS first_date, max(Date) AS last_date,
       count(DISTINCT Date) AS distinct_days,
       count(DISTINCT Sender_account) AS distinct_senders,
       count(DISTINCT Receiver_account) AS distinct_receivers
FROM {src}
""").T.rename(columns={0:"value"}).to_string())

print("\n"+"="*70); print("6. CLASS IMBALANCE - Is_laundering"); print("="*70)
print(q(f"""
SELECT Is_laundering, count(*) AS n,
       round(100.0*count(*)/sum(count(*)) OVER (),4) AS pct
FROM {src} GROUP BY 1 ORDER BY 1
""").to_string(index=False))

print("\n"+"="*70); print("7. LAUNDERING_TYPE breakdown  <-- our ground truth"); print("="*70)
print(q(f"""
SELECT Laundering_type, Is_laundering, count(*) AS n,
       round(100.0*count(*)/sum(count(*)) OVER (),4) AS pct
FROM {src} GROUP BY 1,2 ORDER BY Is_laundering DESC, n DESC
""").to_string(index=False))

print("\n"+"="*70); print("8. PAYMENT_TYPE"); print("="*70)
print(q(f"SELECT Payment_type, count(*) AS n FROM {src} GROUP BY 1 ORDER BY n DESC").to_string(index=False))

print("\n"+"="*70); print("9. CROSS-BORDER FEASIBILITY  <-- decides if R-02 works"); print("="*70)
print(q(f"""
SELECT (Sender_bank_location <> Receiver_bank_location) AS is_cross_border,
       count(*) AS n, round(100.0*count(*)/sum(count(*)) OVER (),2) AS pct
FROM {src} GROUP BY 1 ORDER BY 1
""").to_string(index=False))
print()
print("-- top sender locations --")
print(q(f"SELECT Sender_bank_location, count(*) n FROM {src} GROUP BY 1 ORDER BY n DESC LIMIT 10").to_string(index=False))
print()
print("-- top receiver locations --")
print(q(f"SELECT Receiver_bank_location, count(*) n FROM {src} GROUP BY 1 ORDER BY n DESC LIMIT 10").to_string(index=False))
