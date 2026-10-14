"""Single API ownership with transaction fencing and fail-closed health checks."""

import asyncio
import logging
from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
OWNER_LOCK = 746238102
FENCE_LOCK = 746238103
OWNS = text("""
SELECT EXISTS (
    SELECT 1 FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid
    WHERE locktype = 'advisory' AND granted
    AND l.pid = :pid AND a.backend_start = :started
    AND classid = 0 AND objid = :key AND objsubid = 1
    AND database = (SELECT oid FROM pg_database WHERE datname = current_database())
)
""")


class ApiOwnership:
    def __init__(self, engine):
        self.engine = engine
        self.guard = None
        self.pid = None
        self.started = None
        self.alive = False

    async def acquire(self):
        self.guard = await self.engine.connect()
        # Drain earlier owner's admitted transactions before recovery/new work.
        await self.guard.execute(text(f"SELECT pg_advisory_xact_lock({FENCE_LOCK})"))
        if not await self.guard.scalar(text(f"SELECT pg_try_advisory_lock({OWNER_LOCK})")):
            raise RuntimeError("Another API process owns this database; run with --workers 1")
        self.pid = await self.guard.scalar(text("SELECT pg_backend_pid()"))
        self.started = await self.guard.scalar(
            text("SELECT backend_start FROM pg_stat_activity WHERE pid = pg_backend_pid()")
        )
        await self.guard.commit()
        self.alive = True

    def fence_sessions(self, sessions):
        owner = self

        class OwnedSession(Session):
            pass

        @event.listens_for(OwnedSession, "after_begin")
        def fence(session, transaction, connection):
            if not owner.alive:
                raise HTTPException(503, "API ownership lost; restart this process")
            connection.execute(text(f"SELECT pg_advisory_xact_lock_shared({FENCE_LOCK})"))
            if not connection.scalar(
                OWNS, dict(pid=owner.pid, started=owner.started, key=OWNER_LOCK)
            ):
                owner.alive = False
                raise HTTPException(503, "API ownership lost; restart this process")
            # Shared lock is held through COMMIT/ROLLBACK. A successor must wait.

        sessions.configure(sync_session_class=OwnedSession)

    async def check(self):
        if not self.alive:
            return False
        try:
            async with asyncio.timeout(3):
                async with self.engine.connect() as conn:
                    if not await conn.scalar(
                        OWNS, dict(pid=self.pid, started=self.started, key=OWNER_LOCK)
                    ):
                        self.alive = False
        except Exception:
            self.alive = False
        return self.alive

    async def monitor(self, chat):
        while await self.check():
            await asyncio.sleep(1)
        logger.error("API database ownership lost; refusing work until process restart")
        await chat.close()

    async def close(self):
        self.alive = False
        if self.guard is not None:
            try:
                if self.guard.in_transaction():
                    await self.guard.rollback()
                await self.guard.execute(text(f"SELECT pg_advisory_unlock({OWNER_LOCK})"))
            except Exception:
                # A terminated guard connection is the failure we are handling.
                await self.guard.invalidate()
            finally:
                await self.guard.close()
