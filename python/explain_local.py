"""Turn a score into a reason an MLRO can read, accept, or reject.

A gradient-boosted score is not a filing basis. This renders, per alert, the
features that pushed it up - the model's equivalent of the rule engine's
"trigger logic" field. That is the minimum an STR narrative needs.
"""
import numpy as np, pandas as pd
pd.set_option("display.width", 220)

sv   = np.load("outputs/shap_values.npy")
X    = pd.read_parquet("outputs/shap_queue_X.parquet")
meta = pd.read_parquet("outputs/shap_queue_meta.parquet")
imp  = pd.read_csv("outputs/shap_global_importance.csv")

print("="*100)
print("FULL ATTRIBUTION - every feature, including the ones the rules were built on")
print("="*100)
RULE_FEATS = {"s_band10k_7d":"R-01 structuring band", "s_band5k_7d":"R-01 band (5k)",
              "s_small_30d":"R-04 smurfing", "s_passthru_ratio_2d":"R-02 pass-through 2d",
              "s_passthru_ratio_7d":"R-02 pass-through 7d", "s_recv_30d":"R-03' fan-out",
              "is_round_1000":"R-03 round-number (retired)", "is_round_100":"R-03 roundness"}
imp["from_rule"] = imp.feature.map(RULE_FEATS).fillna("")
print(imp.to_string(index=False))

# ---- per-alert reason strings ----
HUMAN = {
 "r_txn_7d":"beneficiary received {v:.0f} payments in 7 days",
 "r_senders_30d":"beneficiary was paid by {v:.0f} distinct senders in 30 days",
 "r_senders_7d":"beneficiary was paid by {v:.0f} distinct senders in 7 days",
 "s_txn_30d":"sender made {v:.0f} transactions in 30 days",
 "s_txn_1d":"sender made {v:.0f} transactions in 24 hours",
 "s_txn_7d":"sender made {v:.0f} transactions in 7 days",
 "s_recv_30d":"sender paid {v:.0f} distinct beneficiaries in 30 days",
 "s_recv_7d":"sender paid {v:.0f} distinct beneficiaries in 7 days",
 "s_recv_1d":"sender paid {v:.0f} distinct beneficiaries in 24 hours",
 "log_amount":"transaction amount",
 "amount":"transaction amount {v:,.2f}",
 "s_small_30d":"sender made {v:.0f} sub-7,000 transactions in 30 days",
 "s_band10k_7d":"sender made {v:.0f} transactions in the 8,000-9,999 band in 7 days",
 "s_passthru_ratio_7d":"7-day outflow/inflow ratio {v:.2f}",
 "s_passthru_ratio_2d":"48h outflow/inflow ratio {v:.2f}",
 "s_xborder_ratio_30d":"{v:.0%} of sender's 30-day activity is cross-border",
 "is_xborder":"cross-border leg",
 "s_account_age_days":"sender account is {v:.0f} days old",
 "r_amt_sum_7d":"beneficiary received {v:,.0f} in 7 days",
 "s_amt_sum_7d":"sender sent {v:,.0f} in 7 days",
 "s_amt_zscore_7d":"amount is {v:.1f} SD from the sender's 7-day norm",
 "ccy_mismatch":"payment and receipt currencies differ",
 "pay_type":"payment channel",
 "hour_of_day":"time of day",
}
def reason(i, n=4):
    row, s = X.iloc[i], sv[i]
    top = np.argsort(-s)[:n]                      # only features that PUSHED IT UP
    out = []
    for j in top:
        if s[j] <= 0: continue
        f = X.columns[j]
        t = HUMAN.get(f, f).format(v=row.iloc[j]) if "{v" in HUMAN.get(f, "") else HUMAN.get(f, f)
        out.append(f"{t} (+{s[j]:.2f})")
    return "; ".join(out)

print("\n" + "="*100)
print("SAMPLE ALERT NARRATIVES - what an MLRO would actually read")
print("="*100)
tp = np.where(meta.is_laundering.values == 1)[0][:3]
fp = np.where(meta.is_laundering.values == 0)[0][:3]
for label, idx in [("TRUE POSITIVE", tp), ("FALSE POSITIVE", fp)]:
    for i in idx:
        m = meta.iloc[i]
        print(f"\n[{label}] txn {m.txn_id} | score {m.score:.4f} | actual: {m.laundering_type}")
        print(f"  why: {reason(i)}")

# does the queue's reasoning differ between real and false alerts?
print("\n" + "="*100)
print("Which feature is the TOP driver, for true vs false alerts in the queue?")
print("="*100)
top_feat = X.columns[np.argmax(sv, axis=1)]
d = pd.crosstab(pd.Series(top_feat, name="top_driver"),
                pd.Series(np.where(meta.is_laundering.values==1,"true positive","false positive"),
                          name="outcome"))
d["tp_rate_pct"] = (100*d.get("true positive",0)/d.sum(axis=1)).round(1)
print(d.sort_values("tp_rate_pct", ascending=False).to_string())
