# Challenge 04: The Fix That Didn't

> **Status:** resolved (two attempts) · **Date logged:** 2026-07-16 · **Severity:** critical (a false reproducibility claim was already written into the README)

---

## 1. TL;DR

Identical code produced three different models (86.15%, 88.02%, 87.42% recall). I traced it to an unseeded `random()` in the SQL, replaced it with a deterministic hash, verified the *row count* matched, and wrote "reproducible" into the README. It was still broken. The real cause was **row order**: DuckDB's parallel CTAS physically reorders the feature table on every rebuild, and scikit-learn takes its early-stopping validation split **by position**. Same rows, different order, different model. `ORDER BY txn_id` fixed it.

---

## 2. What happened

### Act I, the bug

Two scripts that train the same model on the same data returned different numbers:

| Script | precision@K | recall@K |
|---|---|---|
| `train.py` | 19.492% | 86.57% |
| `train_v2_generalisation.py` | 19.643% | 87.24% |

The cause was visible once I looked: the training query downsampled negatives with

```sql
WHERE txn_date <= DATE '2023-05-31' AND (is_laundering = 1 OR random() < 0.10)
```

`random()` is unseeded. Every run drew a different training set. **Every model in the project had `random_state=42` set; the non-determinism was in the SQL, where I never thought to look for it.**

### Act II, the fix that wasn't

I replaced it with a deterministic hash:

```sql
AND (is_laundering = 1 OR hash(txn_id) % 10 = 0)
```

Then I verified it:

```
run 1: rows=712,761  pos=7,036
run 2: rows=712,761  pos=7,036   (fresh connection)
==> DETERMINISTIC ✅
```

Both scripts now agreed exactly (2,444 / 19.397% / 86.15%). I wrote into the README: *"Two runs from fresh connections return identical training sets and identical model outputs."*

**Then I ran the full pipeline from a clean rebuild, and the model changed again:**

| | recall@K | ROC-AUC |
|---|---|---|
| Before rebuild | 86.15% | 0.9918 |
| **After rebuild** | **88.02%** | **0.9952** |

**My verification had tested the wrong thing.** I checked that the *sample size* was stable. I never checked that the *results* were stable. And I only re-ran the scripts, I never rebuilt the database, which is the step that actually varies.

### Act III, two wrong hypotheses

**Hypothesis 1: the row order from DuckDB is non-deterministic.** The tell was that even the *random baseline* changed (15 → 16), and it uses `np.random.default_rng(42)`, a fixed seed that cannot vary unless the rows it scores are in a different order.

Tested it. **Wrong**, within a single database file, three consecutive queries returned identical order.

**Hypothesis 2: `row_number() OVER ()` in the DB build reassigns `txn_id` on every rebuild**, so `hash(txn_id)` selects a different sample. This one had a real mechanism: `OVER ()` has no `ORDER BY`, so row numbering depends on the order the parallel CSV reader emits rows.

Tested it with a fingerprint of the training sample across a full rebuild:

```
 A: n=712,761  sum_amt=6,494,831,285.37  pos=7,036  id_cksum=85661369  map_cksum=417686538
 B: n=712,761  sum_amt=6,494,831,285.37  pos=7,036  id_cksum=85661369  map_cksum=417686538
```

**Wrong again**, identical. The `txn_id` assignment and the sampled set are both stable.

But that fingerprint used `count`, `sum` and a checksum, **all order-insensitive**. It proved the *set* was stable and said nothing about the *order*. So I fingerprinted the order:

| | first 5 `txn_id` returned | order fingerprint |
|---|---|---|
| Before rebuild | `[3104095, 3096044, 3117516, 1024937, 1027434]` | `1c62f080…` |
| After rebuild | `[3927427, 1619871, 993370, 1600298, 2727245]` | `e2dab7d5…` |

**Same set. Different order. Every rebuild.**

### The mechanism

Two facts combine:

1. **SQL guarantees no row order without `ORDER BY`.** DuckDB builds `features` with a parallel `CREATE TABLE ... AS SELECT` over window functions and joins; the physical order rows land in depends on thread scheduling. It differs on every rebuild.
2. **`HistGradientBoostingClassifier` defaults to `early_stopping='auto'`**, which activates above 10,000 samples and holds out a validation slice **by position**. `random_state=42` fixes *which positions* are held out, not *which rows sit at those positions*.

So: identical data, reordered, produces a different validation split, a different early-stopping point, and a different model. Nothing errors. The number just moves.

**The fix:** `ORDER BY txn_id` on every query that feeds a model. Two full rebuilds now produce a bit-identical model: **2,480 / 19.683% / 87.42% / ROC-AUC 0.9951**.

**Residual, disclosed:** the logistic-regression baseline's ROC-AUC still varies in the 4th decimal (0.9167–0.9169). That is multithreaded BLAS reduction order, not data. It is a baseline, not the headline, and it is reported as 0.9167 rather than hidden.

---

## 3. Why it matters

### (a) Technical reason

**The lesson is not "seed your randomness." It is "verify the output, not the input."**

