"""
Module de File d'Attente Persistante et Résilience Hors-Ligne (Store & Forward).

Permet à un nœud de mettre en mémoire tampon sur disque les tâches destinées à un pair
actuellement hors-ligne ou injoignable, et de les délivrer automatiquement dès sa reconnexion.
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional


@dataclass
class QueuedTask:
    task_id: str
    target_node: str
    skill: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    status: str  # 'PENDING', 'SUCCESS', 'FAILED'
    created_at: float
    next_retry_at: float
    last_error: Optional[str] = None


class PersistentTaskQueue:
    """Gestionnaire de file d'attente persistante SQLite avec retry exponentiel."""

    def __init__(self, db_path: str | Path = ":memory:"):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS task_spool (
                    task_id TEXT PRIMARY KEY,
                    target_node TEXT NOT NULL,
                    skill TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    attempts INTEGER DEFAULT 0,
                    max_attempts INTEGER DEFAULT 5,
                    status TEXT DEFAULT 'PENDING',
                    created_at REAL,
                    next_retry_at REAL,
                    last_error TEXT
                )
            """)
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_spool_target ON task_spool(target_node, status)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_spool_retry ON task_spool(status, next_retry_at)")

    def enqueue(
        self,
        target_node: str,
        skill: str,
        payload: dict[str, Any],
        max_attempts: int = 5,
        delay_sec: float = 0.0,
    ) -> str:
        """Ajoute une tâche dans la file d'attente sur disque."""
        now = time.time()
        raw = f"{target_node}:{skill}:{now}:{json.dumps(payload, sort_keys=True)}"
        task_id = "task_" + hashlib.sha256(raw.encode()).hexdigest()[:12]

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO task_spool (
                    task_id, target_node, skill, payload, attempts, max_attempts,
                    status, created_at, next_retry_at
                ) VALUES (?, ?, ?, ?, 0, ?, 'PENDING', ?, ?)
                """,
                (task_id, target_node, skill, json.dumps(payload), max_attempts, now, now + delay_sec),
            )
        return task_id

    def get_pending_for_node(self, target_node: str) -> list[QueuedTask]:
        """Récupère les tâches prêtes à être expédiées à un nœud actif."""
        now = time.time()
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT task_id, target_node, skill, payload, attempts, max_attempts, status, created_at, next_retry_at, last_error
            FROM task_spool
            WHERE target_node = ? AND status = 'PENDING' AND next_retry_at <= ?
            ORDER BY created_at ASC
            """,
            (target_node, now),
        )
        tasks = []
        for r in cursor.fetchall():
            tasks.append(QueuedTask(
                task_id=r[0],
                target_node=r[1],
                skill=r[2],
                payload=json.loads(r[3]),
                attempts=r[4],
                max_attempts=r[5],
                status=r[6],
                created_at=r[7],
                next_retry_at=r[8],
                last_error=r[9],
            ))
        return tasks

    def mark_success(self, task_id: str):
        """Marque une tâche comme livrée et exécutée avec succès."""
        with self.conn:
            self.conn.execute("UPDATE task_spool SET status = 'SUCCESS' WHERE task_id = ?", (task_id,))

    def mark_failure(self, task_id: str, error_msg: str, backoff_base_sec: float = 2.0):
        """Enregistre un échec et planifie la tentative suivante avec backoff exponentiel."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT attempts, max_attempts FROM task_spool WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        if not row:
            return

        attempts, max_attempts = row[0] + 1, row[1]
        now = time.time()

        if attempts >= max_attempts:
            status = 'FAILED'
            next_retry = now + 999999
        else:
            status = 'PENDING'
            next_retry = now + (backoff_base_sec ** attempts)

        with self.conn:
            self.conn.execute(
                """
                UPDATE task_spool
                SET attempts = ?, status = ?, last_error = ?, next_retry_at = ?
                WHERE task_id = ?
                """,
                (attempts, status, error_msg, next_retry, task_id),
            )

    async def flush_node(self, target_node: str, dispatcher: Callable[[str, dict], Any]) -> list[dict[str, Any]]:
        """Tente d'expédier toutes les tâches en attente pour un nœud donné."""
        tasks = self.get_pending_for_node(target_node)
        results = []

        for t in tasks:
            try:
                res = await dispatcher(t.skill, t.payload)
                self.mark_success(t.task_id)
                results.append({"task_id": t.task_id, "ok": True, "result": res})
            except Exception as e:
                err_str = str(e)
                self.mark_failure(t.task_id, err_str)
                results.append({"task_id": t.task_id, "ok": False, "error": err_str})

        return results

    def stats(self) -> dict[str, int]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT status, COUNT(*) FROM task_spool GROUP BY status")
        counts = {"PENDING": 0, "SUCCESS": 0, "FAILED": 0}
        for status, count in cursor.fetchall():
            counts[status] = count
        return counts

    def close(self):
        self.conn.close()
