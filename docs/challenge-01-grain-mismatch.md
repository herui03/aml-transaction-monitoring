# Challenge 01: The Grain Mismatch That Inflated Precision 2,750×

> **Status:** resolved · **Date logged:** 2026-07-16 · **Severity:** critical (would have shipped a false result)

---

## 1. TL;DR

I evaluated an account-level detection rule against transaction-level labels, which made a completely useless rule look like it had 1.10% precision. Once I aligned the grain, true precision was 0.0004%, a 2,750× overstatement, with 99.37% of my "catches" being coincidences.

---

## 2. What happened

I ported a rule-based AML transaction monitoring engine onto **SAML-D**, a published third-party benchmark of **9,504,852 transactions** with labelled laundering typologies.

**Rule R-01** fires when one sender makes ≥5 transactions in a rolling 7-day window, each valued between 8,000 and 9,999, i.e. just under a 10,000 reporting threshold.

To score it, I built my "ground truth" like this:

```sql
-- WRONG: collapses a transaction-grain label to an account-grain label
SELECT DISTINCT sender FROM txn
WHERE laundering_type IN ('Structuring','Smurfing')
```

This says: *"if an account has **any** labelled transaction in its history, the whole account is guilty."*

That produced **1,933 "guilty" accounts**. My rule flagged **43,086 accounts**, of which **474** overlapped. I reported:

- **Precision: 1.1001%**
- **Recall: 24.52%**

Bad numbers, but they *looked like a working detector*.

**The problem:** the labels are attached to **individual transactions**, not accounts. And the labelled accounts are overwhelmingly normal:

| Labelled typology | Mean total txns per account | Mean **labelled** txns per account |
|---|---|---|
| Structuring | 135.8 | **1.0** |
| Smurfing | 140.9 | 14.8 |

A "Structuring" account has **135.8 transactions, of which 1.0 is laundering, 99.3% of its activity is normal**. My rule needs 5 transactions in a 7-day band to fire. **The 5 transactions that triggered the alert were almost never the 1 transaction that was actually labelled.**

So the rule flagged the account **for an unrelated reason**, and my scoring counted it as correct.

### The corrected numbers

I rewrote the rule to emit **transaction grain**, returning only the transactions inside the triggering window (the "linked transactions" a real TM console shows as evidence), and re-scored:

| Measurement | Precision | Recall | Inflation vs. truth |
|---|---|---|---|
| Account grain, **lenient** (what I first reported) | **1.1001%** | 24.52% | **2,750×** |
| Account grain, **strict** (flagged for the *right* reason) | **0.0070%** | n/a | 17× |
| **Transaction grain (the only correct one)** | **0.0004%** | **0.1071%** | n/a |

- Alerted transactions: **753,526**
- Of which truly laundering: **3**
- **Coincidence rate: 99.3671%**, of 474 claimed true positives, only **3** were flagged because of a genuinely labelled transaction. **471 were luck.**

### The kill shot: the rule's theoretical ceiling

I then checked where the labelled transactions actually sit relative to the band the rule searches:

| Labelled typology | Total labelled txns | Falling in the 8,000–9,999 band |
|---|---|---|
| Structuring | 1,870 | **164 (8.77%)** |
| Smurfing | 932 | **0 (0.00%)** |

**Only 164 of 2,802 labelled transactions are in the band at all.** So even a flawless implementation caps out at **164 ÷ 2,802 = 5.85% recall**. It achieved 0.1071%.

**The rule is not badly tuned. It is searching a place where the evidence does not exist.**

---

## 3. Why it matters

### (a) Technical reason

**Grain = what one row represents.** A metric computed across mismatched grains is not a weak metric, it is a **meaningless** one. Precision and recall are only defined when the prediction set and the label set live in the same space.

The mismatch created a **silent false positive in the evaluation itself**. The rule was wrong, the score said "weak but working", and nothing crashed. There was no error message. This is the most dangerous class of bug: **one that produces a plausible number.**

It also shows why "any-match" collapsing is a trap. `EXISTS(labelled txn)` is a *very* weak account-level label when 99.3% of that account's behaviour is normal. It converts a precise transaction label into an almost-meaningless account attribute.

### (b) Business / regulatory reason

In a real bank this error ships a **dead rule into production**, and everyone believes it is working.

