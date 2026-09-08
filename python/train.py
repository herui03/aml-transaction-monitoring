import duckdb, numpy as np, pandas as pd, time
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, average_precision_score

RNG = 42
con = duckdb.connect("data/processed/aml.duckdb", read_only=True)

DROP = {"txn_id","ts","txn_date","is_laundering","laundering_type"}
cols = [c for c in con.execute("DESCRIBE features").fetchdf()["column_name"] if c not in DROP]
CAT  = ["pay_type"]
NUM  = [c for c in cols if c not in CAT]

# ---- TEST = the full unseen future period. Never sampled. ----
test = con.execute(f"""
  SELECT {','.join(cols)}, is_laundering, laundering_type
  FROM features WHERE txn_date > DATE '2023-05-31'
     ORDER BY txn_id
""").fetchdf()

# ---- TRAIN: keep every positive, downsample negatives 1:100.
# Downsampling only the TRAIN negatives is safe: it changes the fitted intercept,
# not the RANKING, and every metric below is rank-based (precision@K, AUC).
train = con.execute(f"""
  SELECT {','.join(cols)}, is_laundering FROM features
  WHERE txn_date <= DATE '2023-05-31' AND (is_laundering = 1 OR hash(txn_id) % 10 = 0)
     ORDER BY txn_id
""").fetchdf()
print(f"train rows {len(train):,} (pos {int(train.is_laundering.sum()):,}) | "
      f"test rows {len(test):,} (pos {int(test.is_laundering.sum()):,})")

ytr, yte = train.pop("is_laundering").values, test["is_laundering"].values
lt = test.pop("laundering_type")

for df in (train, test):
    df["pay_type"] = df["pay_type"].astype("category")
cats = train["pay_type"].cat.categories
test["pay_type"] = test["pay_type"].cat.set_categories(cats)
Xtr_h = train.copy(); Xte_h = test[train.columns].copy()

# capacity: 84 test days x 10 analysts x 15 alerts/day
K = 12600
def prec_at_k(scores, y, k=K):
    idx = np.argsort(-scores)[:k]
    tp  = int(y[idx].sum())
    return dict(tp_at_k=tp,
                precision_at_k_pct=round(100*tp/k, 3),
                recall_at_k_pct=round(100*tp/int(y.sum()), 2))

results = {}

# ---------- BASELINE 0: random ----------
rs = np.random.default_rng(RNG).random(len(yte))
results["B0 random"] = prec_at_k(rs, yte)

# ---------- BASELINE 1: amount only (the naive baseline the model MUST beat) ----------
results["B1 amount-only"] = prec_at_k(test["amount"].values, yte)

# ---------- MODEL A: logistic regression ----------
def prep(df):
    X = pd.get_dummies(df, columns=["pay_type"], dummy_na=False)
    return X.replace([np.inf,-np.inf], np.nan)
Atr, Ate = prep(train), prep(test[train.columns])
Ate = Ate.reindex(columns=Atr.columns, fill_value=0)
med = Atr.median()
Atr, Ate = Atr.fillna(med), Ate.fillna(med)
sc = StandardScaler().fit(Atr)
t0=time.time()
lr = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=RNG)
lr.fit(sc.transform(Atr), ytr)
p_lr = lr.predict_proba(sc.transform(Ate))[:,1]
results["MA logistic-regression"] = prec_at_k(p_lr, yte)
print(f"logreg trained {time.time()-t0:.0f}s")

# ---------- MODEL B: gradient boosting ----------
t0=time.time()
gb = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.1, max_depth=None,
        categorical_features=[Xtr_h.columns.get_loc("pay_type")],
        class_weight="balanced", random_state=RNG)
gb.fit(Xtr_h, ytr)
p_gb = gb.predict_proba(Xte_h)[:,1]
results["MB gradient-boosting"] = prec_at_k(p_gb, yte)
print(f"hgb trained {time.time()-t0:.0f}s")

# ---------- report ----------
res = pd.DataFrame(results).T
res["roc_auc"] = [np.nan, roc_auc_score(yte, test["amount"].values), roc_auc_score(yte,p_lr), roc_auc_score(yte,p_gb)]
res["pr_auc"]  = [np.nan, average_precision_score(yte, test["amount"].values),
                  average_precision_score(yte,p_lr), average_precision_score(yte,p_gb)]
res = res.round(4)
print("\n"+"="*94)
print(f"PRECISION@K  -  K = {K:,} (84 test days x 10 analysts x 15 alerts/day)")
print(f"test positives = {int(yte.sum()):,}   perfect-model ceiling = {100*min(K,int(yte.sum()))/K:.1f}% precision")
print("="*94)
print(res.to_string())
res.to_csv("outputs/model_results.csv")
np.save("outputs/p_gb.npy", p_gb); np.save("outputs/y_test.npy", yte)
test[["amount"]].assign(lt=lt.values).to_parquet("outputs/test_meta.parquet")
