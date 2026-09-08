# Challenge 02: Tuning a Rule for a Crime the Data Doesn't Contain

> **Status:** resolved (rule retired with documented evidence) · **Date logged:** 2026-07-16 · **Severity:** high (would have wasted weeks tuning)

---

## 1. TL;DR

My structuring rule scored 1.1% precision, so I swept 90 parameter combinations looking for a better setting. The best in the entire space was 3.137%, because SAML-D doesn't model threshold-avoidance at all. Only 164 of 2,802 labelled transactions even fall inside the amount band the rule searches, capping recall at 5.85% for a *flawless* implementation.

---

## 2. What happened

**Rule R-01** implements the regulatory definition: one sender making ≥5 transactions in a rolling 7-day window, each valued in the band 8,000–9,999, i.e. deliberately just under a 10,000 reporting threshold. This is the behaviour that is itself a crime in the US (31 U.S.C. § 5324) regardless of whether the underlying funds are dirty.

Run against **SAML-D** (9,504,852 transactions), at transaction grain:

| | |
|---|---|
| Alerts | 43,086 accounts (**14.7% of the 292,715-account book**) |
| Precision (account grain) | **1.1001%** |
| Base rate | 1,933 ÷ 292,715 = **0.66%** |
| **Lift over random** | **1.7×** |

A 1.7× lift should have been the first alarm. Instead of asking *whether the rule could work*, I asked *how to tune it*, and swept the parameter space.

### The sweep: 90 combinations

- **Threshold (T):** 5,000 · 7,500 · 10,000 · 12,500 · 15,000 · 20,000
- **Window (W):** 7 · 14 · 30 days
- **Min count (N):** 3 · 4 · 5 · 6 · 8

| Setting | Alerts | Recall | Precision | Lift |
|---|---|---|---|---|
| Original (T=10,000 / W=7 / N=5) | 43,086 | 24.52% | 1.1001% | 1.7× |
| **Best in the entire space** (T=5,000 / W=30 / N=3) | 30,221 | 49.04% | **3.137%** | 4.7× |

**Nothing in 90 combinations produced a usable rule.** The best still flags 10.32% of the customer base at 97% false positives.

> ### ⚠️ Which grain these sweep numbers use, read this before quoting them
>
> **Every precision figure in the sweep above is account-grain *lenient***, the measure [challenge-01](challenge-01-grain-mismatch.md) proves is inflated by up to 2,750×. The sweep ran before that error was caught, and it is reported here unchanged rather than retroactively rewritten.
>
> **The conclusion survives *a fortiori*, because the honest numbers are worse.** Re-scored at transaction grain (`outputs/corrected_dual_grain.csv`):
>
> | Setting | Precision (account, lenient) | **Precision (transaction, correct)** | **Recall (transaction)** | Coincidence rate |
> |---|---|---|---|---|
> | Original (T=10,000 / W=7 / N=5) | 1.1001% | **0.0004%** | 0.1071% | 99.37% |
> | Best in space (T=5,000 / W=30 / N=3) | 3.137% | **0.0152%** | 2.3198% | 93.78% |
>
> The sweep's *internal comparison* is valid, all 90 combinations were measured identically, so the ranking between settings and the shape of the three gradients hold. What the lenient measure distorts is the *absolute* level, and it distorts it **in the generous direction**. The best setting in the entire space achieves **0.0152% precision at transaction grain**, not 3.137%.
>
> **If asked why the sweep wasn't re-run at the corrected grain:** it would change the numbers and not the finding, and re-running it would erase the evidence of the order in which I learned things. The grid is kept as it was; the correction is stated here.

### The evidence that made it conclusive: all three gradients point the wrong way

| Knob | Direction that improves the score | What that direction *means* |
|---|---|---|
| Threshold | **Lower** is better (5,000 optimal; 10,000–15,000 worst) | The labelled amounts sit at median **4,800.35** (Structuring) and **2,629.43** (Smurfing), **nowhere near any reporting threshold** |
| Window | **Wider** is better (7 → 14 → 30 monotonic) | Labelled Smurfing accounts span a **mean of 121.1 days** (min 4, max 315), not a week |
| Min count | **Fewer** is better (N=3 optimal) | Labelled Structuring accounts carry **1.0 flagged transaction each** (1,870 transactions from 1,870 distinct senders) |

