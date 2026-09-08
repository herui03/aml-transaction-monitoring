"""Extracts for the Tableau workbook. Tableau reads CSV; the .twbx is built by
hand from these (see tableau/BUILD_GUIDE.md) - a .twbx is a binary only Tableau
Desktop can author, so the data and the spec are the deliverable."""
import duckdb, numpy as np, pandas as pd, pickle

con = duckdb.connect("data/processed/aml.duckdb", read_only=True)
DROP={"txn_id","ts","txn_date","is_laundering","laundering_type","sender"}
cols=[c for c in con.execute("DESCRIBE features").fetchdf()["column_name"] if c not in DROP]
tr = con.execute(f"""SELECT {','.join(cols)} FROM features
  WHERE txn_date <= DATE '2023-05-31' AND (is_laundering = 1 OR hash(txn_id) % 10 = 0)
  ORDER BY txn_id""").fetchdf()
te = con.execute(f"""SELECT txn_id, {','.join(cols)}, is_laundering, laundering_type
  FROM features WHERE txn_date > DATE '2023-05-31' ORDER BY txn_id""").fetchdf()
y   = te.pop("is_laundering").values
lt  = te.pop("laundering_type").values
ids = te.pop("txn_id").values
for df in (tr, te): df["pay_type"]=df["pay_type"].astype("category")
te["pay_type"]=te["pay_type"].cat.set_categories(tr["pay_type"].cat.categories)
X = te[tr.columns]

gb = pickle.load(open("outputs/model_gb.pkl","rb"))
p_gb = gb.predict_proba(X)[:,1]
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
def prep(df):
    d = pd.get_dummies(df, columns=["pay_type"], dummy_na=False)
    return d.replace([np.inf,-np.inf], np.nan)
Atr, Ate = prep(tr), prep(X)
Ate = Ate.reindex(columns=Atr.columns, fill_value=0)
med = Atr.median(); Atr, Ate = Atr.fillna(med), Ate.fillna(med)
sc = StandardScaler().fit(Atr)
ytr = con.execute("""SELECT is_laundering FROM features
  WHERE txn_date <= DATE '2023-05-31' AND (is_laundering = 1 OR hash(txn_id) % 10 = 0)
  ORDER BY txn_id""").fetchdf()["is_laundering"].values
lr = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=42).fit(sc.transform(Atr), ytr)
p_lr = lr.predict_proba(sc.transform(Ate))[:,1]

CAP, TOT = 12600, int(y.sum())
# ---------- 1. cumulative gain curve ----------
def gain(score, name, jitter=None):
    s = score if jitter is None else jitter
    order = np.argsort(-s)
    cum = np.cumsum(y[order])
    xs = np.unique(np.concatenate([np.arange(0, 25001, 50), [CAP]]))
    return pd.DataFrame({"approach": name, "alerts_investigated": xs,
                         "laundering_caught": cum[np.clip(xs-1, 0, len(cum)-1)] * (xs>0),
                         "pct_of_all_laundering": (cum[np.clip(xs-1,0,len(cum)-1)]*(xs>0))/TOT*100})
rng = np.random.default_rng(42)
frames = [gain(None, "Random ordering", jitter=rng.random(len(y))),
          gain(X["amount"].values, "Amount-only ranking"),
          gain(p_lr, "Logistic regression"),
          gain(p_gb, "Gradient-boosted model")]

# Rule engine: it cannot rank, so investigating x of its N alerts yields a
# straight line in expectation. That straight line IS the argument.
r04 = con.execute("""
WITH small AS (SELECT txn_id, sender, ts, laundering_type FROM txn
               WHERE amount < 7000 AND txn_date > DATE '2023-05-31'),
w AS (SELECT *, count(*) OVER (PARTITION BY sender ORDER BY ts
        RANGE BETWEEN INTERVAL 90 DAY PRECEDING AND CURRENT ROW) AS c FROM small),
peak AS (SELECT sender, ts AS pts, c, row_number() OVER (PARTITION BY sender ORDER BY c DESC, ts) rn FROM w),
fired AS (SELECT sender, pts FROM peak WHERE rn=1 AND c>=15)
SELECT count(*) AS alerts, sum(CASE WHEN s.laundering_type='Smurfing' THEN 1 ELSE 0 END) AS tp
FROM small s JOIN fired f USING (sender)
WHERE s.ts > f.pts - INTERVAL 90 DAY AND s.ts <= f.pts""").fetchone()
r_alerts, r_tp = r04
xs = np.unique(np.concatenate([np.arange(0, 25001, 50), [CAP]]))
frames.append(pd.DataFrame({"approach": "Rule engine (cannot rank)",
    "alerts_investigated": xs,
    "laundering_caught": (xs / r_alerts * r_tp).round(1),
    "pct_of_all_laundering": (xs / r_alerts * r_tp) / TOT * 100}))
