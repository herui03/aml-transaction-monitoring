"""Discrimination is not calibration.
AUC says "can you rank?". Calibration says "does 0.97 mean 97%?".
A model can be excellent at the first and useless at the second, and MRM cares
about both - a score you cannot read as a probability cannot carry a threshold.
"""
import numpy as np, pandas as pd
from sklearn.calibration import calibration_curve
sv   = np.load("outputs/shap_values.npy")
X    = pd.read_parquet("outputs/shap_queue_X.parquet")
meta = pd.read_parquet("outputs/shap_queue_meta.parquet")

top_feat = X.columns[np.argmax(sv, axis=1)]
d = pd.DataFrame({"top_driver": top_feat, "score": meta.score.values,
                  "y": meta.is_laundering.values})

print("="*104)
print("Do alerts with the SAME score have the SAME chance of being real?")
print("="*104)
g = d.groupby("top_driver").agg(alerts=("y","size"), true_pos=("y","sum"),
        median_score=("score","median"), min_score=("score","min"), max_score=("score","max"))
g["actual_tp_rate_pct"] = (100*g.true_pos/g.alerts).round(1)
g["model_says_pct"] = (100*g.median_score).round(1)
g["gap"] = (g.model_says_pct - g.actual_tp_rate_pct).round(1)
print(g.sort_values("actual_tp_rate_pct", ascending=False).to_string())

print("\n" + "="*104)
print("CALIBRATION over the WHOLE test set (not just the queue)")
print("="*104)
p = np.load("outputs/p_gb.npy") if False else None
import duckdb, pickle
con = duckdb.connect("data/processed/aml.duckdb", read_only=True)
DROP={"txn_id","ts","txn_date","is_laundering","laundering_type","sender"}
cols=[c for c in con.execute("DESCRIBE features").fetchdf()["column_name"] if c not in DROP]
tr = con.execute(f"""SELECT {','.join(cols)} FROM features
  WHERE txn_date <= DATE '2023-05-31' AND (is_laundering = 1 OR hash(txn_id) % 10 = 0)
  ORDER BY txn_id""").fetchdf()
te = con.execute(f"""SELECT {','.join(cols)}, is_laundering FROM features
  WHERE txn_date > DATE '2023-05-31' ORDER BY txn_id""").fetchdf()
y = te.pop("is_laundering").values
for df in (tr, te): df["pay_type"]=df["pay_type"].astype("category")
te["pay_type"]=te["pay_type"].cat.set_categories(tr["pay_type"].cat.categories)
gb = pickle.load(open("outputs/model_gb.pkl","rb"))
p = gb.predict_proba(te[tr.columns])[:,1]

bins = [0,.5,.9,.99,.999,1.0]
b = pd.cut(p, bins=bins, include_lowest=True)
c = pd.DataFrame({"bin":b,"y":y}).groupby("bin", observed=False).agg(
        txns=("y","size"), true_pos=("y","sum"))
c["actual_pct"] = (100*c.true_pos/c.txns).round(3)
print(c.to_string())
print("\nIf the model were calibrated, 'actual_pct' would sit inside each bin's range.")
