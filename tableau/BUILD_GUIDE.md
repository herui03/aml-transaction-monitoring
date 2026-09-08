# Tableau Public, build guide

**Why this is a guide and not a `.twbx`:** a Tableau workbook is a binary only Tableau Desktop can author. The data and the specification are the deliverable; you build the workbook. That is also the better outcome, when an interviewer asks how the dashboard was made, you made it.

**Target:** Tableau Public (free, native macOS). Publishing produces a public URL, put that link on the CV, not a screenshot.

> Tableau Public **saves your workbook publicly**. That is the point here (the link is the deliverable), but be aware there is no private option on the free tier. Nothing in these extracts is sensitive, SAML-D is a published synthetic benchmark, but form the habit of checking before you publish anything.

---

## The data

| File | Rows | Grain, one row per… |
|---|---|---|
| `gain_curve.csv` | 2,510 | approach × alerts-investigated |
| `alert_queue.csv` | 12,600 | alert (a scored transaction inside the budget) |
| `calibration.csv` | 5 | score bucket |
| `capacity_summary.csv` | 5 | approach |

Connect each as a **separate data source** (Data → New Data Source → Text file). Do **not** join them, they have different grains, and joining across grains is how you get silently wrong numbers. Regenerate any of them with `.venv/bin/python python/export_tableau.py`.

### Field reference

**`gain_curve.csv`**

| Field | Type | Meaning |
|---|---|---|
| `approach` | dimension | Rule engine (cannot rank) · Random ordering · Amount-only ranking · Logistic regression · Gradient-boosted model |
| `alerts_investigated` | measure → **convert to dimension** | x-axis: how many alerts a team works through |
| `laundering_caught` | measure | cumulative true positives found by that point |
| `pct_of_all_laundering` | measure | the same, as % of the 2,837 test cases |

**`alert_queue.csv`**

| Field | Type | Meaning |
|---|---|---|
| `rank` | dimension | 1 = highest risk score |
| `txn_id` | dimension | transaction identifier |
| `risk_score` | measure | model output, 0–1, **not a probability, see sheet 3** |
| `primary_driver` | dimension | the feature contributing most to this alert (SHAP) |
| `driver_contribution` | measure | that feature's SHAP value |
| `amount` | measure | transaction amount (UK pounds) |
| `outcome` | dimension | True positive · False positive |
| `actual_typology` | dimension | ground-truth label |

**`calibration.csv`**, `bucket` (dimension), `transactions`, `laundering`, `model_says_pct`, `actual_pct` (measures).

**`capacity_summary.csv`**, `approach` (dimension), `recall_at_capacity_pct` (measure).

---

## Colours, set these once, exactly

Tableau's default palette fails colourblind checks. Create a custom palette **before** building anything.

Edit `~/Documents/My Tableau Repository/Preferences.tps` and paste inside `<workbook>`:

```xml
<preferences>
  <color-palette name="AML Categorical" type="regular">
    <color>#2a78d6</color>  <!-- 1 blue    -->
    <color>#1baf7a</color>  <!-- 2 aqua    -->
    <color>#eda100</color>  <!-- 3 yellow  -->
    <color>#008300</color>  <!-- 4 green   -->
    <color>#4a3aa7</color>  <!-- 5 violet  -->
  </color-palette>
</preferences>
```

Restart Tableau. Assign hues **in this fixed order**, never let Tableau cycle or auto-assign.

This palette is validated: worst adjacent colourblind separation ΔE **24.2** (target ≥12). Two of the hues sit below 3:1 contrast against a white surface, which is why **every chart below carries direct labels**, identity must never rest on colour alone. That is a requirement, not a preference.

**Ink** (use for all text, never colour text with a series colour): primary `#0b0b0b`, secondary `#52514e`, axis/labels `#898781`, gridlines `#e1e0d9`.

---

## Sheet 1: "Detection at analyst capacity" (the headline)

**This chart is the entire project.** If a recruiter looks at one thing, it is this.

*Source: `gain_curve.csv`*

1. `alerts_investigated` → **Columns** (right-click → Convert to Dimension → Continuous)
2. `pct_of_all_laundering` → **Rows**
3. `approach` → **Colour**, palette **AML Categorical**, order: Gradient-boosted model → Logistic regression → Amount-only ranking → Random ordering → Rule engine
4. Marks: **Line**, size 2px
5. **Reference line, the point of the whole chart:** right-click x-axis → Add Reference Line → Constant → **12600** → Label: *"10 analysts × 15 alerts/day × 84 days"* → dashed, `#898781`
6. **Direct labels (required):** Label → Show mark labels → **Line Ends** → Label end of line only
7. Axis titles: *"Alerts investigated"* / *"% of all laundering caught"*
8. Title: **"At a real investigation budget, ranking is the product"**
9. Subtitle: *"9,504,852 transactions · 2,837 labelled cases · 84-day test period, never seen in training"*

**What it shows:** the gradient-boosted line reaches ~87% by the capacity marker while the rule engine's line is flat on the floor. The rule line is *straight*, that is not a rendering artefact, it is the finding: with no ranking, every alert is equally likely to be the real one, so yield grows linearly and hopelessly.

---

