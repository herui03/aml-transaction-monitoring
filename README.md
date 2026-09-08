# AML Transaction Monitoring: Rules vs a Scored Model at Analyst Capacity

I ported a rule-based anti-money-laundering monitoring engine onto SAML-D, a public benchmark of 9,504,852 transactions with labelled laundering typologies, measured how the rules actually perform, and then compared them with a scored model at the same investigation budget.

The short version: rule-based monitoring does not fail because the rules are inaccurate. It fails because rules cannot rank. A compliance team can only investigate a fixed number of alerts per day, and a rule that raises a million alerts with no ordering gives them no way to choose.

Stack: SQL (DuckDB, window functions), Python (pandas, scikit-learn, SHAP), Tableau.

## Headline result

Budget: 12,600 investigations over the 84-day test period (10 analysts x 15 alerts per day).

| Approach | Precision at budget | Laundering caught at budget | ROC-AUC |
|---|---|---|---|
| Rule engine (R-04, best configuration) | n/a | 0.07% (see note) | n/a |
| Random ordering | 0.103% | 0.46% | n/a |
| Amount-only ranking | 0.516% | 2.29% | 0.4733 (worse than random) |
| Logistic regression | 2.468% | 10.96% | 0.9167 |
| Gradient-boosted model | 19.683% | 87.42% | 0.9951 |

The theoretical ceiling at this budget is 22.5% precision (2,837 positives / 12,600 investigations), so the model reaches 87.5% of what is achievable.

About the 0.07% for rules: a rule fires or it does not, so at a fixed budget you are drawing at random from its alerts. On the test period R-04 raised 1,115,642 alerts containing 163 true positives. Investigating 12,600 of them yields 1.84 in expectation, or 0.065% of the 2,837 labelled cases.

The obvious objection is that R-04 targets one typology while the model scores everything. Restricting the comparison to Smurfing, the typology R-04 was written for (263 cases in the test period):

| Basis | Positives | Rule recall at budget | Model recall at budget |
|---|---|---|---|
| All laundering typologies | 2,837 | 0.065% | 87.42% |
| Smurfing only | 263 | 0.700% | 84.41% |

R-04 does find 163 of the 263 Smurfing cases (62%), but only if you investigate all 1,115,642 of its alerts. The rule can detect; what it detects cannot be found within budget.

## Data

