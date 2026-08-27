VALIDATOR := vendor/gtfs-validator-8.0.1-cli.jar
CLAIMS    := fixtures/claims/sample_agency.json
PY        := .venv/bin/python

.PHONY: setup build validate ambiguity test clean

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

clean:
	rm -rf out __pycache__ .pytest_cache