## Sheet 2: "Recall at capacity" (the one-glance version)

*Source: `capacity_summary.csv`*

1. `approach` → **Rows** · `recall_at_capacity_pct` → **Columns**
2. Marks: **Bar**. Sort descending by measure.
3. Label → Show mark labels (the number on every bar)
4. Colour: single `#2a78d6`. **Do not colour by approach**, one measure, one hue; the axis already carries identity.
5. Title: **"Same 12,600 investigations. Same data. 1,347× apart."**

| | |
|---|---|
| Gradient-boosted model | 87.42% |
| Logistic regression | 10.96% |
| Amount-only ranking | 2.29% |
| Random ordering | 0.42% |
| Rule engine (cannot rank) | 0.06% |

---

## Sheet 3: "The score is not a probability" (the honest one)

**Do not omit this sheet.** A dashboard that only shows the win is a sales deck. This one shows the model's defect, and it is the sheet an interviewer will respect.

*Source: `calibration.csv`*

1. `bucket` → **Columns** (order: 0.00–0.50, 0.50–0.90, 0.90–0.99, 0.99–0.999, 0.999–1.00)
2. `model_says_pct` and `actual_pct` → **Rows**, **on the same axis**. Measure Values / Measure Names, *not* a dual axis. Both are percentages; two y-scales here would be a lie.
3. Marks: **Circle**, size ≥8px. Colour: `model_says_pct` → `#898781` (muted, this is the claim), `actual_pct` → `#2a78d6` (the truth).
4. Add a **Line** to Detail joining the pair per bucket → a dumbbell. The gap *is* the chart.
5. Label the `actual_pct` mark only.
6. Title: **"What the model says, and what is true"**
7. Caption: *"Transactions scored 0.90–0.99 are laundering 6.719% of the time, not ~95%. The model ranks (ROC-AUC 0.9951) and does not calibrate. Every metric in this project is rank-based and unaffected, but no score threshold would be."*

---

## Sheet 4: "Alert queue" (what an analyst sees)

*Source: `alert_queue.csv`*

1. **Rows:** `rank`, `txn_id`, `primary_driver`, `actual_typology`
2. **Text:** `risk_score`, `amount`, `driver_contribution`
3. Filter: `rank` ≤ 200 (a table of 12,600 rows helps nobody)
4. `outcome` → **Colour**: True positive `#008300`, False positive `#898781`. Add `outcome` to **Text** as well, colour alone never carries meaning.
5. Fit: Entire View. Font: tabular figures for the numeric columns.
6. Title: **"The queue, in the order an analyst would work it"**
7. Caption: *"`primary_driver` is the feature contributing most to this alert (SHAP), the model's equivalent of a rule's trigger logic. It is what converts a score into something an MLRO can accept or reject."*

---

## Dashboard assembly

Size: **1200 × 1600**, Tiled (not floating, floating breaks on other screens).

```
┌──────────────────────────────────────────────────┐
│  Title + one-line thesis                         │
├──────────────────────────────────────────────────┤
│  Sheet 1, gain curve            (full width)    │  ← the argument
├────────────────────────┬─────────────────────────┤
│  Sheet 2, recall bars │  Sheet 3, calibration  │  ← the win, and the flaw
├────────────────────────┴─────────────────────────┤
│  Sheet 4, alert queue           (full width)    │  ← the product
├──────────────────────────────────────────────────┤
│  Footer: data source · licence · limitations     │
└──────────────────────────────────────────────────┘
```

**Footer text, do not cut this:**

> Data: SAML-D (Oztas et al.), a published synthetic AML benchmark, CC-BY-NC-SA-4.0. UK-denominated; no Singapore/SGD/MAS framing applies. Real bank AML data cannot be published, so the rules run against data they were not designed to trigger, which is what makes precision measurable. Known limitations: the score is not calibrated; accounts with no transaction history are caught at 78.25% vs 87.42% overall. Full method and five documented mistakes: <repo link>

**Dashboard title:** "AML Transaction Monitoring, rules vs. a scored model, measured at analyst capacity"
**Subtitle:** "Rule-based monitoring doesn't fail because rules are inaccurate. It fails because rules can't rank."

---

## Before publishing

- [ ] Every chart with ≥2 series has **direct labels** (two palette hues are sub-3:1 on white, labels are the mitigation, not optional)
- [ ] **No dual axis anywhere.** If two measures need different scales, that is two charts.
- [ ] Sheet 3 is present. The dashboard shows the defect, not only the win.
- [ ] Footer names the licence and the limitations.
- [ ] Tooltips read as sentences, not `SUM(pct_of_all_laundering): 87.42`.
- [ ] Open it on a phone-width window. Tiled layouts survive; floating ones don't.
- [ ] Numbers match the README: 87.42% / 19.683% / 0.9951 / 12,600 / 0.06%. **If a figure here disagrees with the README, the README is right and this workbook is stale**, regenerate the extracts.

---

## What this dashboard is not

It is not a monitoring tool. It has no live connection, no refresh, no case management. It is **the evidence for one argument**, laid out so the argument can be checked: at a fixed investigation budget, ranking beats detection, and the model that ranks best cannot yet be trusted to tell you what its numbers mean.
