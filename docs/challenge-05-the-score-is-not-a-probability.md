# Challenge 05: The Score Is Not a Probability

> **Status:** diagnosed, not fixed (calibration is deliberately outstanding) · **Date logged:** 2026-07-16 · **Severity:** high (every score-threshold control built on this model would be wrong)

---

## 1. TL;DR

My model scores ROC-AUC 0.9951 and I read that as "the model is good." It ranks superbly and its numbers are meaningless. Transactions it scores 0.9–0.99 are laundering **6.719%** of the time, not ~95%, a 14× overstatement. Grouped by their dominant SHAP driver, alerts at effectively the same score range from **79.0%** to **3.5%** actual laundering rate. Every metric I report is rank-based, so none of them are wrong, but the first control anyone would build ("escalate above 0.9") would be.

---

## 2. What happened

The model looked finished. ROC-AUC **0.9951**, PR-AUC **0.7982**, precision@budget **19.683%** against a ceiling of 22.5%, 87.5% of the maximum achievable. Leakage ruled out, cold start measured, SHAP attribution rendering a reason per alert.

Then, while checking whether the SHAP-driver breakdown could be used to triage the queue, I noticed something that shouldn't be possible:

| Dominant SHAP driver | Alerts | **Model's median score** | **Actual laundering rate** | Gap |
|---|---|---|---|---|
| `r_senders_30d` | 571 | 99.8% | **79.0%** | 20.8 |
| `s_recv_30d` | 2,610 | 97.4% | **51.4%** | 46.0 |
| `s_passthru_ratio_7d` | 23 | 93.7% | 21.7% | 72.0 |
| `r_txn_7d` | 3,829 | 95.0% | **12.3%** | 82.7 |
| `s_small_30d` | 101 | 91.7% | 11.9% | 79.8 |
| **`s_txn_30d`** | **5,431** | **92.1%** | **3.5%** | **88.6** |

**Alerts at effectively the same score have laundering rates spanning 79.0% to 3.5%, a 22× spread.** If the score were a probability, this could not happen: alerts at 0.92 would be laundering ~92% of the time regardless of *why* they scored 0.92.

So I checked calibration across the entire test set (`python/calibration_check.py`):

| Score bucket | Transactions | **Actual laundering rate** | A calibrated model would say |
|---|---|---|---|
| 0.0 – 0.5 | 2,383,241 | 0.005% | n/a |
| 0.5 – 0.9 | 61,981 | **0.405%** | 50–90% |
| **0.9 – 0.99** | **8,855** | **6.719%** | **90–99%** |
| 0.99 – 0.999 | 1,195 | 89.456% | 99–99.9% |
| 0.999 – 1.0 | 792 | 100.000% | ~100% |

**The 0.9–0.99 bucket is out by a factor of 14.** 8,855 transactions the model called "90-to-99-percent likely" are laundering 6.719% of the time.

### Why this happens

Three causes, and only the first is a mistake:

1. **I downsampled the training negatives 10:1 and used `class_weight="balanced"` on top.** Both shift the fitted intercept. The model was trained on a world where laundering is ~1% prevalent and reweighted toward 50%; it is deployed on one where it is 0.1155%. **The ranking survives that transformation untouched, the probabilities do not.** I documented "downsampling only shifts the intercept, not the ranking, and every metric is rank-based" as a justification. That sentence is true, and I wrote it without following it to its conclusion: *if it shifts the intercept, the probabilities are wrong.*
2. **Gradient boosting optimises a ranking-friendly loss and is not calibrated by construction.** Tree ensembles are known to push probabilities toward the extremes. This is expected behaviour, not a defect.
3. **`predict_proba` returns something called a probability.** The method name is an assertion the model has not earned. Nothing in the API distinguishes "a number between 0 and 1" from "a probability."

### The subtler trap I walked into first

My initial reading of the driver table was operational: *alerts driven by `r_senders_30d` are 79% real and those driven by `s_txn_30d` are 3.5%, so triage the queue by dominant driver and put the 79% bucket first.* That is a real effect and a genuinely tempting move.

**It is also two errors stacked.**

- **The table is computed on the test set.** Deriving a triage rule from test and then reporting its benefit on test is using the same data twice, the estimate of the gain would be inflated by the act of measuring it. Strata like this must be fitted on a validation split carved out of *training* and only then measured on test.
- **More fundamentally, it treats the symptom as the opportunity.** The driver table is not an operational insight. **It is the calibration failure, viewed from the side.** A calibrated model would already assign the 3.5% group lower scores, the whole reason they cluster at 0.92 alongside genuine 79% cases is that the score is not tracking probability. Bolting a driver-based triage layer on top would be patching a symptom while leaving the cause in place, and it would silently entangle explanation with prioritisation.

**The fix is to calibrate the score, not to rank the excuses.**

---

## 3. Why it matters

### (a) Technical reason

**Discrimination and calibration are different properties, and a model can have one without the other.**

