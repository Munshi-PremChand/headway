#!/usr/bin/env python3
"""Print a gtfs-validator report and act as the publish gate.

Exit code 1 if any ERROR-severity notice stands. This is a GATE, not a score:
it can only ever read zero at publish time, so it proves conformance, never
correctness. The correctness number is cell-level fidelity against a frozen
transcription of the source document.
"""
import json
import sys

report = json.load(open(sys.argv[1]))
notices = report.get("notices", [])

totals: dict[str, int] = {}
for n in notices:
    totals[n["severity"]] = totals.get(n["severity"], 0) + n["totalNotices"]

for n in sorted(notices, key=lambda x: (x["severity"], x["code"])):
    print(f"  [{n['severity']:>7}] {n['code']} x{n['totalNotices']}")

errs = totals.get("ERROR", 0)
print(f"\nERROR={errs}  WARNING={totals.get('WARNING', 0)}  INFO={totals.get('INFO', 0)}")
print("PUBLISH GATE:", "OPEN" if errs == 0 else "CLOSED")
sys.exit(1 if errs else 0)
