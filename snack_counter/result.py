from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Refill
    from .ports import Button


@dataclass
class Result:
    """Outcome of an action: what to tell the person, and which buttons to show next."""

    ok: bool
    message: str
    buttons: list[Button] = field(default_factory=list)
    refill: Refill | None = None
