"""Dual-grain evaluation. Scores a rule at BOTH transaction and account grain,
so the gap between them is always visible rather than silently chosen."""
import duckdb

class Evaluator:
    def __init__(self, db="data/processed/aml.duckdb"):
        self.con = duckdb.connect(db, read_only=True)
        self.n_senders = self.con.execute("SELECT count(DISTINCT sender) FROM txn").fetchone()[0]
        self.n_txns    = self.con.execute("SELECT count(*) FROM txn").fetchone()[0]

    def _lab(self, types):
        return "(" + ",".join(f"'{t}'" for t in types) + ")"

    def score(self, alert_sql, params, label_types):
        L = self._lab(label_types)
        self.con.execute("DROP TABLE IF EXISTS _alerts")
        self.con.execute(f"CREATE TEMP TABLE _alerts AS {alert_sql}", params)

        # --- transaction grain: did we alert the transactions that are labelled? ---
        txn = self.con.execute(f"""
          SELECT count(*) AS alerted,
                 sum(CASE WHEN laundering_type IN {L} THEN 1 ELSE 0 END) AS tp
          FROM _alerts""").fetchone()
        n_lab = self.con.execute(f"SELECT count(*) FROM txn WHERE laundering_type IN {L}").fetchone()[0]

        # --- account grain, two flavours ---
        acct = self.con.execute(f"""
          WITH flagged AS (SELECT DISTINCT sender FROM _alerts),
               guilty  AS (SELECT DISTINCT sender FROM txn WHERE laundering_type IN {L}),
               honest  AS (SELECT DISTINCT sender FROM _alerts WHERE laundering_type IN {L})
          SELECT (SELECT count(*) FROM flagged) AS flagged,
                 (SELECT count(*) FROM guilty)  AS guilty,
                 (SELECT count(*) FROM flagged f JOIN guilty g USING(sender)) AS tp_lenient,
                 (SELECT count(*) FROM honest)  AS tp_strict
        """).fetchone()

        alerted, tp_txn = txn
        flagged, guilty, tp_len, tp_str = acct
        pct = lambda a,b: round(100*a/b, 4) if b else 0.0
        return {
          "txn_alerted": alerted, "txn_tp": tp_txn, "txn_labelled": n_lab,
          "txn_precision_pct": pct(tp_txn, alerted), "txn_recall_pct": pct(tp_txn, n_lab),
          "acct_flagged": flagged, "acct_guilty": guilty,
          "acct_tp_lenient": tp_len, "acct_tp_strict": tp_str,
          "acct_prec_lenient_pct": pct(tp_len, flagged),
          "acct_prec_strict_pct":  pct(tp_str, flagged),
          "coincidence_rate_pct": pct(tp_len - tp_str, tp_len),
        }

if __name__ == "__main__":
    ev = Evaluator()
    sql = open("sql/rules/r01_structuring.sql").read()
    r = ev.score(sql, {"threshold":10000,"band_lo":0.8,"window_days":7,"min_count":5},
                 ["Structuring","Smurfing"])
    print("="*78); print("R-01 @ original params - CORRECTED, dual grain"); print("="*78)
    for k,v in r.items(): print(f"  {k:<26}: {v:>12,}")
