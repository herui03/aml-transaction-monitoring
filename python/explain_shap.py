"""SHAP attribution for the alert queue.

WHY only the alerts: an MLRO reads the reason for the alerts an analyst
escalates, not for the 2.4M transactions the model silently cleared. We explain
the top-K by score - the queue that actually reaches a human.

WHY this is not optional: a gradient-boosted score is not a filing basis. An STR
needs a narrative a human signs their name to. Attribution is what converts
"0.97" into something an MLRO can act on or reject.
"""
import duckdb, numpy as np, pandas as pd, pickle, shap
pd.set_option("display.width", 200)

con = duckdb.connect("data/processed/aml.duckdb", read_only=True)
DROP = {"txn_id","ts","txn_date","is_laundering","laundering_type","sender"}
cols = [c for c in con.execute("DESCRIBE features").fetchdf()["column_name"] if c not in DROP]

train = con.execute(f"""SELECT {','.join(cols)}, is_laundering FROM features
   WHERE txn_date <= DATE '2023-05-31' AND (is_laundering = 1 OR hash(txn_id) % 10 = 0)
   ORDER BY txn_id""").fetchdf()
test = con.execute(f"""SELECT txn_id, {','.join(cols)}, is_laundering, laundering_type
   FROM features WHERE txn_date > DATE '2023-05-31' ORDER BY txn_id""").fetchdf()
train.pop("is_laundering")
yte = test.pop("is_laundering").values
lt  = test.pop("laundering_type").values
ids = test.pop("txn_id").values

for df in (train, test): df["pay_type"] = df["pay_type"].astype("category")
test["pay_type"] = test["pay_type"].cat.set_categories(train["pay_type"].cat.categories)
X = test[train.columns]

gb = pickle.load(open("outputs/model_gb.pkl","rb"))
p = gb.predict_proba(X)[:,1]

K = 12600
topk = np.argsort(-p)[:K]
Xq = X.iloc[topk]                       # the alert queue
print(f"alert queue: {len(Xq):,} transactions | true positives in queue: {int(yte[topk].sum()):,}")

# TreeExplainer needs numeric input. sklearn maps a pandas categorical to codes
# 0..n-1 internally in category order, so passing .cat.codes hands the explainer
# exactly the representation the fitted trees split on - the model is untouched.
Xq_num = Xq.copy()
Xq_num["pay_type"] = Xq_num["pay_type"].cat.codes.astype("float64")
expl = shap.TreeExplainer(gb)
sv = expl.shap_values(Xq_num, check_additivity=False)
if isinstance(sv, list): sv = sv[1]
if sv.ndim == 3: sv = sv[:, :, 1]
print(f"shap values: {sv.shape}")

imp = pd.DataFrame({
    "feature": train.columns,
    "mean_abs_shap": np.abs(sv).mean(axis=0),
}).sort_values("mean_abs_shap", ascending=False).reset_index(drop=True)
imp["share_pct"] = (100*imp.mean_abs_shap/imp.mean_abs_shap.sum()).round(2)
imp["cumulative_pct"] = imp.share_pct.cumsum().round(2)

print("\n" + "="*88)
print("GLOBAL ATTRIBUTION - what drives the alert queue (mean |SHAP|)")
print("="*88)
print(imp.head(15).to_string(index=False))

print("\n" + "="*88)
print("RED-FLAG CHECK - is the model leaning on anything it has no business using?")
print("="*88)
SUSPECT = ["hour_of_day","day_of_week","is_round_100","is_round_1000","s_account_age_days"]
print(imp[imp.feature.isin(SUSPECT)].to_string(index=False))

np.save("outputs/shap_values.npy", sv)
Xq_num.to_parquet("outputs/shap_queue_X.parquet")
imp.to_csv("outputs/shap_global_importance.csv", index=False)
pd.DataFrame({"txn_id": ids[topk], "score": p[topk], "is_laundering": yte[topk],
              "laundering_type": lt[topk]}).to_parquet("outputs/shap_queue_meta.parquet")
print("\nsaved: outputs/shap_values.npy, shap_global_importance.csv, shap_queue_*.parquet")
