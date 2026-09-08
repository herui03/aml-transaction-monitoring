-- ===================================================================
-- Feature engineering - TRANSACTION GRAIN, BACKWARD-LOOKING ONLY
-- ===================================================================
-- Every window is RANGE ... PRECEDING AND CURRENT ROW: at scoring time we may
-- only use what was knowable when the transaction landed. A random split or a
-- forward-looking window would leak the future and inflate every metric.
--
-- The rule logic from Stage 2 is NOT discarded - each rule becomes a FEATURE
-- (a count, a ratio) instead of a verdict. Rules decide alone; features vote.
--
-- Deliberately EXCLUDED: laundering_type (incl. the 'Normal_*' values, which
-- encode the generator's intent and would leak), and any global statistic
-- computed over the full dataset.

-- Directional flow view: one row per (account, event), both legs of every txn.
CREATE OR REPLACE TABLE flows AS
SELECT txn_id, sender   AS account, ts, amount,  0 AS is_inflow FROM txn
UNION ALL
SELECT txn_id, receiver AS account, ts, amount,  1 AS is_inflow FROM txn;

CREATE OR REPLACE TABLE acct_flow_feat AS
SELECT txn_id, account, is_inflow,
  sum(CASE WHEN is_inflow=1 THEN amount ELSE 0 END) OVER w2 AS in_2d,
  sum(CASE WHEN is_inflow=0 THEN amount ELSE 0 END) OVER w2 AS out_2d,
  sum(CASE WHEN is_inflow=1 THEN amount ELSE 0 END) OVER w7 AS in_7d,
  sum(CASE WHEN is_inflow=0 THEN amount ELSE 0 END) OVER w7 AS out_7d
FROM flows
WINDOW
  w2 AS (PARTITION BY account ORDER BY ts RANGE BETWEEN INTERVAL 2 DAY PRECEDING AND CURRENT ROW),
  w7 AS (PARTITION BY account ORDER BY ts RANGE BETWEEN INTERVAL 7 DAY PRECEDING AND CURRENT ROW);

CREATE OR REPLACE TABLE features AS
WITH s AS (   -- sender-side history
  SELECT txn_id, sender, receiver, ts, txn_date, amount, is_xborder,
         pay_type, pay_ccy, recv_ccy, is_laundering, laundering_type,
         count(*)                  OVER s1  AS s_txn_1d,
         count(*)                  OVER s7  AS s_txn_7d,
         count(*)                  OVER s30 AS s_txn_30d,
         count(DISTINCT receiver)  OVER s1  AS s_recv_1d,
         count(DISTINCT receiver)  OVER s7  AS s_recv_7d,
         count(DISTINCT receiver)  OVER s30 AS s_recv_30d,
         sum(amount)               OVER s7  AS s_amt_sum_7d,
         avg(amount)               OVER s7  AS s_amt_avg_7d,
         coalesce(stddev(amount)   OVER s7, 0) AS s_amt_std_7d,
         max(amount)               OVER s30 AS s_amt_max_30d,
         avg(CASE WHEN is_xborder THEN 1.0 ELSE 0 END) OVER s30 AS s_xborder_ratio_30d,
         -- R-01 as a feature: sub-threshold band density, 7d
         sum(CASE WHEN amount>=8000 AND amount<10000 THEN 1 ELSE 0 END) OVER s7  AS s_band10k_7d,
         sum(CASE WHEN amount>=4000 AND amount< 5000 THEN 1 ELSE 0 END) OVER s7  AS s_band5k_7d,
         -- R-04 as a feature: small-value density, 30d
         sum(CASE WHEN amount<7000 THEN 1 ELSE 0 END) OVER s30 AS s_small_30d,
         min(ts)                   OVER (PARTITION BY sender) AS s_first_ts
  FROM txn
  WINDOW
    s1  AS (PARTITION BY sender ORDER BY ts RANGE BETWEEN INTERVAL  1 DAY PRECEDING AND CURRENT ROW),
    s7  AS (PARTITION BY sender ORDER BY ts RANGE BETWEEN INTERVAL  7 DAY PRECEDING AND CURRENT ROW),
    s30 AS (PARTITION BY sender ORDER BY ts RANGE BETWEEN INTERVAL 30 DAY PRECEDING AND CURRENT ROW)
),
r AS (        -- receiver-side history (fan-in signal)
  SELECT txn_id,
         count(*)                OVER r7  AS r_txn_7d,
         count(DISTINCT sender)  OVER r7  AS r_senders_7d,
         count(DISTINCT sender)  OVER r30 AS r_senders_30d,
         sum(amount)             OVER r7  AS r_amt_sum_7d
  FROM txn
  WINDOW
    r7  AS (PARTITION BY receiver ORDER BY ts RANGE BETWEEN INTERVAL  7 DAY PRECEDING AND CURRENT ROW),
    r30 AS (PARTITION BY receiver ORDER BY ts RANGE BETWEEN INTERVAL 30 DAY PRECEDING AND CURRENT ROW)
)
SELECT
  s.txn_id, s.ts, s.txn_date, s.is_laundering, s.laundering_type,
  -- transaction intrinsics
  s.amount,
  ln(s.amount + 1)                                    AS log_amount,
  CASE WHEN s.is_xborder THEN 1 ELSE 0 END            AS is_xborder,
  CASE WHEN s.pay_ccy <> s.recv_ccy THEN 1 ELSE 0 END AS ccy_mismatch,
  s.pay_type,
  hour(s.ts)                                          AS hour_of_day,
  dayofweek(s.txn_date)                               AS day_of_week,
  -- roundness (R-03 is dead as a RULE, but keep the signal as a FEATURE and let
  -- the model decide whether it carries information)
  CASE WHEN abs(s.amount % 100)  < 0.005 THEN 1 ELSE 0 END AS is_round_100,
  CASE WHEN abs(s.amount % 1000) < 0.005 THEN 1 ELSE 0 END AS is_round_1000,
  -- sender velocity / network
  s.s_txn_1d, s.s_txn_7d, s.s_txn_30d,
  s.s_recv_1d, s.s_recv_7d, s.s_recv_30d,
  s.s_amt_sum_7d, s.s_amt_avg_7d, s.s_amt_std_7d, s.s_amt_max_30d,
  s.s_xborder_ratio_30d,
  s.s_band10k_7d, s.s_band5k_7d, s.s_small_30d,
  -- how unusual is this amount for THIS sender right now
  (s.amount - s.s_amt_avg_7d) / nullif(s.s_amt_std_7d, 0) AS s_amt_zscore_7d,
  date_diff('day', s.s_first_ts, s.ts)                    AS s_account_age_days,
  -- receiver side
  r.r_txn_7d, r.r_senders_7d, r.r_senders_30d, r.r_amt_sum_7d,
  -- R-02 as a feature: pass-through ratio (outflow vs inflow) for the SENDER
  af.out_2d / nullif(af.in_2d, 0)                     AS s_passthru_ratio_2d,
  af.out_7d / nullif(af.in_7d, 0)                     AS s_passthru_ratio_7d,
  af.in_2d                                            AS s_inflow_2d
FROM s
JOIN r USING (txn_id)
LEFT JOIN acct_flow_feat af ON af.txn_id = s.txn_id AND af.is_inflow = 0;
