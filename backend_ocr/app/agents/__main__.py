"""Launch one agent by name from the repository root."""

import argparse
import asyncio
from contextlib import AsyncExitStack
import json
import signal
from uuid import UUID

from .ownership import WORKER_AGENTS, is_external


async def run_worker(name):
    from db import close_pool, get_pool
    from .workers import LOCKS, operations

    # SIGTERM is sent by process supervisors. Let cancellation drain the workers.
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    try:
        loop.add_signal_handler(signal.SIGTERM, task.cancel)
    except (NotImplementedError, RuntimeError):
        pass

    async with AsyncExitStack() as stack:
        pool = await get_pool()
        stack.push_async_callback(close_pool)
        conn = await stack.enter_async_context(pool.acquire())
        key = LOCKS[name]
        if not await conn.fetchval("SELECT pg_try_advisory_lock($1)", key):
            raise SystemExit(f"Another standalone {name} agent owns this database lock.")
        stack.push_async_callback(conn.execute, "SELECT pg_advisory_unlock($1)", key)
        worker_operations = tuple(operations(name))
        tasks = [asyncio.create_task(operation()) for operation in worker_operations]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for worker in done:
                worker.result()
            raise RuntimeError(f"The {name} agent exited unexpectedly")
        finally:
            for worker in tasks:
                worker.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agent", choices=(*WORKER_AGENTS, "analytics"))
    parser.add_argument("--tenant", type=UUID, help="Analytics tenant")
    parser.add_argument("--brand", type=UUID, help="Optional analytics brand")
    args = parser.parse_args()
    if args.agent == "analytics":
        if not args.tenant:
            parser.error("analytics requires --tenant")
        from .analytics import activity_report

        print(json.dumps(activity_report(str(args.tenant), str(args.brand) if args.brand else None)))
        return
    if args.tenant or args.brand:
        parser.error("Use PIPELINE_TENANT_IDS where supported by the underlying worker")
    if not is_external(args.agent):
        parser.error(f"Assign {args.agent} through ONSUMM_EXTERNAL_AGENTS before launching it")
    try:
        asyncio.run(run_worker(args.agent))
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass


if __name__ == "__main__":
    main()
