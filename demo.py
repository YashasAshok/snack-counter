"""Scripted demo: one November in both offices, printed as a chat transcript.

    python demo.py

The clock is simulated, so a whole month runs in about a second. Every
complaint in the brief shows up: the empty box being handed on, an attempted
double purchase, fair rotation, automatic claims, a visitor refilling the other
office, the budget limit, and the monthly report in both currencies.
"""

from __future__ import annotations

import sys
import textwrap
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from snack_counter import budget
from snack_counter.actions import CATALOGUE, Action
from snack_counter.app import App, create_app
from snack_counter.fakes import FakeChat, FakeClock, FakeHR, FixedFx, SentMessage
from snack_counter.models import RefillState
from snack_counter.sample_data import (ARJUN, BENGALURU, DIVYA, INGRID, KARI, LARS, MARTE, OLA, OSLO, PRIYA,
                                       RAVI, SNEHA, SOFIE, TEST_FX_RATES, sample_offices, sample_people,
                                       sample_settings)

OSLO_TZ = ZoneInfo("Europe/Oslo")
BLR_TZ = ZoneInfo("Asia/Kolkata")


def at(tz: ZoneInfo, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=tz).astimezone(timezone.utc)


class Demo:
    def __init__(self, out=print) -> None:
        self.out = out
        self.loud = True
        clock = FakeClock(at(OSLO_TZ, 11, 2, 9, 0))
        chat = FakeChat(clock, on_send=self._show)
        self.app: App = create_app(clock, chat, FakeHR(), FixedFx(TEST_FX_RATES), sample_settings(),
                                   sample_offices(), sample_people())

    # --- printing --------------------------------------------------------
    def _local(self, person_id: str, moment: datetime) -> datetime:
        store = self.app.store
        person = store.people[person_id]
        home = store.offices[person.home_office]
        office = store.offices[person.office_on(home.today(moment))]
        return office.local(moment)

    def _show(self, message: SentMessage) -> None:
        if not self.loud:
            return
        name = self.app.store.name(message.to)
        stamp = f"{self._local(message.to, message.sent_at):%H:%M}"
        lines = message.text.splitlines()
        self.out(f"  {stamp}  Bot → {name}: {lines[0]}")
        for line in lines[1:]:
            self.out(f"{'':16}{line}")
        if message.buttons:
            self.out(f"{'':16}" + "  ".join(f"[{b.label}]" for b in message.buttons))

    def heading(self, text: str) -> None:
        self.out(f"\n━━━ {text} " + "━" * max(3, 70 - len(text)))

    def note(self, text: str) -> None:
        for line in textwrap.wrap(text, 72):
            self.out(f"         ⤷ {line}")

    def _actor(self, person_id: str, what: str, form: str = "") -> None:
        if self.loud:
            stamp = f"{self._local(person_id, self.app.clock.now()):%H:%M}"
            self.out(f"  {stamp}  {self.app.store.name(person_id)} {what}")
            if form:
                self.out(f"{'':16}form: {form}")

    # --- doing things ----------------------------------------------------
    def wait_until(self, moment: datetime) -> None:
        """Let time pass, showing any messages the bot sends meanwhile."""
        self.app.run_until(moment)

    def skip_to(self, moment: datetime) -> None:
        """Jump ahead (e.g. to another day) without printing the routine messages in between."""
        was_loud, self.loud = self.loud, False
        self.app.run_until(moment)
        self.loud = was_loud

    def press(self, person_id: str, action: Action, refill_id: str | None = None, shown: str = "", **form):
        """A button that isn't on a message (e.g. from the QR code or the bot's menu)."""
        self._actor(person_id, f"taps [{CATALOGUE[action].label}]", shown)
        return self.app.bot.press(person_id, action, refill_id, **form)

    def tap(self, person_id: str, label: str, shown: str = "", **form):
        """Tap a button on the latest message that has it."""
        button = self.app.chat.button(person_id, label)
        self._actor(person_id, f"taps [{label}]", shown)
        return self.app.bot.tap(person_id, button, **form)

    def hr_works_through_backlog(self, older_than_days: int = 6) -> None:
        """HR staff approve and pay claims that have waited long enough (in their own system)."""
        now = self.app.clock.now()
        for refill in self.app.store.refills.values():
            claim = refill.claim
            if refill.state in (RefillState.CLAIM_SUBMITTED, RefillState.APPROVED) and claim and \
                    now - claim.submitted_at >= timedelta(days=older_than_days):
                self.app.hr.pay(claim.hr_claim_id)

    def quick_refill(self, office_id: str, reporter: str, when: datetime, amount: int,
                     items: list[str], ran_out=(), left_over=(), hr_backlog: bool = True) -> None:
        """A whole refill in fast-forward: reported, accepted by whoever is asked, done 3 hours later."""
        was_loud, self.loud = self.loud, False
        self.app.run_until(when)
        if hr_backlog:
            self.hr_works_through_backlog()
        refill = self.app.bot.press(reporter, Action.REPORT_EMPTY, office=office_id).refill
        buyer = refill.offer_to
        self.app.run_until(when + timedelta(minutes=5))
        self.app.bot.press(buyer, Action.ACCEPT, refill.id)
        self.app.run_until(when + timedelta(hours=3))
        self.app.bot.press(buyer, Action.MARK_DONE, refill.id, amount=str(amount),
                           receipt=f"receipt-{refill.id}.jpg", items=items,
                           ran_out=list(ran_out), left_over=list(left_over))
        self.loud = was_loud
        office = self.app.store.offices[office_id]
        left = budget.remaining(self.app.store, office, self.app.clock.now())
        self.out(f"  {office.local(when):%a %d %b}  {office.name:<10} {self.app.store.name(buyer):<7} "
                 f"refilled for {str(refill.purchase.amount):>10}   ·  budget left {left}")

    # --- the story -------------------------------------------------------
    def run(self) -> App:
        app = self.app

        self.heading("Mon 02 Nov · Oslo: the box is empty")
        self.press(PRIYA, Action.SET_VISIT, shown="Bengaluru, 9–20 Nov",
                   office=BENGALURU, start=date(2026, 11, 9), end=date(2026, 11, 20))
        self.wait_until(at(OSLO_TZ, 11, 2, 9, 10))
        self.note("Kari scans the QR code on the Oslo box.")
        refill = self.press(KARI, Action.REPORT_EMPTY, office=OSLO).refill
        self.note("The bot picks ONE person (fairest first) and asks them directly.")
        self.wait_until(at(OSLO_TZ, 11, 2, 9, 25))
        self.press(OLA, Action.REPORT_EMPTY, office=OSLO)
        self.note("No second refill is created: one active refill per office.")

        self.heading("Lars doesn't reply within 2 hours")
        self.wait_until(at(OSLO_TZ, 11, 2, 11, 0))
        self.wait_until(at(OSLO_TZ, 11, 2, 11, 30))
        self.tap(INGRID, "Can't today", shown="reason: WFH", reason="WFH")
        self.note("Declining hands it on immediately.")

        self.heading("Ola doesn't reply either: 3 direct offers used, so broadcast")
        self.wait_until(at(OSLO_TZ, 11, 2, 13, 30))
        self.wait_until(at(OSLO_TZ, 11, 2, 13, 35))
        self.note("Lars and Ola tap at the same moment. Only one can win "
                  "(the tests fire these from two threads at once).")
        self.tap(LARS, "I'll do it")
        self.tap(OLA, "I'll do it")

        self.heading("Lars buys the snacks")
        self.wait_until(at(OSLO_TZ, 11, 2, 16, 5))
        self.tap(LARS, "Mark as done",
                 shown="845 NOK · receipt.jpg · Chips, Fruit, Chocolate · ran out first: Fruit · left over: Biscuits",
                 amount="845", receipt="receipt-lars-0211.jpg", items=["Chips", "Fruit", "Chocolate"],
                 ran_out=["Fruit"], left_over=["Biscuits"])
        self.note("The HR claim is filed automatically: amount, currency, description, receipt, employee ID.")

        self.heading("Thu 05 Nov · HR approves; Oslo refills again")
        self.skip_to(at(OSLO_TZ, 11, 5, 9, 0))
        app.hr.approve(refill.claim.hr_claim_id)
        self.note(f"HR approves {refill.claim.hr_claim_id} in their own system. We check HR daily.")
        self.quick_refill(OSLO, KARI, at(OSLO_TZ, 11, 5, 10, 0), 1100, ["Fruit", "Chips", "Nuts"],
                          ran_out=["Fruit"], hr_backlog=False)
        self.wait_until(at(OSLO_TZ, 11, 5, 16, 30))

        self.heading("Mon 09 Nov · Bengaluru: Priya is visiting")
        self.skip_to(at(BLR_TZ, 11, 9, 10, 0))
        refill_blr = self.press(SNEHA, Action.REPORT_EMPTY, office=BENGALURU).refill
        self.note("Priya is visiting from Oslo, so she can refill the Bengaluru box. "
                  "Eligibility depends on where you are today, not your home office.")
        self.wait_until(at(BLR_TZ, 11, 9, 10, 20))
        self.tap(PRIYA, "I'll do it")
        self.wait_until(at(BLR_TZ, 11, 9, 15, 0))
        self.tap(PRIYA, "Mark as done", shown="2 400 INR · Namkeen, Biscuits, Fruit · ran out first: Namkeen",
                 amount="2400", receipt="receipt-priya-0911.jpg", items=["Namkeen", "Biscuits", "Fruit"],
                 ran_out=["Namkeen"])
        self.note("Charged to the Bengaluru budget in INR. HR pays Priya back in her own payroll currency.")
        self.quick_refill(OSLO, OLA, at(OSLO_TZ, 11, 9, 10, 0), 950, ["Fruit", "Chocolate", "Crackers"],
                          ran_out=["Fruit"], hr_backlog=False)

        self.heading("Tue 10 Nov · Lars is paid back")
        self.skip_to(at(OSLO_TZ, 11, 10, 9, 0))
        app.hr.pay(refill.claim.hr_claim_id)
        self.wait_until(at(OSLO_TZ, 11, 10, 16, 30))

        self.heading("Wed 11 Nov · Bengaluru: a purchase over the limit")
        self.skip_to(at(BLR_TZ, 11, 11, 11, 0))
        self.press(DIVYA, Action.REPORT_EMPTY, office=BENGALURU)
        self.note("Priya has done one refill now, so Arjun (none yet) is asked. The tip comes from earlier refills.")
        self.wait_until(at(BLR_TZ, 11, 11, 11, 15))
        self.tap(ARJUN, "I'll do it")
        self.wait_until(at(BLR_TZ, 11, 11, 14, 0))
        self.tap(ARJUN, "Mark as done", shown="3 400 INR · Namkeen, Fruit, Juice",
                 amount="3400", receipt="receipt-arjun-1111.jpg", items=["Namkeen", "Fruit", "Juice"])
        self.wait_until(at(BLR_TZ, 11, 11, 14, 30))
        self.tap(RAVI, "Approve")

        self.heading("12–24 Nov · fast-forward (claims are paid as HR works through them)")
        self.quick_refill(OSLO, KARI, at(OSLO_TZ, 11, 12, 10, 0), 1200, ["Fruit", "Chips", "Chocolate"],
                          ran_out=["Fruit"])
        self.quick_refill(BENGALURU, SNEHA, at(BLR_TZ, 11, 16, 11, 0), 2800, ["Namkeen", "Fruit", "Biscuits"])
        self.quick_refill(OSLO, OLA, at(OSLO_TZ, 11, 17, 10, 0), 1050, ["Fruit", "Nuts", "Chocolate"])
        self.quick_refill(BENGALURU, DIVYA, at(BLR_TZ, 11, 19, 11, 0), 2100, ["Fruit", "Namkeen"])
        self.quick_refill(OSLO, KARI, at(OSLO_TZ, 11, 20, 10, 0), 800, ["Fruit", "Chips"])
        self.quick_refill(BENGALURU, SNEHA, at(BLR_TZ, 11, 24, 11, 0), 2600, ["Namkeen", "Juice", "Fruit"])
        self.note("Spending limits shrink as the budget runs low (Oslo's last one was limited to 855 NOK).")

        self.heading("Wed 25 Nov · Oslo: the budget is used up")
        self.skip_to(at(OSLO_TZ, 11, 25, 10, 0))
        blocked = self.press(KARI, Action.REPORT_EMPTY, office=OSLO).refill
        self.wait_until(at(OSLO_TZ, 11, 25, 10, 10))
        self.tap(MARTE, "Keep blocked")

        self.quick_refill(BENGALURU, SNEHA, at(BLR_TZ, 11, 27, 11, 0), 1600, ["Fruit", "Biscuits"])

        self.heading("Tue 01 Dec · the monthly report goes to management automatically")
        self.skip_to(at(OSLO_TZ, 11, 30, 23, 45))
        self.wait_until(at(OSLO_TZ, 12, 1, 8, 0))
        self.note("The new month also unblocks the Oslo refill; a volunteer is asked when the office opens.")
        self.wait_until(at(OSLO_TZ, 12, 1, 9, 0))
        return app


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    Demo().run()


if __name__ == "__main__":
    main()
