import duckdb
con = duckdb.connect()
con.execute("CREATE VIEW t AS SELECT * FROM read_csv_auto('data/raw/SAML-D.csv', header=true)")
def q(s): return con.execute(s).fetchdf()

print("="*72); print("Do 'Structuring'/'Smurfing' senders actually send MANY transactions?"); print("="*72)
print(q("""
WITH flagged AS (
  SELECT DISTINCT Sender_account, Laundering_type
  FROM t WHERE Laundering_type IN ('Structuring','Smurfing')
),
activity AS (
  SELECT f.Laundering_type, f.Sender_account, count(*) AS total_txns,
         sum(CASE WHEN t.Is_laundering=1 THEN 1 ELSE 0 END) AS flagged_txns,
         round(quantile_cont(t.Amount,0.5),2) AS med_amt
  FROM flagged f JOIN t ON t.Sender_account=f.Sender_account
  GROUP BY 1,2
)
SELECT Laundering_type,
       count(*) AS n_senders,
       round(avg(total_txns),1)   AS avg_total_txns_per_sender,
       round(avg(flagged_txns),1) AS avg_flagged_txns_per_sender,
       max(total_txns)            AS max_total_txns,
       round(avg(med_amt),2)      AS avg_median_amt
FROM activity GROUP BY 1
""").to_string(index=False))

print("\n"+"="*72); print("Smurfing senders - do their txns cluster in a 7-day window?"); print("="*72)
print(q("""
WITH s AS (SELECT DISTINCT Sender_account FROM t WHERE Laundering_type='Smurfing')
SELECT count(DISTINCT x.Sender_account) AS smurf_senders,
       round(avg(span_days),1) AS avg_span_days,
       round(min(span_days),1) AS min_span, round(max(span_days),1) AS max_span
FROM (
  SELECT t.Sender_account, date_diff('day', min(t.Date), max(t.Date)) AS span_days
  FROM t JOIN s ON s.Sender_account=t.Sender_account
  WHERE t.Laundering_type='Smurfing' GROUP BY 1
) x
""").to_string(index=False))

print("\n"+"="*72); print("Where do the LABELS sit vs the 8k-10k band R-01 targets?"); print("="*72)
print(q("""
SELECT Laundering_type,
  count(*) AS n,
  sum(CASE WHEN Amount>=8000 AND Amount<10000 THEN 1 ELSE 0 END) AS in_8k_10k_band,
  round(100.0*sum(CASE WHEN Amount>=8000 AND Amount<10000 THEN 1 ELSE 0 END)/count(*),2) AS pct_in_band
FROM t WHERE Laundering_type IN ('Structuring','Smurfing') GROUP BY 1
""").to_string(index=False))

print("\n"+"="*72); print("FAN-OUT candidates (replacement for dead R-03) - ground truth exists?"); print("="*72)
print(q("""
SELECT Laundering_type, count(*) AS n, count(DISTINCT Sender_account) AS senders,
       round(count(*)*1.0/count(DISTINCT Sender_account),1) AS txns_per_sender,
       count(DISTINCT Receiver_account) AS distinct_receivers
FROM t WHERE Laundering_type IN ('Fan_Out','Layered_Fan_Out','Fan_In','Layered_Fan_In','Cycle')
GROUP BY 1 ORDER BY n DESC
""").to_string(index=False))