pd.concat(frames).to_csv("tableau/gain_curve.csv", index=False)
print(f"gain_curve.csv          | rule engine on test: {r_alerts:,} alerts, {r_tp:,} TP")

# ---------- 2. calibration ----------
bins = [0,.5,.9,.99,.999,1.0]
lab  = ["0.00–0.50","0.50–0.90","0.90–0.99","0.99–0.999","0.999–1.00"]
c = pd.DataFrame({"bucket": pd.cut(p_gb, bins=bins, labels=lab, include_lowest=True),
                  "y": y, "score": p_gb}).groupby("bucket", observed=False).agg(
        transactions=("y","size"), laundering=("y","sum"), model_says_pct=("score","median"))
c["actual_pct"] = (100*c.laundering/c.transactions).round(3)
c["model_says_pct"] = (100*c.model_says_pct).round(2)
c.reset_index().to_csv("tableau/calibration.csv", index=False)
print("calibration.csv")

# ---------- 3. alert queue with reasons ----------
sv = np.load("outputs/shap_values.npy")
Xq = pd.read_parquet("outputs/shap_queue_X.parquet")
topk = np.argsort(-p_gb)[:CAP]
HUMAN = {"r_txn_7d":"beneficiary payment count (7d)","r_senders_30d":"beneficiary distinct senders (30d)",
 "r_senders_7d":"beneficiary distinct senders (7d)","s_txn_30d":"sender velocity (30d)",
 "s_txn_1d":"sender velocity (24h)","s_txn_7d":"sender velocity (7d)",
 "s_recv_30d":"sender fan-out (30d)","s_recv_7d":"sender fan-out (7d)","s_recv_1d":"sender fan-out (24h)",
 "log_amount":"transaction amount","amount":"transaction amount","s_small_30d":"sub-7,000 density (30d)",
 "s_passthru_ratio_7d":"pass-through ratio (7d)","s_passthru_ratio_2d":"pass-through ratio (48h)",
 "s_xborder_ratio_30d":"cross-border share (30d)","s_account_age_days":"account age",
 "r_amt_sum_7d":"beneficiary inflow (7d)","s_amt_sum_7d":"sender outflow (7d)","pay_type":"payment channel"}
drv = Xq.columns[np.argmax(sv, axis=1)]
q = pd.DataFrame({
    "rank": np.arange(1, CAP+1),
    "txn_id": ids[topk], "risk_score": p_gb[topk].round(4),
    "primary_driver": [HUMAN.get(d, d) for d in drv],
    "driver_contribution": sv[np.arange(CAP), np.argmax(sv, axis=1)].round(3),
    "amount": X["amount"].values[topk].round(2),
    "outcome": np.where(y[topk]==1, "True positive", "False positive"),
    "actual_typology": lt[topk],
})
q.to_csv("tableau/alert_queue.csv", index=False)
print(f"alert_queue.csv         | {len(q):,} alerts, {int((q.outcome=='True positive').sum()):,} true positives")

# ---------- 4. recall at capacity ----------
def rec(s): return round(100*y[np.argsort(-s)[:CAP]].sum()/TOT, 2)
pd.DataFrame({
 "approach": ["Rule engine (cannot rank)","Random ordering","Amount-only ranking","Logistic regression","Gradient-boosted model"],
 "recall_at_capacity_pct": [round(100*(CAP/r_alerts*r_tp)/TOT,2), rec(rng.random(len(y))), rec(X["amount"].values), rec(p_lr), rec(p_gb)],
}).to_csv("tableau/capacity_summary.csv", index=False)
print("capacity_summary.csv")
print(f"\ncapacity K={CAP:,} | test positives={TOT:,} | ceiling={100*min(CAP,TOT)/CAP:.1f}% precision")
