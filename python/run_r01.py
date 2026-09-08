import duckdb
con = duckdb.connect("data/processed/aml.duckdb", read_only=True)
sql = open("sql/rules/r01_structuring.sql").read()

def run(threshold, window_days, min_count, band_lo=0.8):
    p = {"threshold": threshold, "band_lo": band_lo,
         "window_days": window_days, "min_count": min_count}
    flagged = con.execute(f"SELECT sender FROM ({sql})", p).fetchdf()
    senders = set(flagged["sender"].tolist())
    return senders

# --- baseline: YOUR ORIGINAL PARAMETERS ---
print("="*72)
print("R-01 with YOUR ORIGINAL PARAMETERS: threshold=10,000  window=7d  min_count=5")
print("="*72)
s = run(10000, 7, 5)
print(f"senders flagged           : {len(s):,}")

# ground truth: senders that actually have a Structuring/Smurfing labelled txn
gt = con.execute("""
  SELECT DISTINCT sender FROM txn WHERE laundering_type IN ('Structuring','Smurfing')
""").fetchdf()["sender"].tolist()
gt = set(gt)
print(f"ground-truth guilty senders: {len(gt):,}")
hit = s & gt
print(f"caught (true positives)   : {len(hit):,}")
print(f"recall                    : {100*len(hit)/len(gt):.2f}%")
print(f"precision                 : {100*len(hit)/len(s):.2f}%" if s else "precision: n/a")
