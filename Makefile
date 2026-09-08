# AML Transaction Monitoring - reproducible pipeline.
# Requires ~/.kaggle/kaggle.json (mode 600). The key never enters this repo.
PY := .venv/bin/python
KG := .venv/bin/kaggle
DS := berkanoztas/synthetic-transaction-monitoring-dataset-aml

.PHONY: demo venv data db profile rules features model validate clean

demo: venv data db profile rules features model validate   ## full pipeline, cold start to results

venv:
	python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt

data:
	@test -f data/raw/SAML-D.csv || ( mkdir -p data/raw && \
	  $(KG) datasets download -d $(DS) -p data/raw && \
	  cd data/raw && unzip -o -q synthetic-transaction-monitoring-dataset-aml.zip )

db:       ; $(PY) python/build_db.py                    # 950MB CSV -> DuckDB (~7s)
profile:  ; $(PY) python/profile_stage1.py; $(PY) python/profile_stage1b.py; $(PY) python/sanity_medians.py
rules:    ; $(PY) python/sweep_r01.py; $(PY) python/run_all_corrected.py
features: ; $(PY) python/build_features.py              # 37 features (~36s)
model:    ; $(PY) python/train.py
validate: ; $(PY) python/train_v2_generalisation.py; $(PY) python/coldstart_check.py; $(PY) python/leakage_check.py

clean:    ; rm -rf data/processed outputs/*.npy outputs/*.pkl outputs/*.parquet
