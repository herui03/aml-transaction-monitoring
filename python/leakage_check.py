import duckdb
con = duckdb.connect("data/processed/aml.duckdb", read_only=True)
def q(s): return con.execute(s).fetchdf()

print("="*88)
print("LEAKAGE CHECK - does the model just memorise known-bad SENDERS?")
print("="*88)
print(q("""
WITH tr AS (SELECT DISTINCT sender FROM txn WHERE txn_date <= DATE '2023-05-31' AND is_laundering=1),
     te AS (SELECT DISTINCT sender FROM txn WHERE txn_date >  DATE '2023-05-31' AND is_laundering=1)
SELECT (SELECT count(*) FROM te) AS test_guilty_senders,
       (SELECT count(*) FROM te JOIN tr USING(sender)) AS also_guilty_in_TRAIN,
       round(100.0*(SELECT count(*) FROM te JOIN tr USING(sender))/(SELECT count(*) FROM te),2) AS pct_already_known
""").T.rename(columns={0:"value"}).to_string())

print("\n--- and how many test POSITIVE TRANSACTIONS come from an already-known-bad sender? ---")
print(q("""
WITH tr AS (SELECT DISTINCT sender FROM txn WHERE txn_date <= DATE '2023-05-31' AND is_laundering=1)
SELECT count(*) AS test_positive_txns,
       sum(CASE WHEN tr.sender IS NOT NULL THEN 1 ELSE 0 END) AS from_known_bad_sender,
       round(100.0*sum(CASE WHEN tr.sender IS NOT NULL THEN 1 ELSE 0 END)/count(*),2) AS pct
FROM txn t LEFT JOIN tr ON tr.sender=t.sender
WHERE t.txn_date > DATE '2023-05-31' AND t.is_laundering=1
""").T.rename(columns={0:"value"}).to_string())

print("\n--- how many test senders were NEVER seen in train at all? ---")
print(q("""
WITH tr AS (SELECT DISTINCT sender FROM txn WHERE txn_date <= DATE '2023-05-31')
SELECT count(DISTINCT t.sender) AS test_senders,
       count(DISTINCT CASE WHEN tr.sender IS NULL THEN t.sender END) AS never_seen_in_train
FROM txn t LEFT JOIN tr ON tr.sender=t.sender
WHERE t.txn_date > DATE '2023-05-31'
""").T.rename(columns={0:"value"}).to_string())
