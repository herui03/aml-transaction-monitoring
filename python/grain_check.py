import duckdb
con = duckdb.connect("data/processed/aml.duckdb", read_only=True)

# The transactions that ACTUALLY trigger R-01 for each sender, at original params.
TRIG = """
WITH banded AS (
  SELECT txn_id, sender, ts, amount, laundering_type
  FROM txn WHERE amount >= 8000 AND amount < 10000
), w AS (
  SELECT *, count(*) OVER (PARTITION BY sender ORDER BY ts
             RANGE BETWEEN INTERVAL 7 DAY PRECEDING AND CURRENT ROW) AS c
  FROM banded
), fired AS (
  SELECT sender FROM w GROUP BY sender HAVING max(c) >= 5
)
SELECT b.* FROM banded b JOIN fired f USING (sender)
"""
con.execute(f"CREATE TEMP TABLE trig AS {TRIG}")

print("="*80)
print("Of the accounts R-01 flags, how many were flagged BECAUSE OF")
print("an actually-labelled laundering transaction?")
print("="*80)

print(con.execute("""
WITH guilty AS (
  SELECT DISTINCT sender FROM txn WHERE laundering_type IN ('Structuring','Smurfing')
),
flagged_guilty AS (              -- the 474 "true positives"
  SELECT DISTINCT t.sender FROM trig t JOIN guilty g USING (sender)
),
-- did ANY of the transactions that triggered the rule carry a laundering label?
honest_hits AS (
  SELECT DISTINCT sender FROM trig
  WHERE laundering_type IN ('Structuring','Smurfing')
)
SELECT
  (SELECT count(*) FROM flagged_guilty) AS true_positives_claimed,
  (SELECT count(*) FROM honest_hits)    AS flagged_for_the_RIGHT_reason,
  (SELECT count(*) FROM flagged_guilty) - (SELECT count(*) FROM honest_hits) AS coincidental_hits,
  round(100.0*(SELECT count(*) FROM honest_hits)/(SELECT count(*) FROM flagged_guilty),2) AS pct_honest
""").fetchdf().T.rename(columns={0:"value"}).to_string())

print("\n" + "="*80)
print("Transaction-level view: of the 9.5M txns, what did R-01 actually touch?")
print("="*80)
print(con.execute("""
SELECT
  (SELECT count(*) FROM trig)                                          AS txns_inside_flagged_accounts,
  (SELECT count(*) FROM trig WHERE laundering_type IN ('Structuring','Smurfing')) AS of_which_labelled,
  (SELECT count(*) FROM txn WHERE laundering_type IN ('Structuring','Smurfing'))  AS total_labelled_in_dataset
""").fetchdf().T.rename(columns={0:"value"}).to_string())

print("\n" + "="*80)
print("TRUE transaction-level precision/recall for R-01 @ original params")
print("="*80)
r = con.execute("""
SELECT
  count(*)                                                              AS alerted_txns,
  sum(CASE WHEN laundering_type IN ('Structuring','Smurfing') THEN 1 ELSE 0 END) AS correct_txns
FROM trig
""").fetchone()
total_lab = con.execute("SELECT count(*) FROM txn WHERE laundering_type IN ('Structuring','Smurfing')").fetchone()[0]
alerted, correct = r
print(f"alerted transactions      : {alerted:,}")
print(f"of which truly laundering : {correct:,}")
print(f"TXN-LEVEL precision       : {100*correct/alerted:.4f}%")
print(f"TXN-LEVEL recall          : {100*correct/total_lab:.2f}%")
