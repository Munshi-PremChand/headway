VALIDATOR := vendor/gtfs-validator-8.0.1-cli.jar
CLAIMS    := fixtures/claims/sample_agency.json
PY        := .venv/bin/python

ASTC := https://st.redbus.in/Images/WL/ASTC/schedules_new/Guwahati_division.pdf

.PHONY: setup build validate ambiguity test calibrate fixture pipeline multipage photocopy clean

setup:
	python3 -m venv .venv && .venv/bin/pip install -q pytest
	@test -f $(VALIDATOR) || $(PY) -c "import urllib.request;urllib.request.urlretrieve('https://github.com/MobilityData/gtfs-validator/releases/download/v8.0.1/gtfs-validator-8.0.1-cli.jar','$(VALIDATOR)')"

build:
	$(PY) scripts/build_feed.py $(CLAIMS) out/gtfs.zip

# The publish gate. Exits non-zero if any ERROR-severity notice stands.
validate: build
	@rm -rf out/report
	docker run --rm -v "$(PWD)":/w -w /w eclipse-temurin:21-jre \
	  java -jar $(VALIDATOR) -i out/gtfs.zip -o out/report >/dev/null 2>&1
	@$(PY) scripts/show_report.py out/report/report.json

ambiguity:
	$(PY) scripts/ambiguity_report.py $(CLAIMS)

test:
	$(PY) -m pytest tests -q

fixture:
	$(PY) scripts/make_fixture_timetable.py fixtures/scans

# Re-runs the thinking-level measurement against Vertex. Needs gcloud auth and
# a billing-enabled project. Withholds its verdict if any call fails.
calibrate:
	$(PY) scripts/calibrate_thinking.py 3

# The whole pipeline, live, against a real ASTC division page. Needs poppler
# (pdftoppm) and any one Gemini credential; an ADC file is NOT required — a
# `gcloud auth login` access token or a free AI Studio key both work.
# Exits non-zero unless the validator returns zero ERROR notices.
pipeline:
	$(PY) scripts/run_pipeline.py --pdf $(ASTC) --page 1 \
	    --profile astc_guwahati --json out/astc_ledger.json

# Pages 1-2, joining the service that spans the page break.
multipage:
	$(PY) scripts/run_multipage.py --pages 1-2 --json out/multipage.json

# The claim the project rests on: no text layer at all.
photocopy:
	$(PY) scripts/photocopy_test.py --level 2

clean:
	rm -rf out __pycache__ .pytest_cache .tmp
