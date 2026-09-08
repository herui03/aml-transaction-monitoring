"""Cold-start test: every feature is built from an account's own past, so an
account with little history should be harder to score. Does the evidence agree?
Method: rank the whole test set once (as production would), take the top-K, then
ask which history-depth buckets the CAUGHT vs MISSED positives fall into."""
import duckdb, numpy as np, pandas as pd, pickle
con = duckdb.connect("data/processed/aml.duckdb", read_only=True)
DROP={"txn_id","ts","txn_date","is_laundering","laundering_type","sender"}
cols=[c for c in con.execute("DESCRIBE features").fetchdf()["column_name"] if c not in DROP]

train = con.execute(f"""SELECT {','.join(cols)}, is_laundering FROM features
  WHERE txn_date <= DATE '2023-05-31' AND (is_laundering = 1 OR hash(txn_id) % 10 = 0)
     ORDER BY txn_id""").fetchdf()
test  = con.execute(f"""SELECT {','.join(cols)}, is_laundering, s_account_age_days AS age, s_txn_30d AS hist
  FROM features WHERE txn_date > DATE '2023-05-31'
     ORDER BY txn_id""").fetchdf()
ytr = train.pop("is_laundering").values
yte = test.pop("is_laundering").values
age, hist = test.pop("age").values, test.pop("hist").values

for df in (train, test): df["pay_type"]=df["pay_type"].astype("category")
test["pay_type"]=test["pay_type"].cat.set_categories(train["pay_type"].cat.categories)
gb = pickle.load(open("outputs/model_gb.pkl","rb"))
p = gb.predict_proba(test[train.columns])[:,1]

K=12600
caught = np.zeros(len(yte), bool); caught[np.argsort(-p)[:K]] = True

def bucket_report(vals, edges, labels, name):
    b = pd.cut(vals, bins=edges, labels=labels, include_lowest=True)
    df = pd.DataFrame({"bucket":b, "y":yte, "caught":caught, "score":p})
    g = df[df.y==1].groupby("bucket", observed=False).agg(
            positives=("y","size"), caught_in_topK=("caught","sum"),
            median_score=("score","median"))
    g["recall_pct"] = (100*g.caught_in_topK/g.positives).round(2)
    g["pct_of_all_positives"] = (100*g.positives/int(yte.sum())).round(2)
    vol = df.groupby("bucket", observed=False).size().rename("test_txns")
    out = vol.to_frame().join(g)
    print("\n"+"="*104); print(name); print("="*104)
    print(out.to_string())
    return out

a = bucket_report(age, [-1,7,30,90,180,10**6],
      ["0-7d (new)","8-30d","31-90d","91-180d",">180d (established)"],
      "COLD START by ACCOUNT AGE  - days since the sender's first-ever transaction")
h = bucket_report(hist, [-1,1,3,10,30,10**6],
      ["<=1 txn (no history)","2-3","4-10","11-30",">30 (rich history)"],
      "COLD START by HISTORY DEPTH - sender's transaction count in the prior 30 days")
a.to_csv("outputs/coldstart_by_age.csv"); h.to_csv("outputs/coldstart_by_history.csv")
print(f"\noverall recall@{K:,} = {100*caught[yte==1].sum()/int(yte.sum()):.2f}%")