I did seed the randomness. I then verified the thing that was easy to check (row count) instead of the thing I actually claimed (identical results). A verification that cannot fail is not a verification. **The test must assert the property you are claiming**, if the claim is "the model is reproducible," the test is "train twice, compare the model," not "count the rows twice."

Three further generalisations:

1. **`ORDER BY` is not cosmetic.** Any pipeline whose behaviour depends on row order, sampling, positional splits, `LIMIT` without ordering, floating-point accumulation, is silently non-deterministic without it. Storage order is an implementation detail and parallelism changes it freely.
2. **Order-insensitive fingerprints cannot detect order bugs.** My `count`/`sum`/`checksum` fingerprint was *designed* to be blind to the exact failure mode I was hunting. It returned a confident, meaningless PASS.
3. **Library defaults carry hidden state.** `early_stopping='auto'` is documented, harmless-looking, and turns row order into a model input. `random_state` fixes the *positions* held out, not the *rows*. You inherit every default you don't read.

### (b) Business / regulatory reason

- **Reproducibility is a regulatory requirement, not an engineering nicety.** Under model risk management, an independent model validation team must be able to rebuild your model from your code and data and get *your* numbers. If they get 86.15% and you documented 88.02%, the model does not go live, and your other numbers are now suspect too.
- **A false reproducibility claim is worse than an unreproducible model.** I had already written "identical model outputs" into the README. Had that shipped, an examiner or a validator would have found a documented claim contradicted by a two-minute test. **Being wrong is recoverable; being wrong in writing, in a control document, is a finding.**
- **This is the mechanism behind "it worked in dev."** Nothing crashed. No exception, no warning, no failed assertion. The number simply moved between runs, which is precisely the class of defect that survives testing and reaches production.
- **Silent variance corrupts monitoring.** If a deployed model is periodically retrained and its performance moves ±2 points from row-order noise, model-performance monitoring can no longer distinguish genuine drift from build noise. The control designed to detect decay becomes unable to.

---

## 4. Analogy

**Weighing yourself to check the scale.**

You suspect the bathroom scale is broken. So you test it: you stand on it twice in a row and get 70.0 kg both times. **Consistent. The scale works.** You write that down.

Except the scale only resets when it's picked up and moved. Standing on it twice in a row never triggers the fault. The next morning, scale nudged by the cleaner, it reads 72.5 kg.

**Your test could not fail.** It exercised the one path where the bug doesn't live.

That is exactly what I did: I re-ran the *scripts* twice and confirmed they matched. **The variance lived in the database rebuild**, which my test never touched. `make db` was the hand that moved the scale.

---

## 5. The fix / decision

1. **Deterministic sampling.** `random()` → `hash(txn_id) % 10 = 0`. Necessary but not sufficient, a hash of a stable key, evaluated identically on every run, with no seed state to lose. Preferred over `setseed()`, which is connection-scoped hidden state that a new connection silently discards.

2. **`ORDER BY txn_id` on every query that feeds a model** (`train.py`, `train_v2_generalisation.py`, `coldstart_check.py`), with a comment at each site explaining *why*, because a future reader will otherwise see a pointless sort on 9.5M rows and delete it.

3. **Replaced the verification with one that can actually fail.** The acceptance test is now: rebuild the database from the raw CSV, rebuild the features, train, twice, and diff the model outputs. Not the row count. The output.

4. **Documented the residual instead of hiding it.** The logistic-regression AUC wobble (0.9167–0.9169) is disclosed in the README with its cause. A "fully reproducible" claim with a known 4th-decimal exception is honest; the same claim with the exception omitted is the same mistake I just made.

5. **Kept the false claim's history.** The README previously said "identical model outputs" and was wrong. That sentence is replaced, and this file records that it existed. **The failure mode worth documenting is not the `random()`, it is that I wrote a claim I had not tested.**

---

## 6. Evidence

| File | What it proves |
|---|---|
| `python/train.py` | `ORDER BY txn_id` + `hash(txn_id) % 10 = 0`, with the comment explaining why the sort is load-bearing. |
| `python/train_v2_generalisation.py` | Same fix; its ALL-test row now matches `train.py` exactly (2,480 / 19.683% / 87.42% / 0.9951). |
| `python/coldstart_check.py` | Same fix; its overall recall (87.42%) reconciles with both. |
| `README.md` § Reproducibility | The corrected claim, with the residual BLAS variance disclosed rather than omitted. |

**Acceptance test**, the one that can actually fail:

```bash
run_once () {
  .venv/bin/python python/build_db.py       > /dev/null 2>&1   # rebuild from raw CSV
  .venv/bin/python python/build_features.py > /dev/null 2>&1   # the step that reorders
  .venv/bin/python python/train.py 2>/dev/null | grep -E "^(B0|B1|MA|MB)"
}
[ "$(run_once)" = "$(run_once)" ] && echo "REPRODUCIBLE" || echo "NOT REPRODUCIBLE"
```

The earlier version of this test re-ran only `train.py`, skipping the rebuild, which is where the variance lived. **It passed, and it was worthless.**

