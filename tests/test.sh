#!/bin/bash
set -u

REWARD_FILE=/logs/verifier/reward.txt
JUNIT_FILE=/logs/verifier/junit.xml
mkdir -p /logs/verifier
echo "0" > "$REWARD_FILE"

finalized=0
write_zero() { echo "0" > "$REWARD_FILE" 2>/dev/null || true; }
on_signal() { write_zero; exit 130; }
on_exit() { if [ "$finalized" -eq 0 ]; then write_zero; fi; }
trap 'on_exit' EXIT
trap 'on_signal' INT TERM HUP

if ! python -m pip install --user --no-cache-dir --disable-pip-version-check \
  --no-index --find-links /tests/wheels/ \
  --require-hashes --only-binary=:all: -r /tests/requirements.txt; then
  write_zero
  exit 0
fi

cd /workspace || { write_zero; exit 0; }

# The outer timeout keeps a hung verifier from stalling the run. The score is
# computed from the junit report, never from this command's exit code.
timeout 300 python -m pytest -v /tests/test_outputs.py --junitxml="$JUNIT_FILE" 2>&1 \
  | tee /logs/verifier/pytest.log || true

if [ ! -s "$JUNIT_FILE" ]; then
  echo "0" > "$REWARD_FILE"
  chmod 0444 "$REWARD_FILE"
  finalized=1
  exit 0
fi

python - "$JUNIT_FILE" "$REWARD_FILE" <<'PY'
import os
import sys
import xml.etree.ElementTree as ET

junit, reward = sys.argv[1], sys.argv[2]
GROUPS = {"c1": 1, "c2": 1, "c3": 1, "c4": 2, "c5": 3, "e2e": 2}


def emit(value):
    with open(reward, "w", encoding="utf-8") as handle:
        handle.write(f"{value:.6f}\n")
    os.chmod(reward, 0o444)


# A missing or empty report means pytest never completed (for example the
# runner was replaced or killed); record INCOMPLETE and score zero.
if not os.path.isfile(junit) or os.path.getsize(junit) == 0:
    print("INCOMPLETE: pytest report missing or empty", file=sys.stderr)
    emit(0.0)
    raise SystemExit(0)

try:
    root = ET.parse(junit).getroot()
except ET.ParseError:
    print("INCOMPLETE: pytest report could not be parsed", file=sys.stderr)
    emit(0.0)
    raise SystemExit(0)

passed = {}
for case in root.iter("testcase"):
    name = case.get("name", "")
    if "::" in name:
        name = name.rsplit("::", 1)[-1]
    passed[name] = not any(child.tag in ("failure", "error") for child in case)

earned = 0
for group, weight in GROUPS.items():
    names = [name for name in passed if name.startswith("test_" + group + "_")]
    if names and all(passed[name] for name in names):
        earned += weight

emit(min(1.0, earned / 10.0))
PY

finalized=1
exit 0