**Every knob that improves the metric pushes the rule away from the definition of structuring.** Drop the threshold to 5,000 and it is no longer "just under the reporting line", it is just "small transactions." Widen the window to 30 days and it is no longer "rapid splitting." Drop to 3 transactions and it is no longer "repeated."

**To make the number look good, the only option is to stop being a structuring rule.**

### The kill shot: the theoretical ceiling

| Labelled typology | Total labelled txns | Falling in the 8,000–9,999 band |
|---|---|---|
| Structuring | 1,870 | **164 (8.77%)** |
| Smurfing | 932 | **0 (0.00%)** |
| **Total** | **2,802** | **164** |

**A flawless implementation caps at 164 ÷ 2,802 = 5.85% recall.** The rule is not mis-tuned. **It is searching a place where the evidence does not exist.**

### The root cause: benign twins

SAML-D pairs every laundering shape with a normal-labelled counterpart:

| Label | Transactions | Share |
|---|---|---|
| `Normal_Small_Fan_Out` | 3,477,717 | **36.59%** |
| `Normal_Fan_Out` | 2,302,220 | **24.22%** |
| `Normal_Fan_In` | 2,104,285 | **22.14%** |

**60.81% of the dataset is benign fan-out/fan-in behaviour.** So the structural shape of laundering carries no discriminative power by construction, which is precisely why the SAML-D authors evaluate ML models on it rather than rules.

Confirmed across **three rule families, 134 parameter combinations total**:

| Rule family | Combinations | Best precision |
|---|---|---|
| R-01 structuring | 90 | 3.137% |
| R-03' fan-out | 20 | 0.966% |
| R-04 smurfing | 24 | 0.233% |

At `min_distinct_recv = 30`, R-03' returned **0 true positives**, the guilty do not fan out *more* than the innocent. There is no extreme to threshold on.

### A separate casualty: R-03 was dead on arrival

The round-number-wire rule (3+ wires at exact multiples of 10,000, ≥30,000, overseas):

| Check | Count in 9,504,852 transactions |
|---|---|
| Exact multiples of 10,000 | **5** |
| Exact multiples of 10,000 **and** ≥ 30,000 | **0** |

SAML-D generates continuous amounts with decimals (39090.73, 31654.11, 70952.02). "Roundness" does not exist by construction. **The rule was retired rather than fudged.**

### One more mismatch worth stating plainly

**SAML-D is UK-denominated.** 9,183,088 of 9,504,852 transactions originate from UK banks; the currency is "UK pounds." **Any Singapore/SGD/MAS framing was removed from the project.** A CTR-threshold narrative borrowed from another jurisdiction and pasted onto UK data would be a factual error an interviewer could catch in one question.

---

## 3. Why it matters

### (a) Technical reason

**A parameter sweep answers "which setting is best?" It does not answer "can this feature separate the classes at all?"** Those are different questions, and I asked them in the wrong order. The sweep cost 90 runs; the ceiling check, *what fraction of labelled transactions even fall in my search band?*, is **one query** and would have ended the investigation on day one.

The generalisable rule: **before optimising a detector, bound it.** Compute the maximum achievable recall given the detector's search space. If the ceiling is 5.85%, no amount of tuning matters.

Second lesson: **lift over base rate is the smoke alarm.** A 1.7× lift is not "a weak detector", it is "approximately a random number generator." Precision quoted without its base rate is how a coin flip gets mistaken for a model.

### (b) Business / regulatory reason

