-- R-03' · Fan-out (scatter)                          [TRANSACTION-GRAIN OUTPUT]
-- Replaces the round-number-wire rule, which is undetectable on SAML-D:
-- only 5 of 9,504,852 amounts are exact multiples of 10,000, and 0 of those are
-- >= 30,000. The dataset generates continuous amounts, so "round value" carries
-- no signal by construction.
--
-- Fires when ONE sender pays >= :min_recv DISTINCT receivers inside a rolling
-- :window_days window. Returns the transactions inside the peak window.
WITH w AS (
    SELECT txn_id, sender, receiver, ts, amount, laundering_type,
           count(DISTINCT receiver) OVER (
               PARTITION BY sender ORDER BY ts
               RANGE BETWEEN INTERVAL ($window_days) DAY PRECEDING AND CURRENT ROW
           ) AS distinct_recv
    FROM txn
),
peak AS (
    SELECT sender, ts AS peak_ts, distinct_recv,
           row_number() OVER (PARTITION BY sender ORDER BY distinct_recv DESC, ts) AS rn
    FROM w
),
fired AS (
    SELECT sender, peak_ts FROM peak WHERE rn = 1 AND distinct_recv >= $min_recv
)
SELECT t.txn_id, t.sender, t.ts, t.amount, t.is_laundering, t.laundering_type
FROM txn t JOIN fired f USING (sender)
WHERE t.ts >  f.peak_ts - INTERVAL ($window_days) DAY
  AND t.ts <= f.peak_ts
