from __future__ import annotations

import argparse
import json

from .schemas import RunRequest
from .workflow import RunService


def main():
    parser = argparse.ArgumentParser(description="Generate an auditable investment research draft")
    parser.add_argument("company_name")
    parser.add_argument("--ticker")
    args = parser.parse_args()
    service = RunService()
    run_id = service.store.create(RunRequest(company_name=args.company_name, ticker=args.ticker))
    service.run(run_id)
    row = service.store.get(run_id)
    print(json.dumps({"run_id": run_id, "status": row["status"], "error": row["error"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
