from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable, Coroutine


class AsyncLoopThread:
    """Runs a dedicated asyncio event loop in a background daemon thread."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, name="TkAsyncioLoop", daemon=True)
        self.thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run_coroutine(
        self,
        coro: Coroutine[Any, Any, Any],
        callback: Callable[[Any], None] | None = None,
        tk_root: Any | None = None,
    ) -> asyncio.Future:
        """Schedules a coroutine on the background event loop."""
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)

        if callback:
            def _done_cb(fut: asyncio.Future) -> None:
                try:
                    res = fut.result()
                except Exception as exc:
                    res = exc

                if tk_root:
                    tk_root.after(0, lambda: callback(res))
                else:
                    callback(res)

            future.add_done_callback(_done_cb)

        return future

    def stop(self) -> None:
        """Stops the event loop."""
        if self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
