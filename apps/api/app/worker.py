"""Persistent worker entrypoint for long-running resume jobs.

The API only commits queued work. This module is intentionally independent from
FastAPI so a process restart or a closed browser cannot cancel generation.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.database import make_engine
from app.services.bundle_service import process_queued_bundles


async def run_once(*, limit: int = 10) -> int:
    engine = make_engine(get_settings().resolved_database_url())
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with Session() as db:
            return await process_queued_bundles(db, limit=limit)
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Job Coach durable resume worker")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--once", action="store_true", help="处理一批任务后退出")
    args = parser.parse_args()
    if args.once:
        asyncio.run(run_once(limit=max(1, args.limit)))
        return
    while True:
        processed = asyncio.run(run_once(limit=max(1, args.limit)))
        if processed == 0:
            # A short idle interval avoids a busy loop while keeping queue
            # latency low. The API remains fully independent of this process.
            import time

            time.sleep(2)


if __name__ == "__main__":
    main()
