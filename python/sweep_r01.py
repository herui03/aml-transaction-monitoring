import duckdb, pandas as pd, itertools, time
con = duckdb.connect("data/processed/aml.duckdb", read_only=True)

gt = set(con.execute("""
  SELECT DISTINCT sender FROM txn WHERE laundering_type IN ('Structuring','Smurfing')
""").fetchdf()["sender"].tolist())
n_senders_total = con.execute("SELECT count(DISTINCT sender) FROM txn").fetchone()[0]

# For a given (threshold, window) compute each sender's PEAK count once,
# then evaluate every min_count off that single result. 18 window passes, not 54.
PEAK = """
WITH banded AS (
  SELECT sender, ts FROM txn
  WHERE amount >= ($threshold * 0.8) AND amount < $threshold
), windowed AS (
  SELECT sender, count(*) OVER (
           PARTITION BY sender ORDER BY ts
           RANGE BETWEEN INTERVAL ($window_days) DAY PRECEDING AND CURRENT ROW
         ) AS c
  FROM banded
)
SELECT sender, max(c) AS peak FROM windowed GROUP BY sender
"""

rows = []
t0 = time.time()
for T, W in itertools.product([5000, 7500, 10000, 12500, 15000, 20000], [7, 14, 30]):
    df = con.execute(PEAK, {"threshold": T, "window_days": W}).fetchdf()
    for N in [3, 4, 5, 6, 8]:
        s = set(df.loc[df["peak"] >= N, "sender"].tolist())
        tp = len(s & gt)
        rows.append({
            "threshold": T, "window_d": W, "min_count": N,
            "alerts": len(s),
            "true_pos": tp,
            "recall_pct": round(100*tp/len(gt), 2),
            "precision_pct": round(100*tp/len(s), 3) if s else 0.0,
            "pct_book_flagged": round(100*len(s)/n_senders_total, 2),
        })
    print(f"  T={T:>6,} W={W:>2}d done ({time.time()-t0:.0f}s)")

res = pd.DataFrame(rows)
res.to_csv("outputs/r01_sweep.csv", index=False)

print("\n" + "="*95)
print("R-01 PARAMETER SWEEP - 90 combinations")
print("="*95)
print(res.to_string(index=False))

print("\n" + "="*95)
print("BEST BY PRECISION (top 10)")
print("="*95)
print(res.sort_values("precision_pct", ascending=False).head(10).to_string(index=False))

print("\n" + "="*95)
print("Your original setting, for reference")
print("="*95)
print(res[(res.threshold==10000)&(res.window_d==7)&(res.min_count==5)].to_string(index=False))
