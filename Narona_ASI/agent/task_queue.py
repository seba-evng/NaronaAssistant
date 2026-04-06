"""
agent/task_queue.py – Cola de tareas para NARONA.
Basado en el patrón de FatihMakes/Mark-XXX.
"""

import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from queue import PriorityQueue
from typing import Optional

from agent.executor import AgentExecutor


# ---------------------------------------------------------------------------
# Enumeraciones
# ---------------------------------------------------------------------------

class TaskStatus(Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    CANCELLED = "cancelled"


class TaskPriority(Enum):
    LOW    = 3
    NORMAL = 2
    HIGH   = 1  # menor número = mayor prioridad en PriorityQueue


# ---------------------------------------------------------------------------
# Dataclass Task
# ---------------------------------------------------------------------------

@dataclass(order=True)
class Task:
    priority: int
    goal: str = field(compare=False)
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()), compare=False)
    status: TaskStatus = field(default=TaskStatus.PENDING, compare=False)
    result: Optional[str] = field(default=None, compare=False)
    speak: Optional[object] = field(default=None, compare=False)

    @staticmethod
    def from_priority_name(goal: str, priority_name: str = "normal", speak=None) -> "Task":
        mapping = {
            "low":    TaskPriority.LOW.value,
            "normal": TaskPriority.NORMAL.value,
            "high":   TaskPriority.HIGH.value,
        }
        prio = mapping.get(priority_name.lower(), TaskPriority.NORMAL.value)
        return Task(priority=prio, goal=goal, speak=speak)


# ---------------------------------------------------------------------------
# Clase TaskQueue
# ---------------------------------------------------------------------------

class TaskQueue:
    """Cola de tareas FIFO con prioridad."""

    def __init__(self):
        self._queue: PriorityQueue = PriorityQueue()
        self._tasks: dict = {}
        self._lock = threading.Lock()
        self._executor = AgentExecutor()
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def enqueue(self, task: Task) -> str:
        """Añade una tarea a la cola y devuelve su ID."""
        with self._lock:
            self._tasks[task.task_id] = task
        self._queue.put(task)
        self._ensure_worker()
        return task.task_id

    def get_status(self, task_id: str) -> Optional[TaskStatus]:
        """Devuelve el estado de una tarea por su ID."""
        task = self._tasks.get(task_id)
        return task.status if task else None

    def get_result(self, task_id: str) -> Optional[str]:
        """Devuelve el resultado de una tarea completada."""
        task = self._tasks.get(task_id)
        return task.result if task else None

    def stop(self):
        """Detiene el worker de la cola."""
        self._stop_event.set()

    # ------------------------------------------------------------------

    def _ensure_worker(self):
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._worker_thread = threading.Thread(
                target=self._process_loop, daemon=True
            )
            self._worker_thread.start()

    def _process_loop(self):
        while not self._stop_event.is_set():
            try:
                task: Task = self._queue.get(timeout=1)
            except Exception:
                continue

            task.status = TaskStatus.RUNNING
            try:
                result = self._executor.execute(task.goal, speak=task.speak)
                task.result = result
                task.status = TaskStatus.COMPLETED
            except Exception as exc:
                task.result = str(exc)
                task.status = TaskStatus.FAILED
            finally:
                self._queue.task_done()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_queue_instance: Optional[TaskQueue] = None
_queue_lock = threading.Lock()


def get_queue() -> TaskQueue:
    """Devuelve la instancia global de TaskQueue (singleton)."""
    global _queue_instance
    with _queue_lock:
        if _queue_instance is None:
            _queue_instance = TaskQueue()
    return _queue_instance
