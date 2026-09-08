# Challenge 03: The Mean That Lied

> **Status:** caught before it reached the model · **Date logged:** 2026-07-16 · **Severity:** high (drove a wrong conclusion about the entire dataset)

---

## 1. TL;DR

A sanity check on my features showed laundering transactions averaging 40,587.67 versus 8,729.88 for normal, a 4.65× difference, and I concluded laundering in this dataset means "large amounts, cross-border." The median said the opposite: 5,322.79 versus 6,114.63. Laundering is actually *smaller* at the median. The mean was hijacked by a fat tail (p99 = 419,540 versus 44,938).

---

## 2. What happened

After building 37 transaction-grain features, I ran a sanity check, a single `GROUP BY` comparing each feature's average across the two classes, to confirm the features carry any signal before spending time training:

```sql
-- The check that produced the wrong conclusion
SELECT is_laundering,
  round(avg(s_recv_7d),2)           AS avg_distinct_recv_7d,
  round(avg(s_band10k_7d),3)        AS avg_band10k_7d,
  round(avg(s_small_30d),2)         AS avg_small_30d,
  round(avg(s_xborder_ratio_30d),3) AS avg_xborder_ratio,
  round(avg(coalesce(s_passthru_ratio_2d,0)),3) AS avg_passthru_2d,
  round(avg(amount),2)              AS avg_amount
FROM features GROUP BY 1 ORDER BY 1;
```

The output looked decisive:

| Feature | Normal (n=9,494,979) | Laundering (n=9,873) | Read |
|---|---|---|---|
| avg distinct receivers 7d | 7.36 | 3.71 | reversed |
| avg band 8k–10k count 7d | 4.603 | 0.455 | reversed, 10× |
| avg small-txn count 30d | 24.03 | 11.72 | reversed |
| avg pass-through ratio 2d | 17.291 | 3.523 | reversed |
| avg cross-border ratio | 0.096 | 0.171 | **1.8× higher** |
| **avg amount** | **8,729.88** | **40,587.67** | **4.65× higher** |

I concluded: *"In SAML-D, laundering is large amounts moving cross-border, not splitting into small pieces."* It fit the story beautifully. It explained why every rule failed. **It was wrong.**

### The medians

| Feature | Normal | Laundering | |
|---|---|---|---|
| **median amount** | **6,114.63** | **5,322.79** | **laundering is LOWER** |
| median distinct receivers 7d | 5.0 | 2.0 | reversed (survives) |
| median small-txn count 30d | 18.0 | 4.0 | reversed (survives) |
| median band 8k–10k count 7d | **0.0** | **0.0** | no separation |
| median cross-border ratio | **0.0** | **0.0** | no separation |
| median pass-through ratio 2d | **0.0** | **0.0** | no separation |

**Median amount for laundering is *lower* than normal.** The 4.65× was an artefact.

### The amount distributions barely differ until the extreme tail

| Quantile | Normal | Laundering |
|---|---|---|
| p10 | 508 | 210 |
| p25 | 2,143 | 2,724 |
| **p50** | **6,115** | **5,323** |
| p75 | 10,459 | 9,790 |
| p90 | 16,558 | 21,198 |
| **p99** | **44,938** | **419,540** |

**From p10 to p75 the two distributions are effectively the same curve.** Separation appears only in the top ~1%, where laundering reaches 419,540 against normal's 44,938, 9.3×. **That thin tail dragged the mean up 4.65× and I read it as a population-wide signal.**

### Exactly how thin: trimming the tail

I quantified the tail's grip by removing the largest laundering amounts and watching the mean collapse (`python/outlier_count.py`):

| Laundering transactions removed | Remaining mean |
|---|---|
| none (all 9,873) | **40,587.67** |
| top 10 | 30,667.42 |
| **top 50 (0.5%)** | **14,728.27** |
| top 100 (1%) | 11,314.24 |
| **top 500 (5%)** | **6,868.02** |

And the concentration of value:

| Slice of the 9,873 laundering transactions | Share of total laundering value |
|---|---|
| Largest 1 transaction | **3.15%** |
| Largest 10 | 24.52% |
| **Largest 50 (0.5%)** | **63.90%** |
| Largest 99 (1%) | 72.30% |

**50 transactions out of 9,873, 0.5% of the rows, carry 63.90% of all laundering value.** Removing them alone cuts the mean by 64%.

The decisive line: **drop the largest 5% and the remaining 95% of laundering transactions average 6,868.02, below the normal population's mean of 8,729.88.** The "laundering is 4.65× larger" claim inverts once a twentieth of the rows are set aside. That is not a signal; that is a tail.

### The pass-through feature was pure garbage

| | mean | **median** | p99 | max |
|---|---|---|---|---|
| Normal | 17.29 | **0.0** | 377.2 | 23,914.6 |
| Laundering | 3.52 | **0.0** | 16.4 | 20,564.8 |

Both medians are **0.0**. The pass-through ratio is a division (`outflow ÷ inflow`); when inflow approaches zero the ratio explodes into the thousands. The entire "normal 17.29 vs laundering 3.52" contrast was **a handful of near-zero denominators**. Not one word of that comparison was usable.

Same story for `band10k_7d` and `xborder_ratio`: **both medians are 0.0 in both classes.** The mean gaps were driven by sparse minorities, not by the typical account.

---

## 3. Why it matters

### (a) Technical reason

**Financial data is always heavy-tailed:** a few enormous transactions and a vast mass of small ones. **On a heavy-tailed distribution, comparing means is approximately comparing the outliers.** The mean has no resistance, a single 12,618,498 transaction moves it; it cannot move the median.

