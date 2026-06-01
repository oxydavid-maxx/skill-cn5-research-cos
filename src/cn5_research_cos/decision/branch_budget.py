"""Branch-budget decay (R2) — prevents unbounded breadth/depth of branching.

Each spend halves breadth (floor 2) and decrements depth. can_branch is False
when depth is exhausted.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Budget:
    breadth: int
    depth: int


def spend(b: Budget) -> Budget:
    return Budget(breadth=max(2, b.breadth // 2), depth=b.depth - 1)


def can_branch(b: Budget) -> bool:
    return b.depth > 0
