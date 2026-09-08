import duckdb, time, os
con = duckdb.connect("data/processed/aml.duckdb")
t0=time.time()
con.execute(open("sql/features.sql").read())
print(f"features built in {time.time()-t0:.1f}s\n")

print(con.execute("SELECT count(*) AS rows, count(DISTINCT txn_id) AS uniq FROM features").fetchdf().to_string(index=False))
cols = con.execute("DESCRIBE features").fetchdf()
print(f"\nfeature columns: {len(cols)}")
print(", ".join(cols["column_name"].tolist()))

print("\n--- time-based split (NO random split: that would leak the future) ---")
print(con.execute("""
SELECT CASE WHEN txn_date <= DATE '2023-05-31' THEN 'train' ELSE 'test' END AS split,
       count(*) AS rows, min(txn_date) AS from_dt, max(txn_date) AS to_dt,
       sum(is_laundering) AS positives,
       round(100.0*sum(is_laundering)/count(*),4) AS pos_pct
FROM features GROUP BY 1 ORDER BY 1 DESC
""").to_fdf().to_string(index=False) if False else con.execute("""
SELECT CASE WHEN txn_date <= DATE '2023-05-31' THEN 'train' ELSE 'test' END AS split,
       count(*) AS rows, min(txn_date) AS from_dt, max(txn_date) AS to_dt,
       sum(is_laundering) AS positives,
       round(100.0*sum(is_laundering)/count(*),4) AS pos_pct
FROM features GROUP BY 1 ORDER BY 1 DESC
""").fetchdf().to_string(index=False))

print("\n--- sanity: do the rule-derived features separate the classes at all? ---")
print(con.execute("""
SELECT is_laundering,
  round(avg(s_recv_7d),2)   AS avg_distinct_recv_7d,
  round(avg(s_band10k_7d),3) AS avg_band10k_7d,
  round(avg(s_small_30d),2)  AS avg_small_30d,
  round(avg(s_xborder_ratio_30d),3) AS avg_xborder_ratio,
  round(avg(coalesce(s_passthru_ratio_2d,0)),3) AS avg_passthru_2d,
  round(avg(amount),2)      AS avg_amount
FROM features GROUP BY 1 ORDER BY 1
""").fetchdf().to_string(index=False))
con.close()
