#!/bin/bash
set -u

reward_file=/logs/verifier/reward.txt
mkdir -p /logs/verifier
echo "0" > "$reward_file"

write_reward_zero() { echo "0" > "$reward_file"; }
trap 'write_reward_zero; exit 130' INT TERM HUP

if ! python -m pip install --user --no-cache-dir --disable-pip-version-check \
  --require-hashes --only-binary=:all: -r /tests/requirements.txt; then
  write_reward_zero
  exit 0
fi

cd /workspace || exit 0
score=0
for spec in "c1 1" "c2 1" "c3 1" "c4 2" "c5 3" "e2e 2"; do
  group=${spec%% *}
  weight=${spec##* }
  if python -m pytest -q /tests/test_outputs.py -k "test_${group}_" \
      > "/logs/verifier/${group}.log" 2>&1; then
    score=$((score + weight))
  fi
done
python - "$score" "$reward_file" <<'PY'
import sys
score, path = int(sys.argv[1]), sys.argv[2]
with open(path, "w", encoding="utf-8") as out:
    out.write(f"{score / 10:.6f}\n")
PY
trap - INT TERM HUP
exit 0
