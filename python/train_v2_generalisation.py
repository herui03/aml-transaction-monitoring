import duckdb, numpy as np, pandas as pd, time, pickle
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score, average_precision_score
RNG=42
con = duckdb.connect("data/processed/aml.duckdb", read_only=True)
DROP={"txn_id","ts","txn_date","is_laundering","laundering_type","sender"}
cols=[c for c in con.execute("DESCRIBE features").fetchdf()["column_name"] if c not in DROP]

# bring sender across so we can slice the test set by "was this account ever seen"
test = con.execute(f"""
  WITH tr_all AS (SELECT DISTINCT sender FROM txn WHERE txn_date <= DATE '2023-05-31'),
       tr_bad AS (SELECT DISTINCT sender FROM txn WHERE txn_date <= DATE '2023-05-31' AND is_laundering=1)
  SELECT f.{', f.'.join(cols)}, f.is_laundering,
         (a.sender IS NULL) AS sender_unseen,
         (b.sender IS NOT NULL) AS sender_known_bad
  FROM features f
  JOIN txn t USING (txn_id)
  LEFT JOIN tr_all a ON a.sender=t.sender
  LEFT JOIN tr_bad b ON b.sender=t.sender
  WHERE f.txn_date > DATE '2023-05-31'
     ORDER BY txn_id
""").fetchdf()
train = con.execute(f"""
  SELECT {','.join(cols)}, is_laundering FROM features
  WHERE txn_date <= DATE '2023-05-31' AND (is_laundering = 1 OR hash(txn_id) % 10 = 0)
     ORDER BY txn_id
""").fetchdf()

ytr = train.pop("is_laundering").values
yte = test.pop("is_laundering").values
unseen = test.pop("sender_unseen").values.astype(bool)
knownbad = test.pop("sender_known_bad").values.astype(bool)

for df in (train, test): df["pay_type"]=df["pay_type"].astype("category")
test["pay_type"]=test["pay_type"].cat.set_categories(train["pay_type"].cat.categories)
Xte = test[train.columns]

gb = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.1,
        categorical_features=[train.columns.get_loc("pay_type")],
        class_weight="balanced", random_state=RNG)
t0=time.time(); gb.fit(train, ytr); print(f"trained {time.time()-t0:.0f}s")
p = gb.predict_proba(Xte)[:,1]
pickle.dump(gb, open("outputs/model_gb.pkl","wb"))

def report(name, mask, k_scale=True):
    s, y = p[mask], yte[mask]
    if y.sum()==0: return None
    # scale the analyst budget to the size of the slice, so K stays 0.513% of volume
    K = max(1, int(round(12600 * mask.sum()/len(yte)))) if k_scale else 12600
    idx = np.argsort(-s)[:K]; tp = int(y[idx].sum())
    return dict(slice=name, txns=int(mask.sum()), positives=int(y.sum()), K=K, tp_at_K=tp,
                precision_at_K_pct=round(100*tp/K,3), recall_at_K_pct=round(100*tp/y.sum(),2),
                roc_auc=round(roc_auc_score(y,s),4), pr_auc=round(average_precision_score(y,s),4))

rows=[report("ALL test", np.ones(len(yte),bool)),
      report("senders NEVER seen in train  <- the real generalisation test", unseen),
      report("senders seen, but never flagged bad in train", (~unseen)&(~knownbad)),
      report("senders already known-bad in train (memorisable)", knownbad)]
df=pd.DataFrame([r for r in rows if r]).set_index("slice")
print("\n"+"="*118)
print("GENERALISATION BY SENDER FAMILIARITY  (K scaled to each slice's volume)")
print("="*118)
print(df.to_string())
df.to_csv("outputs/generalisation_check.csv")