- **False positive cost:** 43,086 flagged accounts out of 292,715 = **14.7% of the customer base**. At ~15 alerts per analyst-day, that is roughly **2,872 analyst-days ≈ 11 full-time analysts for a year**, investigating alerts of which 99.99% are noise.
- **Model validation:** This is exactly why model validation is an **independent, regulated function**, separate from the team that builds the model. The builder has an incentive (however unconscious) to pick the flattering measurement. I picked it without noticing.
- **Audit / model risk management:** An auditor's first question is *"how did you validate this, and at what grain?"* If the answer is "account grain against transaction labels", every downstream metric, tuning decisions, threshold choices, coverage claims to the regulator, is void.
- **Regulatory exposure:** Claiming coverage of a typology you cannot actually detect is worse than not claiming it. It creates a documented control that does not control anything.

---

## 4. Analogy

**A blood test.**

A patient has **136 blood tests**. Exactly **one** came back abnormal.

- **The label says:** *"Test #47 was abnormal."*, that is transaction grain.
- **My rule says:** *"This patient is sick."*, that is account grain.
- **My scoring said:** *"He had an abnormal test somewhere, so I was right!"* ✅

But I concluded he was sick based on **tests #12 through #16**, which were all perfectly normal, and had nothing to do with test #47.

**I guessed right, for entirely the wrong reason. And I gave myself credit for it 471 times out of 474.**

---

## 5. The fix / decision

**Three changes, all committed:**

1. **Rules now emit transaction grain.** `r01_structuring.sql` returns only the transactions inside the peak triggering window, the same "linked transactions" evidence list a real TM console attaches to an alert. A rule is scored on the evidence it actually presents, not on everything the suspect ever did.

2. **Built a dual-grain evaluator that cannot hide the gap.** `python/evaluate.py` **always** reports transaction grain, account-lenient, account-strict, *and* the coincidence rate, in one output. I deliberately made the flattering number impossible to report alone, the honest number is always next to it.

3. **Documented the error instead of quietly fixing it.** This file is the artifact.

**Why this was the right call:** I could have silently switched to the corrected numbers and reported "R-01 achieves 0.0004% precision." That would have been *accurate* and *useless*, it hides the most valuable thing I learned. **The 2,750× gap is the finding.** It is a reusable lesson about validation; the dead rule is not.

### The controlled contrast that proves the diagnosis

I then built **R-04**, deliberately identical in shape to R-01 (many transactions from one sender) but with the window widened from 7 days to 90, because the labelled Smurfing accounts spread activity over a **mean span of 121.1 days**, not a week.

| Rule | Window | **Coincidence rate** |
|---|---|---|
| R-01 structuring | 7 days | **99.37%** |
| R-04 smurfing | 90 days | **16.33%** |

Same rule shape. Matching the window to the *actual* behaviour dropped the coincidence rate from 99% to 16%, **R-04 fires for the right reason 83.7% of the time.**

**This separates two failures that look identical from the outside:**

| Failure | Symptom | Fixable? |
|---|---|---|
| **Firing for the wrong reason** | coincidence rate 99.37% | ✅ Yes, align parameters to real behaviour |
| **Alert flooding** | precision ~0.02% across every rule | ❌ No, not by any threshold |

Even R-04, firing honestly, must alert **1,986,773 transactions (20.9% of the entire dataset)** to reach 43.67% recall. That is the **precision ceiling of univariate rules** on this data, and it motivates the model in Stage 3.

---

## 6. Evidence

| File | What it proves |
|---|---|
| `python/evaluate.py` | The dual-grain evaluator. Always emits transaction grain, account-lenient, account-strict, and coincidence rate together, the flattering number can't be reported alone. |
| `sql/rules/r01_structuring.sql` | The corrected transaction-grain rule; header comment documents *why* the peak window is the alert's evidence. |
| `sql/rules/r04_smurfing.sql` | The controlled contrast, same rule shape, window matched to the 121.1-day real behaviour; coincidence rate 16.33% vs R-01's 99.37%. |
| `outputs/corrected_dual_grain.csv` | All four rule configurations scored at both grains. |
| `outputs/r01_sweep.csv` | The 90-combination parameter grid proving the ~3% ceiling is not a tuning problem. |
| `python/grain_check.py` | The query that first quantified the coincidence rate. |
| `docs/challenge-01-grain-mismatch.md` | This file. |

