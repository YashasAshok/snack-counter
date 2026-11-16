"""Shopping hints: turn "which snacks get eaten" data into a suggestion for the next buyer.

Suggestions only. The volunteer decides what to buy.
"""

from __future__ import annotations

from collections import Counter

from .models import Office, RefillState
from .store import InMemoryStore


def _times(count: int, out_of: int) -> str:
    return "last time" if out_of == 1 else f"{count} of the last {out_of} times"


def shopping_hint(store: InMemoryStore, office: Office, last_n: int = 3) -> str | None:
    recent = sorted(
        (r.purchase for r in store.refills_at(office.id)
         if r.purchase and r.state != RefillState.CANCELLED),
        key=lambda p: p.purchased_at,
        reverse=True,
    )[:last_n]
    if not recent:
        return None

    n = len(recent)
    ran_out = Counter(item for p in recent for item in set(p.ran_out))
    left_over = Counter(item for p in recent for item in set(p.left_over))

    # Only mention something that happened in most of the recent refills
    more = [f"{item} (ran out first {_times(c, n)})" for item, c in ran_out.most_common() if c * 2 > n]
    fewer = [f"{item} (left over {_times(c, n)})" for item, c in left_over.most_common() if c * 2 > n]

    parts = []
    if more:
        parts.append("more " + ", ".join(more))
    if fewer:
        parts.append("fewer " + ", ".join(fewer))
    return "; ".join(parts) if parts else None
