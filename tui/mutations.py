"""Последовательные правки состояния с черновиком поверх подтверждённых данных."""

from collections import Counter, deque
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from collections.abc import Callable


@dataclass
class Change:
    title: str
    method: str
    patch: Callable[[Any], Any]
    arguments: Callable[[Any], tuple]
    journal: str | None = None
    after: Callable | None = None
    failed: Callable | None = None


class StateWrites:
    def __init__(self):
        self.pending: dict[str, deque[Change]] = {}
        self.base: dict[str, Any] = {}
        self.versions = Counter()

    def enqueue(self, key: str, state, change: Change) -> bool:
        first = key not in self.pending
        if first:
            self.base[key] = deepcopy(state)
            self.pending[key] = deque()
        self.pending[key].append(change)
        self.versions[key] += 1
        return first

    def visible(self, key: str):
        state = deepcopy(self.base[key])
        for change in self.pending[key]:
            state = change.patch(state)
        return state

    def target(self, key: str):
        return self.pending[key][0].patch(deepcopy(self.base[key]))

    def finish(self, key: str, success: bool):
        if success:
            self.base[key] = self.target(key)
        self.pending[key].popleft()
        self.versions[key] += 1
        if self.pending[key]:
            return self.visible(key)
        del self.pending[key]
        return self.base.pop(key)

    def accepts(self, key: str, version: int) -> bool:
        return key not in self.pending and self.versions[key] == version