- **Wasted tuning cycles:** In a bank, tuning a live TM rule is not free, each threshold change triggers re-testing, re-documentation, and often re-approval by model validation and sometimes the regulator. Tuning a rule that cannot work burns weeks of a scarce, regulated resource.
- **False assurance is worse than no control:** A rule that claims to cover a typology it cannot detect creates a **documented control that controls nothing**. At the next regulatory review, "we monitor for structuring" is a statement you must defend with evidence. If the honest answer is "our rule caps at 5.85% recall against our own benchmark", that must be *known and disclosed*, not discovered by an examiner.
- **Coverage claims must be bounded:** This is the practical form of model risk management, you are accountable not just for what the model does, but for knowing what it *cannot* do.
- **Knowing when to retire a rule:** R-03 was deleted on the evidence of two numbers (5 and 0). Retiring a control is a governance action, not a cleanup task. **Being able to kill your own feature, with evidence, is a professional skill**, and rule inventories in real banks are full of rules nobody dares delete because nobody measured them.

---

## 4. Analogy

**Testing a speed camera by pointing it at a parking lot.**

The camera works perfectly. The lens is clean, the trigger logic is correct, the calibration certificate is valid.

You get zero speeding tickets. So you tune it: lower the trigger from 60 km/h to 50, to 40, to 5. Eventually it flags every car in the lot, **and every one of them is parked.**

You did not fix the camera. **You stopped measuring speeding.**

That is exactly what dropping my threshold from 10,000 to 5,000 did: precision "improved" from 1.1% to 3.1%, because I quietly stopped detecting *threshold avoidance* and started detecting *small transactions*.

**The cars aren't speeding. The problem was never the camera.**

---

## 5. The fix / decision

1. **Retired R-03 entirely.** Two numbers (5 exact multiples of 10,000 in 9.5M; 0 above 30,000) and the rule is gone. Documented in `sql/rules/r03_fanout.sql`'s header, which records *why* the round-number rule was replaced.

2. **Kept R-01 in the repo as a documented negative result**, not deleted, not tuned into dishonesty. Its 90-point grid is committed as `outputs/r01_sweep.csv`. **The grid is the deliverable.**

3. **Added the ceiling check as a standard first step** before any tuning: *what fraction of the labelled population is even reachable by this detector's search space?*

4. **Built R-04 as a controlled contrast**, deliberately identical in shape to R-01 but with the window matched to the observed 121.1-day behaviour. Its coincidence rate dropped to 16.33% versus R-01's 99.37%, proving the rule *shape* is sound and the *benchmark* is the constraint. **This is what separates a diagnosis from an excuse:** I built the experiment that could have proved me wrong.

5. **Removed all Singapore/SGD/MAS framing** from the project narrative, since the data is UK-denominated.

6. **Pivoted to a scored model (Stage 3)** rather than continuing to tune. The rules become *features*, not verdicts, because the benign twins defeat any single threshold, but may not survive feature interactions.

   **Outcome (measured, Stage 3.2):** they did not survive. At an identical analyst budget of 12,600 investigations (84 test days × 10 analysts × 15 alerts/day), a gradient-boosted model reached **19.88% precision / 86.94% recall** on accounts never flagged in training, against roughly **1% recall** for the rule engine at the same budget. A logistic regression managed only 2.47%, and an amount-only baseline scored **ROC-AUC 0.4733, worse than random**. That spread is the confirmation of this entry's diagnosis from the opposite direction: the classes are inseparable on any single feature (linear model fails, amount fails), and separable only through interactions (tree ensemble succeeds). **The benign twins are real, and they are exactly what defeats a univariate rule and does not defeat an ensemble.**

---

## 6. Evidence

| File | What it proves |
|---|---|
| `outputs/r01_sweep.csv` | The full 90-combination grid. Best precision in the entire space: 3.137%. |
| `outputs/r03_fanout_sweep.csv` | 20 combinations; `min_distinct_recv=30` → 0 true positives (the guilty don't fan out more). |
| `outputs/r04_smurfing_sweep.csv` | 24 combinations; the widened-window contrast. |
| `outputs/corrected_dual_grain.csv` | All four configurations at transaction grain, with coincidence rates. |
| `python/sweep_r01.py` | The sweep harness. |
| `python/profile_stage1b.py` | The feasibility checks: 5 multiples of 10,000; 0 above 30,000; band-occupancy of the labels. |
| `sql/rules/r03_fanout.sql` | Header documents why the round-number rule was retired and replaced. |
| `sql/rules/r04_smurfing.sql` | The falsification test, same shape, window matched to the observed 121.1-day span. |

