import duckdb, time, os
DB = "data/processed/aml.duckdb"
if os.path.exists(DB): os.remove(DB)
con = duckdb.connect(DB)
t0 = time.time()

# Load raw CSV -> typed table. Combine Date+Time into a single timestamp:
# every rule below is time-ordered, and rolling windows need one comparable instant.
con.execute("""
CREATE TABLE txn AS
SELECT
  row_number() OVER ()                        AS txn_id,
  (Date + Time)                               AS ts,
  Date                                        AS txn_date,
  Sender_account                              AS sender,
  Receiver_account                            AS receiver,
  Amount                                      AS amount,
  Payment_currency                            AS pay_ccy,
  Received_currency                           AS recv_ccy,
  Sender_bank_location                        AS sender_loc,
  Receiver_bank_location                      AS receiver_loc,
  Payment_type                                AS pay_type,
  (Sender_bank_location <> Receiver_bank_location) AS is_xborder,
  Is_laundering                               AS is_laundering,
  Laundering_type                             AS laundering_type
FROM read_csv_auto('data/raw/SAML-D.csv', header=true);
""")
print(f"loaded in {time.time()-t0:.1f}s")

# Indexes on the join/filter keys the rules hit hardest.
con.execute("CREATE INDEX idx_sender_ts ON txn(sender, ts);")
con.execute("CREATE INDEX idx_recv_ts   ON txn(receiver, ts);")

print(con.execute("SELECT count(*) AS rows, count(DISTINCT sender) AS senders FROM txn").fetchdf().to_string(index=False))
print()
print(con.execute("SELECT * FROM txn LIMIT 3").fetchdf().to_string(index=False))
con.close()
print(f"\nDB size: {os.path.getsize(DB)/1e6:.0f} MB   (raw CSV was 950 MB)")
