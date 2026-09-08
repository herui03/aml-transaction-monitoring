import duckdb
con = duckdb.connect("data/processed/aml.duckdb", read_only=True)
print("="*96)
print("SANITY CHECK v2 - MEDIANS (robust to outliers) vs the MEANS I reported")
print("="*96)
print(con.execute("""
SELECT is_laundering AS lbl,
  round(median(s_recv_7d),2)            AS med_recv_7d,
  round(median(s_band10k_7d),2)         AS med_band10k_7d,
  round(median(s_small_30d),2)          AS med_small_30d,
  round(median(s_xborder_ratio_30d),3)  AS med_xborder_ratio,
  round(median(coalesce(s_passthru_ratio_2d,0)),3) AS med_passthru_2d,
  round(median(amount),2)               AS med_amount
FROM features GROUP BY 1 ORDER BY 1
""").fetchdf().to_string(index=False))

print("\n--- was the passthru MEAN distorted by outliers? ---")
print(con.execute("""
SELECT is_laundering AS lbl,
  round(avg(coalesce(s_passthru_ratio_2d,0)),2)               AS mean,
  round(median(coalesce(s_passthru_ratio_2d,0)),3)            AS median,
  round(quantile_cont(coalesce(s_passthru_ratio_2d,0),0.99),1) AS p99,
  round(max(coalesce(s_passthru_ratio_2d,0)),1)               AS max
FROM features GROUP BY 1 ORDER BY 1
""").fetchdf().to_string(index=False))

print("\n" + "="*96)
print("The honest test of separability: AMOUNT overlap between the two classes")
print("="*96)
print(con.execute("""
SELECT is_laundering AS lbl, count(*) AS n,
  round(quantile_cont(amount,0.10),0) AS p10, round(quantile_cont(amount,0.25),0) AS p25,
  round(quantile_cont(amount,0.50),0) AS p50, round(quantile_cont(amount,0.75),0) AS p75,
  round(quantile_cont(amount,0.90),0) AS p90, round(quantile_cont(amount,0.99),0) AS p99
FROM features GROUP BY 1 ORDER BY 1
""").fetchdf().to_string(index=False))
