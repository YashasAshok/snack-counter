"""Wires the pieces together. Real adapters (chat, HR, clock, FX) would be passed in here in production."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from .bot import Bot
from .config import Settings
from .models import Office, Person
from .ports import ChatPort, FxRates, HRPort
from .refill_service import RefillService
from .store import InMemoryStore


@dataclass
class App:
    store: InMemoryStore
    clock: object
    chat: ChatPort
    hr: HRPort
    fx: FxRates
    settings: Settings
    service: RefillService
    bot: Bot

    def tick(self) -> None:
        self.service.tick()

    def run_until(self, moment: datetime, step: timedelta = timedelta(minutes=5)) -> None:
        """Move the simulated clock forward to `moment`, running the timers every `step`."""
        while self.clock.now() + step <= moment:
            self.clock.advance(step)
            self.tick()
        if self.clock.now() < moment:
            self.clock.set(moment)
            self.tick()


def create_app(clock, chat: ChatPort, hr: HRPort, fx: FxRates, settings: Settings,
               offices: Iterable[Office], people: Iterable[Person]) -> App:
    store = InMemoryStore()
    for office in offices:
        store.add_office(office)
    for person in people:
        store.add_person(person)
    service = RefillService(store, clock, chat, hr, fx, settings)
    bot = Bot(store, service, chat, clock, fx)
    return App(store, clock, chat, hr, fx, settings, service, bot)
