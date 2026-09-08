import duckdb
con = duckdb.connect("data/processed/aml.duckdb", read_only=True)
print("="*84)
print("How many transactions actually drive the 4.65x mean inflation?")
print("="*84)
# Trim the top-N laundering amounts and watch the mean collapse toward the median.
for n in [0, 1, 5, 10, 50, 100, 500]:
    r = con.execute(f"""
      WITH l AS (
        SELECT amount, row_number() OVER (ORDER BY amount DESC) AS rk
        FROM features WHERE is_laundering=1
      )
      SELECT round(avg(amount),2) AS mean_after_trim, count(*) AS n_left
      FROM l WHERE rk > {n}
    """).fetchone()
    print(f"  drop top {n:>4} laundering txns -> mean = {r[0]:>12,.2f}  (n={r[1]:,})")
print(f"\n  normal mean     = 8,729.88")
print(f"  laundering median = 5,322.79")

print("\n" + "="*84)
print("Share of the laundering total carried by the tail")
print("="*84)
print(con.execute("""
  WITH l AS (SELECT amount, row_number() OVER (ORDER BY amount DESC) AS rk,
                    sum(amount) OVER () AS tot, count(*) OVER () AS n
             FROM features WHERE is_laundering=1)
  SELECT 'top 1 txn' AS slice, round(100.0*sum(amount)/max(tot),2) AS pct_of_total FROM l WHERE rk<=1
  UNION ALL SELECT 'top 10',   round(100.0*sum(amount)/max(tot),2) FROM l WHERE rk<=10
  UNION ALL SELECT 'top 50',   round(100.0*sum(amount)/max(tot),2) FROM l WHERE rk<=50
  UNION ALL SELECT 'top 99 (1%)', round(100.0*sum(amount)/max(tot),2) FROM l WHERE rk<=99
  UNION ALL SELECT 'top 987 (10%)', round(100.0*sum(amount)/max(tot),2) FROM l WHERE rk<=987
""").fetchdf().to_string(index=False))
