"""In-memory storage.

In production this would be a database. The one rule that matters most there:
a unique constraint on "one box-empty refill per office", and a conditional
update for accepting (UPDATE refill SET committed_by = ? WHERE id = ? AND
state IN ('OFFERED', 'BROADCAST')), so only one accept can ever win.
Here, a single lock plays that role.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime

from .money import Money
from .models import Office, Person, Refill


@dataclass(frozen=True)
class AuditEntry:
    at: datetime
    person_id: str
    action: str
    refill_id: str | None
    ok: bool
    reply: str


class InMemoryStore:
    def __init__(self) -> None:
        self.offices: dict[str, Office] = {}
        self.people: dict[str, Person] = {}
        self.refills: dict[str, Refill] = {}
        self.extra_budget: dict[tuple[str, int, int], Money] = {}   # (office, year, month) -> extra
        self.audit: list[AuditEntry] = []
        self.last_report_sent: tuple[int, int] | None = None
        self.lock = threading.RLock()
        self._last_refill_number = 0

    def add_office(self, office: Office) -> None:
        self.offices[office.id] = office

    def add_person(self, person: Person) -> None:
        self.people[person.id] = person

    def new_refill_id(self) -> str:
        self._last_refill_number += 1
        return f"R-{self._last_refill_number:04d}"

    def active_refill(self, office_id: str) -> Refill | None:
        """The refill for this office's box while it is empty (there is at most one)."""
        for refill in self.refills.values():
            if refill.office_id == office_id and refill.box_empty:
                return refill
        return None

    def refills_at(self, office_id: str) -> list[Refill]:
        return [r for r in self.refills.values() if r.office_id == office_id]

    def office_run_by(self, admin_id: str) -> Office | None:
        for office in self.offices.values():
            if office.admin_id == admin_id:
                return office
        return None

    def name(self, person_id: str | None) -> str:
        person = self.people.get(person_id) if person_id else None
        return person.name if person else str(person_id)
