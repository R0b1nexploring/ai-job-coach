#!/usr/bin/env python3
import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))


def main():
    from app.database import SessionLocal
    from app.services.channel_importer import import_channels, read_channel_rows

    parser = argparse.ArgumentParser(description="预览或执行公司投递渠道导入。")
    parser.add_argument(
        "file", type=Path, help="CSV 或 XLSX 文件；原始文件不得提交 Git。"
    )
    parser.add_argument(
        "--execute", action="store_true", help="真正写入；省略时只输出统计。"
    )
    parser.add_argument(
        "--source", default="operator_import", help="不含个人信息的来源标签。"
    )
    parser.add_argument(
        "--owner-user-id", default=None, help="可选：将导入行设为指定用户私有。"
    )
    parser.add_argument(
        "--mapping",
        type=Path,
        help="可选 JSON：canonical_field 到原始列名的映射。",
    )
    args = parser.parse_args()
    mapping = (
        json.loads(args.mapping.read_text(encoding="utf-8")) if args.mapping else None
    )
    modified_at = datetime.fromtimestamp(args.file.stat().st_mtime, tz=UTC)
    rows = read_channel_rows(args.file)
    with SessionLocal() as db:
        result = import_channels(
            db,
            rows,
            source=args.source,
            execute=args.execute,
            owner_user_id=args.owner_user_id,
            column_map=mapping,
            default_source_updated_at=modified_at,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
