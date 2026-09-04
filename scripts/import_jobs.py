#!/usr/bin/env python3
import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))


def main():
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models.entities import User
    from app.services.job_importer import import_campus_announcements, read_campus_rows

    parser = argparse.ArgumentParser(description="预览或导入校招简章（岗位 + 投递入口）。")
    parser.add_argument("file", type=Path, help="CSV 或 XLSX；原始文件不得提交 Git。")
    parser.add_argument("--execute", action="store_true", help="真正写入；省略时只输出统计。")
    parser.add_argument("--source", default="operator_import", help="不含个人信息的来源标签。")
    parser.add_argument("--owner-user-id", default=None, help="可选：设为指定用户私有；默认共享。")
    parser.add_argument("--created-by-user-id", default=None, help="写入岗位时的创建者；默认管理员。")
    parser.add_argument("--mapping", type=Path, help="可选 JSON：canonical_field 到原始列名。")
    args = parser.parse_args()
    mapping = json.loads(args.mapping.read_text(encoding="utf-8")) if args.mapping else None
    modified_at = datetime.fromtimestamp(args.file.stat().st_mtime, tz=UTC)
    rows = read_campus_rows(args.file)
    with SessionLocal() as db:
        created_by = args.created_by_user_id
        if created_by is None:
            admin = db.scalar(select(User).where(User.role == "admin").order_by(User.created_at))
            created_by = admin.id if admin else None
        result = import_campus_announcements(
            db,
            rows,
            source=args.source,
            execute=args.execute,
            owner_user_id=args.owner_user_id,
            created_by=created_by,
            column_map=mapping,
            default_source_updated_at=modified_at,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
