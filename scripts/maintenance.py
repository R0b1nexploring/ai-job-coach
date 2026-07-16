#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.database import SessionLocal  # noqa: E402
from app.services.maintenance_service import run_maintenance  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="预览或执行账号保留期清理与过期岗位标记。")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="真正执行清理；省略时只输出候选数量，不修改数据。",
    )
    args = parser.parse_args()
    with SessionLocal() as db:
        result = run_maintenance(db, execute=args.execute)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
