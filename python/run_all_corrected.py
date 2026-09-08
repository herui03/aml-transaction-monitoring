import sys; sys.path.insert(0,"python")
from evaluate import Evaluator
import pandas as pd
ev = Evaluator()

runs = [
  ("R-01 structuring (orig params)", "sql/rules/r01_structuring.sql",
   {"threshold":10000,"band_lo":0.8,"window_days":7,"min_count":5}, ["Structuring","Smurfing"]),
  ("R-01 structuring (best-precision params)", "sql/rules/r01_structuring.sql",
   {"threshold":5000,"band_lo":0.8,"window_days":30,"min_count":3}, ["Structuring","Smurfing"]),
  ("R-03' fan-out (best lift params)", "sql/rules/r03_fanout.sql",
   {"window_days":14,"min_recv":5}, ["Fan_Out","Layered_Fan_Out"]),
  ("R-04 smurfing (best lift params)", "sql/rules/r04_smurfing.sql",
   {"amt_cap":7000,"window_days":90,"min_count":15}, ["Smurfing"]),
]
rows=[]
for name, path, params, labels in runs:
    r = ev.score(open(path).read(), params, labels)
    r["rule"] = name
    rows.append(r); print(f"done: {name}")

df = pd.DataFrame(rows).set_index("rule")
df.to_csv("outputs/corrected_dual_grain.csv")

print("\n"+"="*104)
print("ALL RULES - CORRECTED TRANSACTION-GRAIN EVALUATION")
print("="*104)
print(df[["txn_alerted","txn_tp","txn_labelled","txn_precision_pct","txn_recall_pct"]].to_string())
print("\n"+"="*104)
print("ACCOUNT GRAIN - lenient (the flattering one) vs strict (the honest one)")
print("="*104)
print(df[["acct_flagged","acct_tp_lenient","acct_tp_strict",
          "acct_prec_lenient_pct","acct_prec_strict_pct","coincidence_rate_pct"]].to_string())
