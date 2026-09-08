"""Rule vs model, on BOTH bases - because the denominator decides the story.

(a) vs all laundering: the operationally honest comparison (same budget, same
    target) but structurally unkind to R-04, which targets one typology.
(b) vs R-04's OWN target (Smurfing only): the comparison R-04 cannot complain
    about. If the model still wins there, the finding survives the caveat.
"""
import duckdb, numpy as np, pandas as pd, pickle
con = duckdb.connect("data/processed/aml.duckdb", read_only=True)
DROP={"txn_id","ts","txn_date","is_laundering","laundering_type","sender"}
cols=[c for c in con.execute("DESCRIBE features").fetchdf()["column_name"] if c not in DROP]
tr = con.execute(f"""SELECT {','.join(cols)} FROM features
  WHERE txn_date <= DATE '2023-05-31' AND (is_laundering = 1 OR hash(txn_id) % 10 = 0)
  ORDER BY txn_id""").fetchdf()
te = con.execute(f"""SELECT {','.join(cols)}, laundering_type FROM features
  WHERE txn_date > DATE '2023-05-31' ORDER BY txn_id""").fetchdf()
lt = te.pop("laundering_type").values
for df in (tr, te): df["pay_type"]=df["pay_type"].astype("category")
te["pay_type"]=te["pay_type"].cat.set_categories(tr["pay_type"].cat.categories)
gb = pickle.load(open("outputs/model_gb.pkl","rb"))
p = gb.predict_proba(te[tr.columns])[:,1]

CAP = 12600
R_ALERTS, R_TP = 1115642, 163          # R-04 on the test period (measured)
y_all   = (lt != 'Normal_Cash_Deposits') & ~pd.Series(lt).str.startswith('Normal').values
y_smurf = (lt == 'Smurfing')
top = np.argsort(-p)[:CAP]

rows = []
for name, y in [("all laundering typologies", y_all), ("Smurfing only (R-04's own target)", y_smurf)]:
    tot = int(y.sum())
    rule_tp  = CAP / R_ALERTS * (R_TP if "Smurf" in name else R_TP)   # R-04 only ever catches Smurfing
    model_tp = int(y[top].sum())
    rows.append({"basis": name, "positives_in_test": tot,
                 "rule_expected_tp_at_K": round(rule_tp, 2),
                 "rule_recall_pct": round(100*rule_tp/tot, 3),
                 "model_tp_at_K": model_tp,
                 "model_recall_pct": round(100*model_tp/tot, 2),
                 "model_over_rule": f"{(model_tp/rule_tp):,.0f}x"})
d = pd.DataFrame(rows)
print("="*118)
print(f"RULE ENGINE vs MODEL - same budget (K={CAP:,}), two denominators")
print(f"R-04 on the test period: {R_ALERTS:,} alerts raised, {R_TP} true positives inside them")
print("="*118)
print(d.to_string(index=False))
d.to_csv("outputs/rule_vs_model_fair.csv", index=False)
