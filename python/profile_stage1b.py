import duckdb
con = duckdb.connect()
src = "read_csv_auto('data/raw/SAML-D.csv', header=true)"
def q(s): return con.execute(s).fetchdf()

print("="*70); print("R-01 FEASIBILITY - mass in the sub-threshold band"); print("="*70)
print(q(f"""
SELECT
  round(100.0*sum(CASE WHEN Amount>=8000  AND Amount<10000 THEN 1 ELSE 0 END)/count(*),3) AS pct_8k_10k,
       sum(CASE WHEN Amount>=8000  AND Amount<10000 THEN 1 ELSE 0 END) AS n_8k_10k,
  round(100.0*sum(CASE WHEN Amount>=16000 AND Amount<20000 THEN 1 ELSE 0 END)/count(*),3) AS pct_16k_20k,
       sum(CASE WHEN Amount>=16000 AND Amount<20000 THEN 1 ELSE 0 END) AS n_16k_20k,
  round(100.0*sum(CASE WHEN Amount>=10000 THEN 1 ELSE 0 END)/count(*),3) AS pct_over_10k
FROM {src}
""").T.rename(columns={0:"value"}).to_string())

print("\n"+"="*70); print("R-03 FEASIBILITY - do exact multiples of 10,000 even EXIST?"); print("="*70)
print(q(f"""
SELECT
  sum(CASE WHEN Amount = round(Amount)                    THEN 1 ELSE 0 END) AS whole_numbers,
  sum(CASE WHEN abs(Amount % 1000)  < 0.005               THEN 1 ELSE 0 END) AS multiples_of_1k,
  sum(CASE WHEN abs(Amount % 10000) < 0.005               THEN 1 ELSE 0 END) AS multiples_of_10k,
  sum(CASE WHEN abs(Amount % 10000) < 0.005 AND Amount>=30000 THEN 1 ELSE 0 END) AS mult_10k_over_30k
FROM {src}
""").T.rename(columns={0:"count"}).to_string())

print("\n"+"="*70); print("Amount decimal structure - sample of large amounts"); print("="*70)
print(q(f"SELECT Amount FROM {src} WHERE Amount>=30000 ORDER BY random() LIMIT 12").to_string(index=False))

print("\n"+"="*70); print("STRUCTURING/SMURFING ground truth - what do they look like?"); print("="*70)
print(q(f"""
SELECT Laundering_type, count(*) AS n,
       count(DISTINCT Sender_account) AS senders,
       round(min(Amount),2) AS min_amt, round(quantile_cont(Amount,0.5),2) AS med_amt,
       round(max(Amount),2) AS max_amt,
       round(avg(CASE WHEN Sender_bank_location<>Receiver_bank_location THEN 1.0 ELSE 0 END)*100,1) AS pct_xborder
FROM {src} WHERE Laundering_type IN ('Structuring','Smurfing') GROUP BY 1
""").to_string(index=False))

print("\n"+"="*70); print("LAYERING-family ground truth (R-02 target)"); print("="*70)
print(q(f"""
SELECT Laundering_type, count(*) AS n, count(DISTINCT Sender_account) AS senders,
       round(quantile_cont(Amount,0.5),2) AS med_amt,
       round(avg(CASE WHEN Sender_bank_location<>Receiver_bank_location THEN 1.0 ELSE 0 END)*100,1) AS pct_xborder
FROM {src}
WHERE Laundering_type IN ('Layered_Fan_In','Layered_Fan_Out','Cycle','Bipartite',
                          'Stacked Bipartite','Gather-Scatter','Scatter-Gather','Deposit-Send')
GROUP BY 1 ORDER BY n DESC
""").to_string(index=False))

print("\n"+"="*70); print("DATA-QUALITY TELL - Payment_type='Cross-border' vs location mismatch"); print("="*70)
print(q(f"""
SELECT Payment_type='Cross-border' AS typed_xborder,
       Sender_bank_location<>Receiver_bank_location AS loc_mismatch,
       count(*) AS n
FROM {src} GROUP BY 1,2 ORDER BY 1,2
""").to_string(index=False))
