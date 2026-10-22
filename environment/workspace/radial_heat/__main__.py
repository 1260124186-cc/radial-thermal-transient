import json
import sys
from pathlib import Path

from .solver import simulate


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: python -m radial_heat input.json output.json", file=sys.stderr)
        return 2
    source, target = Path(sys.argv[1]), Path(sys.argv[2])
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
        result = simulate(data)
        payload = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    except (OSError, ValueError, TypeError, KeyError, ZeroDivisionError, OverflowError) as exc:
        print(f"calculation failed: {exc}", file=sys.stderr)
        return 1
    target.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
