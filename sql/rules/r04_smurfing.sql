-- R-04 · Smurfing at month scale                     [TRANSACTION-GRAIN OUTPUT]
-- The controlled contrast to R-01: same shape (many transactions from one sender),
-- but the window is widened from 7 days to :window_days, because the labelled
-- Smurfing senders spread activity over a mean span of 121 days (min 4, max 315).
-- If R-01 failed only because its window was too tight, this rule recovers it.
WITH small AS (
    SELECT txn_id, sender, ts, amount, is_laundering, laundering_type
    FROM txn WHERE amount < $amt_cap
),
w AS (
    SELECT *, count(*) OVER (
               PARTITION BY sender ORDER BY ts
               RANGE BETWEEN INTERVAL ($window_days) DAY PRECEDING AND CURRENT ROW
           ) AS c
    FROM small
),
peak AS (
    SELECT sender, ts AS peak_ts, c,
           row_number() OVER (PARTITION BY sender ORDER BY c DESC, ts) AS rn
    FROM w
),
fired AS (
    SELECT sender, peak_ts FROM peak WHERE rn = 1 AND c >= $min_count
)
SELECT s.txn_id, s.sender, s.ts, s.amount, s.is_laundering, s.laundering_type
FROM small s JOIN fired f USING (sender)
WHERE s.ts >  f.peak_ts - INTERVAL ($window_days) DAY
  AND s.ts <= f.peak_ts
