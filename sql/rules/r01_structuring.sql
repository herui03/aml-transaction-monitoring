-- R-01 · Structuring / sub-threshold smurfing        [TRANSACTION-GRAIN OUTPUT]
--
-- Returns the individual transactions that CONSTITUTE each alert - not every
-- transaction belonging to a flagged account.
--
-- WHY this matters: the labels in SAML-D are transaction-grain. An account-grain
-- output evaluated against transaction-grain labels overstated precision by ~268x
-- (see docs/methodology_grain.md). A rule must be scored on the evidence it
-- actually presents, which in a real TM console is the "linked transactions" list.
--
-- WHY the peak window: an alert is raised at the moment the pattern completes.
-- The evidence attached to it is the window that triggered it, so we take, per
-- sender, the :window_days window closing on the transaction with the highest
-- in-window count, and return its members.
WITH banded AS (
    SELECT txn_id, sender, ts, amount, is_laundering, laundering_type
    FROM txn
    WHERE amount >= ($threshold * $band_lo)
      AND amount <  $threshold
),
windowed AS (
    SELECT *,
           count(*) OVER (
               PARTITION BY sender ORDER BY ts
               RANGE BETWEEN INTERVAL ($window_days) DAY PRECEDING AND CURRENT ROW
           ) AS txns_in_window
    FROM banded
),
peak AS (
    SELECT sender, ts AS peak_ts, txns_in_window AS peak_count,
           row_number() OVER (PARTITION BY sender
                              ORDER BY txns_in_window DESC, ts) AS rn
    FROM windowed
),
fired AS (
    SELECT sender, peak_ts, peak_count
    FROM peak
    WHERE rn = 1 AND peak_count >= $min_count
)
SELECT b.txn_id, b.sender, b.ts, b.amount,
       b.is_laundering, b.laundering_type,
       f.peak_count AS alert_size
FROM banded b
JOIN fired  f USING (sender)
WHERE b.ts >  f.peak_ts - INTERVAL ($window_days) DAY
  AND b.ts <= f.peak_ts
