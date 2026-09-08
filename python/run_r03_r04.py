import duckdb, pandas as pd, itertools
con = duckdb.connect("data/processed/aml.duckdb", read_only=True)
N_SEND = con.execute("SELECT count(DISTINCT sender) FROM txn").fetchone()[0]

def gt_for(types):
    q = "SELECT DISTINCT sender FROM txn WHERE laundering_type IN ({})".format(
        ",".join(f"'{t}'" for t in types))
    return set(con.execute(q).fetchdf()["sender"].tolist())

def score(flagged, gt, base=None):
    tp = len(flagged & gt)
    prec = 100*tp/len(flagged) if flagged else 0
    rec  = 100*tp/len(gt) if gt else 0
    base_rate = 100*len(gt)/N_SEND
    return dict(alerts=len(flagged), true_pos=tp,
                recall_pct=round(rec,2), precision_pct=round(prec,3),
                base_rate_pct=round(base_rate,3),
                lift_vs_random=round(prec/base_rate,1) if base_rate else 0)

# ---------- R-03' FAN-OUT : one sender -> many DISTINCT receivers in a window ----------
FANOUT = """
WITH w AS (
  SELECT sender, ts,
         count(DISTINCT receiver) OVER (
           PARTITION BY sender ORDER BY ts
           RANGE BETWEEN INTERVAL ($window_days) DAY PRECEDING AND CURRENT ROW
         ) AS distinct_recv
  FROM txn
)
SELECT sender FROM w GROUP BY sender HAVING max(distinct_recv) >= $min_recv
"""
gt_fan = gt_for(['Fan_Out','Layered_Fan_Out'])
print("="*90); print("R-03' FAN-OUT  (replaces the dead round-number rule)")
print(f"ground-truth fan-out senders: {len(gt_fan)}"); print("="*90)
rows=[]
for W, R in itertools.product([1,3,7,14],[5,8,12,20,30]):
    s = set(con.execute(FANOUT, {"window_days":W,"min_recv":R}).fetchdf()["sender"].tolist())
    rows.append({"window_d":W,"min_distinct_recv":R, **score(s, gt_fan)})
r3 = pd.DataFrame(rows); print(r3.to_string(index=False))

# ---------- R-04 SMURFING : many SMALL txns from one sender over a LONG window ----------
SMURF = """
WITH small AS (
  SELECT sender, ts FROM txn WHERE amount < $amt_cap
), w AS (
  SELECT sender, count(*) OVER (
           PARTITION BY sender ORDER BY ts
           RANGE BETWEEN INTERVAL ($window_days) DAY PRECEDING AND CURRENT ROW
         ) AS c
  FROM small
)
SELECT sender FROM w GROUP BY sender HAVING max(c) >= $min_count
"""
gt_smurf = gt_for(['Smurfing'])
print("\n"+"="*90); print("R-04 SMURFING  (month-scale window - the controlled contrast to R-01)")
print(f"ground-truth smurfing senders: {len(gt_smurf)}"); print("="*90)
rows=[]
for CAP, W, N in itertools.product([5000,7000],[30,60,90],[10,15,20,30]):
    s = set(con.execute(SMURF, {"amt_cap":CAP,"window_days":W,"min_count":N}).fetchdf()["sender"].tolist())
    rows.append({"amt_cap":CAP,"window_d":W,"min_count":N, **score(s, gt_smurf)})
r4 = pd.DataFrame(rows); print(r4.to_string(index=False))

r3.to_csv("outputs/r03_fanout_sweep.csv", index=False)
r4.to_csv("outputs/r04_smurfing_sweep.csv", index=False)

print("\n"+"="*90); print("BEST OF EACH - by lift over random"); print("="*90)
print("R-03' fan-out :"); print(r3.sort_values("lift_vs_random",ascending=False).head(3).to_string(index=False))
print("\nR-04 smurfing:"); print(r4.sort_values("lift_vs_random",ascending=False).head(3).to_string(index=False))