- **Discrimination** asks *can you rank?* Measured by ROC-AUC, precision@K. This model: excellent.
- **Calibration** asks *does 0.92 mean 92%?* Measured by reliability curves, Brier score, ECE. This model: no.

ROC-AUC is **invariant to any monotonic transformation of the score.** Square every prediction, take the log, pass it through a sigmoid, AUC does not move. **That invariance is exactly why AUC cannot detect this failure.** I quoted 0.9951 as evidence the model was good, and it is evidence, of precisely one of the two things I needed.

The practical rule: **rank-based metrics survive miscalibration; threshold-based ones do not.** Everything reported in this project is rank-based (precision@K, recall@K, AUC), which is why the headline numbers stand. The moment anyone writes `if score > 0.9:`, they are relying on a property that was never tested and does not hold.

**And the miscalibration is not uniform**, that's the part that makes it dangerous. It is worst exactly where a threshold would sit: the 0.9–0.99 band is out by 14×, while 0.999–1.0 is essentially perfect. A spot-check of the top alerts would show a calibrated-looking model and reveal nothing.

### (b) Business / regulatory reason

- **Every threshold-based control on this model would be wrong.** "Escalate to EDD above 0.9" sounds conservative and would send an analyst 8,855 cases of which **93.3% are clean**. The control would look rigorous in a policy document and function as noise.
- **A score in an STR is a claim.** If a filing says "our model assessed a 95% likelihood," that number goes to a regulator. Here the true figure would be 6.7%. **That is not a modelling error at that point; it is a misstatement in a regulatory filing.**
- **Model risk management requires calibration testing as a distinct discipline.** A validation team will ask for a reliability curve and a Brier score, not just AUC. "AUC 0.9951" answers a question they did not ask. This is a standard finding, and the standard remediation is post-hoc calibration on held-out data.
- **Risk appetite is expressed in probabilities.** A committee sets tolerance as "we act above X% likelihood." That sentence is unimplementable against an uncalibrated score, you cannot map a business policy onto a number that does not mean what it says.
- **Miscalibration is invisible to the metric everyone reports.** AUC is the number that goes in the deck. It cannot see this. **A model can pass every headline check and still be unusable for the one thing the business wants to do with it.**

---

## 4. Analogy

**A thermometer that ranks correctly and reads wrong.**

You have a thermometer that is *perfect* at comparison. Hand it any two objects and it will always tell you which is hotter, never once wrong. On that test it scores 100%.

Then it tells you the patient is at **39°C**. You reach for the fever medication.

The patient is at **36.6°C**. The thermometer's ordering is flawless; its numbers are fiction. It has been ranking, not measuring, the whole time, and every test you ran was a ranking test.

**"Which is hotter?" is discrimination. "How hot is it?" is calibration.** The instrument is genuinely excellent at the first, and you can only prescribe on the second. My ROC-AUC of 0.9951 says the thermometer never gets the order wrong. It says nothing whatsoever about 39.

---

## 5. The fix / decision

**Diagnosed and disclosed; deliberately not yet fixed.** The decision was to state the boundary rather than paper over it:

1. **Documented the failure in the README** with the reliability table, next to the headline ROC-AUC rather than in a footnote. A reader who sees 0.9951 sees the 14× gap in the same section.
2. **Audited every metric in the project for threshold-dependence.** All of them, precision@K, recall@K, AUC, the coincidence rate, the sweep grid, are rank-based, so none required restating. **This is why the check mattered: the answer could have been that half the project needed retracting.**
3. **Declared the model unfit for threshold-based use, in writing.** It ranks well enough to drive an analyst queue today. It is not ready to sit behind `score > X`, and that is now a stated boundary rather than an unexamined assumption.
4. **Rejected the driver-based triage shortcut.** It was fitted on test, it treats the symptom as the opportunity, and it would entangle explanation with prioritisation. Recorded here so the reasoning survives, the idea is attractive enough that I would otherwise have it again.
5. **Specified the remediation rather than rushing it:** isotonic regression or Platt scaling, fitted on a validation split carved out of the *training* period, never on test, with the prevalence shift from downsampling corrected explicitly rather than absorbed into the calibrator. Then re-check the reliability curve, and only then consider a threshold.

**Why not just fix it now:** calibrating against the test set would produce a beautiful reliability curve and destroy the only unbiased estimate of performance in the project, the exact error the entry warns about. The validation split has to be carved from training, and that changes the training data, which changes every number in this repo. **That is a deliberate, scoped piece of work, not a patch to append to a session that has already had to restate its numbers three times** (see [challenge 04](challenge-04-the-fix-that-didnt.md)).

---

## 6. Evidence

| File | What it proves |
|---|---|
| `python/calibration_check.py` | The reliability table and the per-driver gap. The 0.9–0.99 bucket at 6.719%. |
| `python/explain_shap.py` | The SHAP attribution that surfaced the 79.0% → 3.5% spread. |
| `outputs/shap_global_importance.csv` | Global attribution; the driver names behind the spread. |
| `README.md` § headline + § limitations | The reliability table sits next to ROC-AUC 0.9951, not in a footnote. |