[SAML-D](https://www.kaggle.com/datasets/berkanoztas/synthetic-transaction-monitoring-dataset-aml) (Oztas et al.), licence CC-BY-NC-SA-4.0. Not redistributed here; `make data` downloads it.

| | |
|---|---|
| Transactions | 9,504,852 |
| Period | 2022-10-07 to 2023-08-23 (321 days) |
| Accounts | 292,715 senders, 652,266 receivers |
| Labelled laundering | 9,873 (0.1039%) across 17 typologies |
| Nulls / duplicates | 0 / 0 |

Why a synthetic benchmark: real bank AML data cannot be published. Card-fraud datasets have no counterparty network, so none of these rules can run on them; blockchain data has no amounts or jurisdictions. SAML-D carries per-typology ground truth, and the rules were written independently of it, which is what makes precision measurable at all.

SAML-D is UK-denominated (9,183,088 of 9,504,852 transactions originate from UK banks). No Singapore or MAS framing is used in this project.

## What is built

```
sql/rules/                 R-01 structuring, R-03' fan-out, R-04 smurfing (SQL window functions, transaction-grain output)
sql/features.sql           37 backward-looking features; the rules become inputs rather than verdicts
python/evaluate.py         dual-grain evaluator: always prints the transaction-grain number next to the account-grain one
python/train.py            baselines, logistic regression, gradient boosting, precision@K
python/explain_shap.py     SHAP attribution over the alert queue, one reason per alert
python/calibration_check.py  discrimination vs calibration
docs/                      five documented mistakes and what they cost
tableau/                   extracts and a build guide for the dashboard
outputs/                   every figure quoted here, as committed CSVs
```

Pipeline: 950 MB CSV loaded into DuckDB (7.2s), SQL rule and feature layer, scikit-learn, Tableau extract.

Split is time-based, never random: train 2022-10-07 to 2023-05-31 (7,048,788 rows, 7,036 positives), test 2023-06-01 to 2023-08-23 (2,456,064 rows, 2,837 positives). Training keeps every positive and deterministically downsamples negatives to 712,761 rows; this shifts the fitted intercept but not the ranking, and every reported metric is rank-based. The test set is never sampled.

## How the project went

1. Port the rules and measure them properly. R-01 (structuring) at its original parameters flagged 43,086 accounts at 1.10% precision. Then a grain error surfaced (challenge 01 below) and the true transaction-grain precision was 0.0004%.

2. Check whether tuning can save it. 134 parameter combinations across three rule families. The best result anywhere in the grid was 3.137%, and every change that improved the metric moved the rule further from the regulatory definition of structuring. A ceiling check settled it: only 164 of 2,802 labelled transactions fall inside the amount band the rule searches, capping a perfect implementation at 5.85% recall.

3. Work out why. SAML-D pairs every laundering pattern with a benign twin: Normal_Fan_Out is 24.22% of the data and Normal_Small_Fan_Out is 36.59%, so 60.81% of the dataset is benign fan-out behaviour and no single aggregate feature separates the two. An amount-only baseline scores ROC-AUC 0.4733, worse than random, and a linear model manages 2.47% precision. The signal is in feature interactions, which is why a tree ensemble works where thresholds do not.

4. Check the model is not cheating. ROC-AUC 0.9951 on a 0.1%-prevalence problem deserves suspicion. All features are sender-history aggregates, so the model could be memorising known-bad accounts. Sliced by sender familiarity:

   | Test slice | Positives | Precision at budget | Recall at budget | ROC-AUC |
   |---|---|---|---|---|
   | All test | 2,837 | 19.683% | 87.42% | 0.9951 |
   | Seen in training but never flagged bad | 2,075 (73%) | 19.877% | 86.94% | 0.9941 |
   | Already known-bad in training | 751 (26%) | 80.085% | 74.97% | 0.9935 |
   | Never seen in training | 11 (too few to interpret) | n/a | n/a | n/a |

   On accounts the model was never told were bad, 73% of test positives, recall is 86.94% against 87.42% overall. It is not memorising a blacklist. Only 751 of 2,837 test positives belong to a sender that was ever flagged in training, so memorisation alone could not produce 86% recall.

5. Make the score readable, and find out it is not a probability. An MLRO cannot file an STR on "0.97". SHAP attribution over the 12,600-alert queue gives each alert a reason, the model's equivalent of a rule's trigger logic:

   > `[true positive] txn 7656473 | score 0.9999 | actual: Cash_Withdrawal`
   > why: sender paid 2 distinct beneficiaries in 30 days (+4.59); beneficiary was paid by 3 distinct senders in 30 days (+3.03); sender made 2 transactions in 24 hours (+1.15)

   Three things came out of the attribution. First, the model is doing network analysis rather than amount analysis: the top six features (beneficiary fan-in, sender velocity, sender fan-out) carry 65.36% of attribution and `amount` carries 1.83%, consistent with the amount-only baseline being worse than random. Second, given every rule's logic as a feature, the model ranked them the same way the rule evaluation had: R-04's `s_small_30d` at 5.64%, R-02's pass-through ratio at 2.01%, R-01's sub-threshold band density at 0.06% (29th of 32), R-03's roundness flag at exactly 0.000000. Third, the score is not a probability:

   | Score bucket | Transactions | Actual laundering rate |
   |---|---|---|
   | 0.5 to 0.9 | 61,981 | 0.405% |
   | 0.9 to 0.99 | 8,855 | 6.719% |
   | 0.99 to 0.999 | 1,195 | 89.456% |
   | 0.999 to 1.0 | 792 | 100.000% |

   A calibrated model would put the 0.9 to 0.99 bucket near 95%; this one is out by a factor of 14. Every metric in this README is rank-based and unaffected, but any score threshold would be, and "escalate above 0.9" is the first thing anyone reaches for. See [challenge 05](docs/challenge-05-the-score-is-not-a-probability.md).

Reproducibility: two full rebuilds from the raw CSV return a bit-identical gradient-boosted model (2,480 / 19.683% / 87.42% / 0.9951). This took two attempts, documented in [challenge 04](docs/challenge-04-the-fix-that-didnt.md): deterministic negative sampling (`hash(txn_id) % 10 = 0` instead of `random()`) was necessary but not sufficient, because DuckDB's parallel CTAS reorders the feature table on every rebuild and scikit-learn's early-stopping validation split is taken by position. `ORDER BY txn_id` pins it. The logistic-regression baseline still varies in the fourth decimal (0.9167 to 0.9169) from multithreaded BLAS reduction order; the reported figure is 0.9167.

## Things that went wrong

Each of these produced a plausible number and no error message.

| | What went wrong | Cost if unnoticed |
|---|---|---|
| [01 Grain mismatch](docs/challenge-01-grain-mismatch.md) | Scored an account-grain rule against transaction-grain labels | Precision overstated 2,750x; 99.37% of "catches" were coincidences |
| [02 Benchmark mismatch](docs/challenge-02-benchmark-mismatch.md) | Tuned 90 combinations before computing the rule's ceiling | Weeks tuning a rule capped at 5.85% recall |
| [03 The mean that lied](docs/challenge-03-the-mean-that-lied.md) | Compared means on a heavy-tailed distribution | A "4.65x signal" carried by 50 of 9,873 rows; the median went the other way |
| [04 The fix that didn't](docs/challenge-04-the-fix-that-didnt.md) | Fixed an unseeded sample, then verified the wrong thing | Same code, three different answers (86.15% / 88.02% / 87.42% recall) while the README claimed reproducibility |
| [05 The score is not a probability](docs/challenge-05-the-score-is-not-a-probability.md) | Read ROC-AUC 0.9951 as "the model is good" and nearly built a threshold on the score | Alerts scoring 0.9 to 0.99 are laundering 6.719% of the time, not ~95% |

The fix in each case was structural rather than "be more careful": an evaluator that cannot print the flattering number alone, medians reported beside every mean, a content-addressed sample that cannot drift.

## Limitations

- Synthetic benchmark. Real transaction data has late arrivals, corrections, KYC gaps and no clean labels. SAML-D has zero nulls and zero duplicates across 9.5M rows.
- The benchmark does not model threshold avoidance. Its "Structuring" label has a median amount of 4,800.35 and no relationship to any reporting threshold, so conclusions about structuring detection do not transfer to production data.
- Cold start is real. Every feature is built from an account's own history. Bucketing test positives by the sender's transaction count in the prior 30 days (`python/coldstart_check.py`, `outputs/coldstart_by_history.csv`):

  | Sender's transactions in prior 30 days | Positives | Recall at budget |
  |---|---|---|
  | 1 or fewer | 515 (18.15%) | 78.25% |
  | 2 to 3 | 579 | 92.23% |
  | 4 to 10 | 578 | 91.00% |
  | 11 to 30 | 687 | 88.50% |
  | over 30 | 478 | 85.56% |
  | overall | 2,837 | 87.42% |

  Accounts with almost no history are caught at 78.25% against 87.42% overall, and the model's median score on them is 0.971 versus about 0.998 elsewhere. The shape is a U: sparse history gives the model nothing to read, very dense history buries the signal. The sparse end is exactly where laundering onboards, so a production system would need a separate cold-start path (KYC attributes, peer-group baselines, counterparty risk) that does not exist here. The "never seen in training" slice has 11 positives and the "0 to 7 day account age" bucket has 4, so neither is quoted as a result.
- Explainability is partial. SHAP explains a single prediction, not the model's global decision boundary, and an attribution is a post-hoc description of a tree ensemble rather than its reasoning. A rule's logic is the reason; a model's attribution is a description of one.
- The model is uncalibrated. Grouped by dominant SHAP driver, alerts at effectively the same score range from 79.0% to 3.5% actual laundering rate. Calibration (isotonic or Platt, fitted on a validation split, never on test) is required before any threshold-based control is built on it.
- `hour_of_day` carries 1.22% of attribution. In real payments that can be a legitimate signal; in synthetic data it is at least as likely to be the generator's timestamp pattern. Small enough not to change the conclusions, disclosed because it would not transfer.
- Not production scale. DuckDB on a laptop stands in for a bank warehouse. The SQL is portable; streaming, latency and case-management integration are not addressed.

## Reproduce

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# Kaggle API token at ~/.kaggle/kaggle.json (chmod 600). The key never enters this repo.

.venv/bin/kaggle datasets download -d berkanoztas/synthetic-transaction-monitoring-dataset-aml -p data/raw
cd data/raw && unzip -o synthetic-transaction-monitoring-dataset-aml.zip && cd ../..

.venv/bin/python python/build_db.py                  # CSV -> DuckDB (~7s)
.venv/bin/python python/profile_stage1.py            # data profile
.venv/bin/python python/sweep_r01.py                 # the 90-combination grid
.venv/bin/python python/run_all_corrected.py         # rules at both grains
.venv/bin/python python/build_features.py            # 37 features (~36s)
.venv/bin/python python/train.py                     # baselines + models
.venv/bin/python python/train_v2_generalisation.py   # the leakage check
```

Or `make demo` for the whole pipeline.

## Status

Rules, features, models and validation are complete and reproducible. Outstanding: calibration of the score (challenge 05) and publishing the Tableau workbook (extracts and a build guide are in `tableau/`). The model ranks well enough to be useful as a triage queue; it is not ready to sit behind a score threshold.

A small browser-based companion, a rule-based monitoring console with alert triage and STR drafting on synthetic data, is in [aml-monitoring-console](https://github.com/herui03/aml-monitoring-console).

Personal project. Data: SAML-D (CC-BY-NC-SA-4.0), Oztas et al., not redistributed.

Herui Dou, MSc Business Analytics, NTU. [LinkedIn](https://www.linkedin.com/in/heruidou)
