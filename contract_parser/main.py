from __future__ import annotations

import json
import sys

from contract_parser.pipeline import run_pipeline


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python -m contract_parser.main <contract.pdf>")
        return 1
    result = run_pipeline(sys.argv[1])
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
