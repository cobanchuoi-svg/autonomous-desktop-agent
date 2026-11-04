"""
Single-Writer Database Architecture.
Guarantees sequential writes to SQLite through a dedicated thread and queue,
completely eliminating SQLite lock contention across Agent, GUI, and Teacher AI.
Conforms to P1 #3 requirement.
"""

import asyncio
from concurrent.futures import Future
from pathlib import Path
import queue
import sqlite3
import threading
from typing import Any, Dict, Optional, Tuple
from agent.logger import logger


class DBWriteTask:
    """Encapsulates a database write request."""

    def __init__(self, sql: str, params: Tuple[Any, ...] = (), return_rowid: bool = False):
        self.sql = sql
        self.params = params
        self.return_rowid = return_rowid
        self.future: Future = Future()


class DatabaseWriter:
    """Dedicated background writer thread executing all mutating SQLite operations sequentially."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._queue: queue.Queue[Optional[DBWriteTask]] = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._is_running = False
        self.start()

    def start(self) -> None:
        if self._is_running:
            return
        self._is_running = True
        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="DBWriterThread")
        self._thread.start()
        logger.info(f"[DBWriter] Single writer thread started for {self.db_path.name}")

    def _worker_loop(self) -> None:
        """Sequential single-threaded write loop."""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")

        while self._is_running or not self._queue.empty():
            try:
                task = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if task is None:
                break

            try:
                cursor = conn.cursor()
                cursor.execute(task.sql, task.params)
                conn.commit()
                res = cursor.lastrowid if task.return_rowid else cursor.rowcount
                task.future.set_result(res)
            except Exception as e:
                conn.rollback()
                logger.error(f"[DBWriter] Write error executing '{task.sql[:50]}...': {e}")
                task.future.set_exception(e)
            finally:
                self._queue.task_done()

        try:
            conn.close()
        except Exception:
            pass
        logger.info("[DBWriter] Single writer thread stopped cleanly.")

    def execute_write_sync(self, sql: str, params: Tuple[Any, ...] = (), return_rowid: bool = False) -> Any:
        """Enqueue a write and wait synchronously for result (thread-safe)."""
        task = DBWriteTask(sql=sql, params=params, return_rowid=return_rowid)
        self._queue.put(task)
        return task.future.result(timeout=10.0)

    async def execute_write_async(self, sql: str, params: Tuple[Any, ...] = (), return_rowid: bool = False) -> Any:
        """Enqueue a write and await result asynchronously without blocking event loop."""
        task = DBWriteTask(sql=sql, params=params, return_rowid=return_rowid)
        self._queue.put(task)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, task.future.result, 10.0)

    def stop(self) -> None:
        """Orderly flush and shutdown."""
        if not self._is_running:
            return
        self._is_running = False
        self._queue.put(None)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
