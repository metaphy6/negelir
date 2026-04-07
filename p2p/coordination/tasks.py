"""
Negelir P2P — Scrape task queue.
Phase 4: Generates and tracks daily scrape tasks.
Activates the scrape_tasks table from migrations/001_initial.sql.
"""

import uuid
import time
from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ScrapeTask:
    """A single scrape task for distributed coordination."""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    source: str = ""
    data_type: str = ""         # "standing", "fixture", "match_stats"
    target_id: int | None = None  # match_id for match_stats tasks
    status: TaskStatus = TaskStatus.PENDING
    assigned_node: str | None = None
    content_hash: str | None = None
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None


class TaskQueue:
    """
    In-memory task queue for distributed scrape coordination.
    Peers claim tasks atomically (pending → assigned).
    """

    def __init__(self):
        self._tasks: dict[str, ScrapeTask] = {}

    def add(self, task: ScrapeTask) -> str:
        """Add a task to the queue. Returns task_id."""
        self._tasks[task.task_id] = task
        return task.task_id

    def create_daily_tasks(self, recent_match_ids: list[int] | None = None) -> list[ScrapeTask]:
        """
        Generate pending scrape tasks for today's data needs.
        Returns list of created tasks.
        """
        tasks = [
            ScrapeTask(source="mackolik", data_type="standing"),
            ScrapeTask(source="mackolik", data_type="fixture"),
        ]
        for mid in (recent_match_ids or []):
            tasks.append(ScrapeTask(
                source="mackolik", data_type="match_stats", target_id=mid
            ))
        for t in tasks:
            self.add(t)
        return tasks

    def claim(self, task_id: str, peer_id: str) -> bool:
        """
        Atomic claim: pending → assigned.
        Returns False if task doesn't exist or is already claimed.
        """
        task = self._tasks.get(task_id)
        if task is None or task.status != TaskStatus.PENDING:
            return False
        task.status = TaskStatus.ASSIGNED
        task.assigned_node = peer_id
        return True

    def complete(self, task_id: str, data_hash: str) -> bool:
        """Mark task as completed with content hash."""
        task = self._tasks.get(task_id)
        if task is None or task.status != TaskStatus.ASSIGNED:
            return False
        task.status = TaskStatus.COMPLETED
        task.content_hash = data_hash
        task.completed_at = time.time()
        return True

    def fail(self, task_id: str) -> bool:
        """Mark task as failed."""
        task = self._tasks.get(task_id)
        if task is None:
            return False
        task.status = TaskStatus.FAILED
        return True

    def get_pending(self) -> list[ScrapeTask]:
        """Return all pending tasks."""
        return [t for t in self._tasks.values() if t.status == TaskStatus.PENDING]

    def get_task(self, task_id: str) -> ScrapeTask | None:
        return self._tasks.get(task_id)

    @property
    def size(self) -> int:
        return len(self._tasks)
