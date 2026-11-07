"""Démo de l'exécution H : une session courte, en lecture seule, après vérification du quota.

Usage, depuis la racine du dépôt :
    python -m scripts.h_demo
    python -m scripts.h_demo --steer   # pause, reprise et message pendant la session
"""

import argparse
import asyncio
import time
import uuid

from runai.h import HRunner
from runai.h.events import event_label, event_summary
from runai.models import StepKind

TASK = (
    "Open {url} and read the page. Answer with the exact page title and the text of the first link. "
    "This is a read-only task: do not click anything that submits data."
)


async def steer(run, timings: dict[str, float]) -> None:
    await run.wait_for_status({"running"}, timeout_s=120)
    await asyncio.sleep(5)
    started = time.monotonic()
    await run.pause()
    timings["pause_request_s"] = time.monotonic() - started
    try:
        timings["pause_to_paused_s"] = timings["pause_request_s"] + await run.wait_for_status(
            {"paused"} | {"completed", "failed", "idle"}, timeout_s=60, poll_s=0.5
        )
    finally:
        timings["status_after_pause"] = run.status
    if run.status == "paused":
        await asyncio.sleep(3)
        await run.resume()
        await run.send_message("Reminder: answer with the page title only, then stop.")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://example.com")
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--steer", action="store_true", help="Teste pause, reprise et message")
    parser.add_argument("--start-url", action="store_true", help="Démarre le navigateur directement sur --url")
    args = parser.parse_args()

    async with HRunner(max_concurrency=1, quota_timeout_s=0) as runner:
        quota = await runner.quota()
        print(f"Quota H : {quota.active}/{quota.limit} actifs, {quota.available} libres ({quota.scope})")
        if quota.available < 1:
            raise SystemExit("Aucun slot H libre : démo annulée.")

        mission_id = f"h-demo-{uuid.uuid4().hex[:8]}"
        started = time.monotonic()
        run = await runner.start(
            StepKind.search, TASK.format(url=args.url), mission_id=mission_id,
            max_steps=args.max_steps,
            start_url=args.url if args.start_url else None,
        )
        print(f"Session : {run.id}\nAgent View : {run.agent_view_url}")

        def on_event(event: dict) -> None:
            if event.get("type") == "LiveViewUrlEvent":
                print(f"Vue live : {run.live_view_url}")
            summary = event_summary(event)
            print(f"[{time.monotonic() - started:6.1f}s] {event_label(event)}" + (f" : {summary}" if summary else ""))

        timings: dict[str, float] = {}
        steering = asyncio.create_task(steer(run, timings)) if args.steer else None
        async with run:
            result = await run.wait(on_event=on_event, timeout_s=args.timeout)
        if steering is not None:
            steering.cancel()
            await asyncio.gather(steering, return_exceptions=True)

        print(f"\nDurée : {time.monotonic() - started:.1f}s")
        if timings:
            print(f"Pilotage : {timings}")
        print(result.model_dump_json(indent=2))
        print(f"Trace : {run.trace.path}")


if __name__ == "__main__":
    asyncio.run(main())
