from __future__ import annotations
import asyncio
import time
from typing import AsyncIterator, Callable, Any
from models.events import StageEvent, VerificationSnapshot


class StageEmitter:
    """Wraps a stage function and emits start/complete/error events."""

    def __init__(self, job_id: str, pipeline: str, publish: Callable):
        self.job_id = job_id
        self.pipeline = pipeline
        self._publish = publish

    async def emit(
        self,
        stage_id: int,
        stage_name: str,
        payload: Any,
        status: str = "completed",
        duration_ms: float | None = None,
        verification: VerificationSnapshot | None = None,
    ):
        event = StageEvent(
            job_id=self.job_id,
            pipeline=self.pipeline,
            stage_id=stage_id,
            stage_name=stage_name,
            status=status,
            timestamp_ms=time.time() * 1000,
            duration_ms=duration_ms,
            payload=payload,
            verification=verification,
        )
        await self._publish(event.model_dump())

    def _stage_cache_key(self, stage_id: int) -> str:
        """Namespaced key so Mode A and Mode B don't collide on stage_id."""
        return f"_stage_done_{self.pipeline}_{stage_id}"

    async def _emit_resumed(
        self,
        stage_id: int,
        stage_name: str,
        cached: dict,
    ) -> "StageResult":
        """Replay a cached stage completion as if it had just run."""
        from models.events import VerificationSnapshot
        payload = cached.get("payload") or {}
        duration_ms = cached.get("duration_ms", 0.0)
        verif: VerificationSnapshot | None = None
        v_dump = cached.get("verification")
        if v_dump:
            try:
                verif = VerificationSnapshot(**v_dump)
            except Exception:
                verif = None
        # Mark the payload so the UI can show "resumed from cache" if desired
        replayed = {**payload, "_resumed_from_cache": True} if isinstance(payload, dict) else payload
        await self.emit(stage_id, stage_name, {}, status="started")
        await self.emit(stage_id, stage_name, replayed, "completed", duration_ms, verif)
        return StageResult(payload=payload, verification=verif)

    async def run_stage(
        self,
        stage_id: int,
        stage_name: str,
        coro,
        *,
        heartbeat_interval: float = 30.0,
        force: bool = False,
        progress_info: Callable[[float], dict | None] | None = None,
    ) -> Any:
        """Run a stage coroutine and emit start/heartbeat/complete/error events.

        Resume semantics: if this stage already completed for `job_id` (cache
        key persisted to disk), replay the cached payload and skip the coro.
        Caller can pass `force=True` to re-run regardless.

        For long-running stages (e.g. Docling parse, large embedding batches) we
        fire a small `running` event every `heartbeat_interval` seconds so the
        WebSocket stays warm and the UI can show "still working, Ns elapsed".
        """
        # ── Resume check ────────────────────────────────────────────────────
        # Skip if this stage's payload was already persisted (backend reload
        # mid-run, or re-opening an old job). Downstream stages can still read
        # whatever intermediate cache keys the previous run wrote — those live
        # on disk via services.job_cache.
        if not force:
            from services import job_cache
            cached = job_cache.get(self.job_id, self._stage_cache_key(stage_id))
            if isinstance(cached, dict) and cached.get("status") == "completed":
                # Cancel any caller-supplied coro to avoid "coroutine never awaited" warnings
                if hasattr(coro, "close"):
                    coro.close()
                return await self._emit_resumed(stage_id, stage_name, cached)

        await self.emit(stage_id, stage_name, {}, status="started")
        t0 = time.perf_counter()

        async def _heartbeat():
            try:
                while True:
                    await asyncio.sleep(heartbeat_interval)
                    elapsed_ms = (time.perf_counter() - t0) * 1000
                    payload: dict = {"_heartbeat": True, "elapsed_ms": round(elapsed_ms, 0)}
                    # Stage-specific progress (e.g. "page 137/250 estimated")
                    if progress_info is not None:
                        try:
                            info = progress_info(elapsed_ms)
                            if info:
                                payload.update(info)
                        except Exception:
                            pass
                    # status='running' with heartbeat marker — frontend's
                    # applyEvent ignores payload updates for non-completed
                    # events, so this can't clobber real stage output.
                    await self.emit(
                        stage_id, stage_name, payload,
                        status="running",
                        duration_ms=elapsed_ms,
                    )
            except asyncio.CancelledError:
                return

        hb_task = asyncio.create_task(_heartbeat())
        try:
            result = await coro
            duration_ms = (time.perf_counter() - t0) * 1000
            payload = result.payload if hasattr(result, "payload") else result
            verification = result.verification if hasattr(result, "verification") else None
            await self.emit(stage_id, stage_name, payload, "completed", duration_ms, verification)

            # Persist for resume — if the backend reloads or crashes, the next
            # run of this job_id will skip this stage and replay this payload.
            try:
                from services import job_cache
                verif_dump = None
                if verification is not None and hasattr(verification, "model_dump"):
                    verif_dump = verification.model_dump()
                job_cache.put(self.job_id, self._stage_cache_key(stage_id), {
                    "status":       "completed",
                    "payload":      payload,
                    "duration_ms":  duration_ms,
                    "verification": verif_dump,
                })
            except Exception:
                # Persistence failure isn't fatal — the stage still completed.
                pass

            return result
        except Exception as exc:
            duration_ms = (time.perf_counter() - t0) * 1000
            await self.emit(stage_id, stage_name, {"error": str(exc)}, "error", duration_ms)
            raise
        finally:
            hb_task.cancel()
            # Swallow the cancellation cleanly so it doesn't propagate
            try:
                await hb_task
            except (asyncio.CancelledError, Exception):
                pass


class StageResult:
    def __init__(self, payload: Any, verification: VerificationSnapshot | None = None):
        self.payload = payload
        self.verification = verification