The failure was worse than "an imprecise statistic." It **manufactured a conclusion in the opposite direction from the truth** and handed me a satisfying narrative that explained my earlier results. That is the dangerous shape: a wrong number that *resolves* an open question feels like insight, so you stop checking.

Two specific traps this exposed:

1. **Ratio features with small denominators.** `outflow ÷ inflow` is unbounded. Any ratio feature needs its denominator distribution inspected before its mean means anything. Winsorising, clipping, or a log transform is mandatory, not cosmetic.
2. **Sparse features.** When the median is 0 in both classes, the feature is mostly zero and the mean describes a small subpopulation. That is not necessarily useless, but it is **not** what the mean implies.

The correct default: **always print median and quantiles alongside the mean. If they disagree, the mean is lying.**

### (b) Business / regulatory reason

- **This is how a threshold gets set wrong.** Had I gone straight to the model or to a new rule believing "laundering = large amounts", the natural next move is an amount-based threshold, which would flag the top percentile of *normal* business activity (large legitimate corporate payments) and miss the laundering entirely, since laundering's median is *lower*. **Average-based reasoning produces a control aimed at the wrong population.**
- **Model validation checks distributions, not just point statistics.** A validator's standard question is *"show me the distribution, not the average"*, precisely because heavy-tailed financial data makes means unstable. An assumption sourced from a mean is an assumption that fails validation.
- **Documented assumptions must be traceable.** In model risk management, every assumption behind a model is documented and challenged. "Laundering amounts are larger" would have entered that document as a stated assumption sourced from a distorted statistic, and everything built on it inherits the defect.
- **Fair lending / bias parallel:** the same mechanism drives bias findings. A mean difference between two customer groups is routinely an outlier artefact; acting on it can produce a discriminatory control from a statistic that was never real.

---

## 4. Analogy

**Bill Gates walks into a bar.**

Ten people are drinking. Average net worth: about $50,000. Perfectly ordinary bar.

Bill Gates walks in. **Average net worth is now roughly $10 billion.**

Ask "are the people in this bar rich?" and the mean answers: *"extraordinarily, 200,000 times the national average."* The median answers: *"no. Same as before. Ten normal people and one outlier."*

**My p99 laundering transactions at 419,540 are Bill Gates.** There are very few of them, they are genuinely enormous, and they made me believe the whole bar was rich.

And the pass-through ratio was worse than Bill Gates, it was **dividing by someone with almost no money**, producing a "wealth ratio" of 23,914 and letting six of those set the average for nine million people.

---

## 5. The fix / decision

1. **Re-ran the sanity check on medians and quantiles** (`python/sanity_medians.py`), which is what should have been run first. Committed alongside the original so the mistake stays visible.

2. **Retracted the conclusion in the project narrative.** "Laundering = large + cross-border" is deleted, not softened. The evidenced statement is now: *the two classes overlap on essentially every marginal distribution below p90; only the top ~1% of laundering amounts diverges.*

3. **Flagged the ratio features for treatment before training.** `s_passthru_ratio_2d` and `s_passthru_ratio_7d` reach 23,914.6 and require clipping or a log transform, an unbounded feature will dominate a linear model and destabilise a tree model's splits.

4. **Adopted a standing rule:** *no mean without its median.* Any feature comparison in this repo reports mean, median, p99 and max together. Same principle as the dual-grain evaluator from Challenge 01, **make the honest number structurally impossible to omit.**

### What this changed about the project's outlook

**The problem is harder than I said, and I revised my confidence downward.**

The classes overlap on nearly every marginal distribution, which is exactly SAML-D's benign-twin design taken one level deeper: the twins aren't merely structurally similar, they are **statistically near-inseparable one feature at a time**. Any model has to find **interactions between features**, not marginal differences.

One genuine upside: my earlier worry that a model might cheaply learn "big amount = laundering" is now largely dead. **Amount doesn't separate at the median, so the model cannot take that shortcut.** The naive amount-ranking baseline planned for Stage 3.2 should perform poorly, which means if the model wins, it wins on real structure.

### A correction to Challenge 01's framing

I earlier described the features as "pointing backwards" and implied that damaged them. **That was imprecise and I've corrected it:**

| | A feature being *lower* for laundering means… |
|---|---|
| **For a rule** | ☠️ Fatal, the rule hard-codes "high value → alert" while truth is "low → laundering". It aims at the wrong tail. |
| **For a model** | ✅ Fine, even good, the model learns a negative coefficient. Reversal means the feature **has signal**, not that it's useless. |

`med_recv_7d` (5.0 vs 2.0) and `med_small_30d` (18.0 vs 4.0) survive the median test and are **reversed**, which makes them the two most promising features in the set.

---

## 6. Evidence

| File | What it proves |
|---|---|
| `python/build_features.py` | The original mean-only sanity check, the mistake, kept in place. |
| `python/sanity_medians.py` | The corrected check: medians, quantiles, and the mean-vs-median contrast that exposed it. |
| `sql/features.sql` | The 37 features; header documents backward-only windows and the leakage exclusions. |

**Key figures for reference:**

| | Normal | Laundering |
|---|---|---|
| n | 9,494,979 | 9,873 |
| amount mean | 8,729.88 | 40,587.67 |
| **amount median** | **6,114.63** | **5,322.79** |
| amount p99 | 44,938 | 419,540 |
| pass-through mean | 17.29 | 3.52 |
| **pass-through median** | **0.0** | **0.0** |
| pass-through max | 23,914.6 | 20,564.8 |

