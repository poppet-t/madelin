"""Hot/cold queue management for candidate-directed fuzzing.

Programs are scored and placed into hot (high-priority) or cold (low-priority)
queues.  The orchestrator draws parents preferentially from the hot queue.

Promotion: cold → hot when score improves above threshold.
Demotion:  hot → cold when stale (no improvement after N iterations).
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any


@dataclass(order=True)
class QueueEntry:
    """A scored program in the queue.  Ordered by negative score (max-heap via heapq)."""
    priority: float = field(compare=True)  # negative total score
    prog_id: str = field(compare=False)
    calls: list[str] = field(compare=False, repr=False)
    scores: dict = field(compare=False, repr=False)
    age: int = field(compare=False, default=0)


class FuzzQueue:
    """Two-tier hot/cold priority queue for candidate-directed fuzzing."""

    def __init__(
        self,
        hot_threshold: float = 0.5,
        cold_threshold: float = 0.3,
        stale_after: int = 50,
    ):
        self.hot: list[QueueEntry] = []
        self.cold: list[QueueEntry] = []
        self.hot_threshold = hot_threshold
        self.cold_threshold = cold_threshold
        self.stale_after = stale_after
        self._id_counter = 0

    def add(self, calls: list[str], scores: dict) -> str:
        """Add a program to the appropriate queue. Returns prog_id."""
        self._id_counter += 1
        prog_id = f"prog_{self._id_counter:06d}"
        total = scores.get("total", 0.0)
        entry = QueueEntry(
            priority=-total,
            prog_id=prog_id,
            calls=list(calls),
            scores=dict(scores),
        )
        if total >= self.hot_threshold:
            heapq.heappush(self.hot, entry)
        else:
            heapq.heappush(self.cold, entry)
        return prog_id

    def pick_parent(self) -> QueueEntry | None:
        """Pick the highest-scored parent, preferring hot queue.

        Returns None if both queues are empty.
        """
        if self.hot:
            entry = heapq.heappop(self.hot)
            entry.age += 1
            # Re-insert with updated age.
            heapq.heappush(self.hot, entry)
            return entry
        if self.cold:
            entry = heapq.heappop(self.cold)
            entry.age += 1
            heapq.heappush(self.cold, entry)
            return entry
        return None

    def promote_demote(self) -> None:
        """Run promotion/demotion sweep."""
        # Promote cold entries that exceed hot threshold.
        remaining_cold = []
        while self.cold:
            entry = heapq.heappop(self.cold)
            if -entry.priority >= self.hot_threshold:
                heapq.heappush(self.hot, entry)
            else:
                remaining_cold.append(entry)
        self.cold = remaining_cold
        heapq.heapify(self.cold)

        # Demote stale hot entries.
        remaining_hot = []
        while self.hot:
            entry = heapq.heappop(self.hot)
            if entry.age > self.stale_after:
                entry.age = 0
                heapq.heappush(self.cold, entry)
            else:
                remaining_hot.append(entry)
        self.hot = remaining_hot
        heapq.heapify(self.hot)

    @property
    def total_size(self) -> int:
        return len(self.hot) + len(self.cold)

    def stats(self) -> dict:
        return {
            "hot_size": len(self.hot),
            "cold_size": len(self.cold),
            "total_size": self.total_size,
        }
