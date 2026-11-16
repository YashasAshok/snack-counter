"""The refill lifecycle: from "the box is empty" to "the volunteer is paid back".

    OPEN -> OFFERED (one named person, 2h) -> COMMITTED (24h to buy) -> bought -> claim -> paid
              |  no / no reply: next person        |  hand back / deadline: next person
              '-- after 3 tries: BROADCAST (first tap wins)

Rules enforced here:
* at most one box-empty refill per office (a second report joins the first);
* accepting is atomic: every change happens under one lock, so only one
  person can ever commit to a refill;
* every offer and commitment has a deadline; `tick()` hands expired ones on.

Every method re-checks role, person and state itself, so an old button or a
double tap can never do anything it shouldn't.
"""

from __future__ import annotations

from datetime import datetime
from decimal import InvalidOperation
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

from . import assignment, budget
from .actions import CATALOGUE, Action
from .config import Settings
from .insights import shopping_hint
from .models import (BOX_EMPTY, MONEY_OWED, WAITING_FOR_BUYER, DateRange, Office, Person, Purchase,
                     Refill, RefillState, Visit)
from .money import Money
from .ports import Button, ChatPort, Clock, FxRates, HRPort
from .reimbursement import ReimbursementService
from .reporting import format_report, monthly_report
from .result import Result
from .store import InMemoryStore

S = RefillState

_STATE_FOR_PEOPLE = {
    S.NEEDS_APPROVAL: "waiting for the office admin's approval",
    S.SUBMIT_PENDING: "being sent to HR",
    S.CLAIM_SUBMITTED: "with HR for approval",
    S.APPROVED: "approved by HR, payment on the way",
}


class RefillService:
    def __init__(self, store: InMemoryStore, clock: Clock, chat: ChatPort, hr: HRPort,
                 fx: FxRates, settings: Settings) -> None:
        self.store = store
        self.clock = clock
        self.chat = chat
        self.fx = fx
        self.settings = settings
        self.claims = ReimbursementService(store, clock, chat, hr, settings)
        if store.last_report_sent is None:
            store.last_report_sent = self._previous_month(clock.now())

    # =====================================================================
    # Employee: report an empty box
    # =====================================================================
    def report_empty(self, person_id: str, office_id: str) -> Result:
        with self.store.lock:
            office = self.store.offices.get(office_id)
            if office is None:
                return Result(False, "I don't know that office.")
            now = self.clock.now()

            active = self.store.active_refill(office.id)
            if active:
                if person_id not in active.reported_by:
                    active.reported_by.append(person_id)
                active.log(now, f"also reported empty by {self.store.name(person_id)}")
                return Result(True, f"Thanks! The {office.name} box is already being handled ({active.id}).",
                              refill=active)

            refill = Refill(id=self.store.new_refill_id(), office_id=office.id, opened_at=now,
                            reported_by=[person_id])
            self.store.refills[refill.id] = refill
            refill.log(now, f"reported empty by {self.store.name(person_id)}")
            self._find_buyer(refill)
            return Result(True, f"Thanks! {office.name} refill {refill.id} opened. {self._status_line(refill)}",
                          refill=refill)

    # =====================================================================
    # Volunteer: accept, decline, hand back, mark as done
    # =====================================================================
    def accept(self, person_id: str, refill_id: str) -> Result:
        # The lock makes check-and-commit one atomic step: "first tap wins".
        with self.store.lock:
            refill = self.store.refills.get(refill_id)
            if refill is None:
                return Result(False, "I can't find that refill.")
            person = self.store.people[person_id]
            office = self.store.offices[refill.office_id]
            now = self.clock.now()

            if refill.state == S.COMMITTED:
                if refill.committed_by == person_id:
                    return Result(False, "You've already got this one. Thanks!")
                return Result(False, f"This refill has already been taken by "
                                     f"{self.store.name(refill.committed_by)}. Thanks anyway!")
            if refill.state == S.OFFERED:
                if refill.offer_to != person_id:
                    return Result(False, "This refill is with someone else right now. Thanks anyway!")
            elif refill.state == S.BROADCAST:
                reason = assignment.why_not_eligible(self.store, person, office, now, self.fx)
                if reason:
                    return Result(False, f"Sorry, you can't take this one ({reason}).")
            else:
                return Result(False, "This refill doesn't need a buyer any more. Thanks anyway!")

            if not budget.can_start_refill(self.store, office, now):
                self._find_buyer(refill)  # moves it to BLOCKED_BUDGET and tells the admin
                return Result(False, "Sorry, this month's snack budget has just run out. "
                                     "The office admin has been told.")

            others = [p for p in refill.broadcast_to if p != person_id]
            refill.state = S.COMMITTED
            refill.committed_by = person_id
            refill.committed_at = now
            refill.deadline = now + self.settings.commit_window
            refill.spending_limit = budget.spending_limit(self.store, office, now)
            refill.reminder_sent = False
            refill.offer_to = None
            refill.offer_until = None
            refill.broadcast_to = []
            refill.log(now, f"taken by {person.name} (limit {refill.spending_limit})")

            for other in others:
                self._tell(other, f"{person.name} is refilling the {office.name} box. Thanks anyway!")
            return Result(
                True,
                f"It's yours! Spend up to {refill.spending_limit} and finish by "
                f"{self._when(office, refill.deadline)}.",
                self._buttons(refill, Action.MARK_DONE, Action.RELEASE),
                refill=refill,
            )

    def decline(self, person_id: str, refill_id: str, reason: str | None = None) -> Result:
        with self.store.lock:
            refill = self.store.refills.get(refill_id)
            if refill is None or refill.state != S.OFFERED or refill.offer_to != person_id:
                return Result(False, "This offer isn't waiting for you any more. Thanks anyway!")
            now = self.clock.now()
            refill.skip_for_direct_offer.add(person_id)
            refill.skip_for_broadcast.add(person_id)
            refill.log(now, f"declined by {self.store.name(person_id)}" + (f" ({reason})" if reason else ""))
            self._find_buyer(refill)
            return Result(True, "No worries, I'll ask someone else.", refill=refill)

    def release(self, person_id: str, refill_id: str) -> Result:
        with self.store.lock:
            refill = self.store.refills.get(refill_id)
            if refill is None or refill.state != S.COMMITTED or refill.committed_by != person_id:
                return Result(False, "You don't have this refill any more.")
            self._hand_back(refill, f"handed back by {self.store.name(person_id)}")
            return Result(True, "Thanks for letting me know. I'll find someone else.", refill=refill)

    def mark_done(self, person_id: str, refill_id: str, amount, receipt: str | None,
                  items: Iterable[str], ran_out: Iterable[str] = (), left_over: Iterable[str] = ()) -> Result:
        with self.store.lock:
            refill = self.store.refills.get(refill_id)
            if refill is None or refill.state != S.COMMITTED or refill.committed_by != person_id:
                return Result(False, "You don't have an active refill to complete.")
            office = self.store.offices[refill.office_id]
            now = self.clock.now()

            try:
                spent = Money(amount, office.currency)
            except (TypeError, InvalidOperation):
                return Result(False, "Please enter the amount as a number, e.g. 845.50.")
            if not spent.is_positive():
                return Result(False, "The amount must be more than zero.")
            if not receipt:
                return Result(False, "Please attach a photo of the receipt.")
            items = list(items)
            if not items:
                return Result(False, "Please tick at least one item you bought.")

            refill.purchase = Purchase(
                buyer_id=person_id, amount=spent, items=items,
                ran_out=list(ran_out), left_over=list(left_over), receipt=receipt, purchased_at=now,
                fx_rate_to_reporting=self.fx.rate(office.currency, self.settings.reporting_currency,
                                                  office.today(now)),
            )
            refill.log(now, f"refilled by {self.store.name(person_id)} for {spent}")

            if spent > refill.spending_limit:
                refill.state = S.NEEDS_APPROVAL
                self._tell(
                    office.admin_id,
                    f"{self.store.name(person_id)} spent {spent} on the {office.name} refill ({refill.id}), "
                    f"above the {refill.spending_limit} limit. Approve the claim?",
                    self._buttons(refill, Action.APPROVE_PURCHASE, Action.REJECT_PURCHASE),
                )
                return Result(True, f"Thanks for refilling! {spent} is above the {refill.spending_limit} "
                                    f"limit, so {self.store.name(office.admin_id)} needs to approve it before "
                                    f"it goes to HR. I'll keep you posted.", refill=refill)

            result = self.claims.submit(refill)
            return Result(True, f"Thanks for refilling! {result.message}", refill=refill)

    # =====================================================================
    # Volunteer: availability and status
    # =====================================================================
    def join(self, person_id: str) -> Result:
        person = self.store.people[person_id]
        person.is_volunteer = True
        return Result(True, "Welcome aboard! I'll ask you to refill now and then, shared fairly with everyone else.")

    def leave(self, person_id: str) -> Result:
        if assignment.holds_a_refill(self.store, person_id):
            return Result(False, "Please finish or hand back your current refill first.")
        self.store.people[person_id].is_volunteer = False
        return Result(True, "You've left the volunteer list. Thanks for all your help!")

    def set_away(self, person_id: str, start, end) -> Result:
        try:
            period = DateRange(start, end)
        except ValueError as error:
            return Result(False, f"{error}.")
        self.store.people[person_id].away.append(period)
        return Result(True, f"Noted: you're away {start:%d %b} – {end:%d %b}. I won't ask you then.")

    def set_visit(self, person_id: str, office_id: str, start, end) -> Result:
        person = self.store.people[person_id]
        office = self.store.offices.get(office_id)
        if office is None:
            return Result(False, "I don't know that office.")
        if office.id == person.home_office:
            return Result(False, f"{office.name} is already your home office.")
        try:
            visit = Visit(office.id, DateRange(start, end))
        except ValueError as error:
            return Result(False, f"{error}.")
        person.visits.append(visit)
        home = self.store.offices[person.home_office]
        return Result(True, f"Noted. From {start:%d %b} to {end:%d %b} you'll get {office.name} refills, "
                            f"not {home.name} ones.")

    def my_status(self, person_id: str) -> Result:
        lines = []
        owed: dict[str, Money] = {}
        for refill in self.store.refills.values():
            office = self.store.offices[refill.office_id]
            if refill.state == S.OFFERED and refill.offer_to == person_id:
                lines.append(f"• Open offer: refill the {office.name} box (reply by "
                             f"{self._when(office, refill.offer_until)}).")
            if refill.state == S.COMMITTED and refill.committed_by == person_id:
                lines.append(f"• You're refilling the {office.name} box: spend up to {refill.spending_limit} "
                             f"by {self._when(office, refill.deadline)}.")
            purchase = refill.purchase
            if purchase and purchase.buyer_id == person_id and refill.state in MONEY_OWED:
                currency = purchase.amount.currency
                owed[currency] = owed.get(currency, Money.zero(currency)) + purchase.amount
                lines.append(f"• {refill.id}: {purchase.amount}, {_STATE_FOR_PEOPLE[refill.state]}.")
        if owed:
            lines.insert(0, "You're owed " + " and ".join(str(m) for m in owed.values()) + ".")
        if not lines:
            return Result(True, "Nothing in progress, and you're not owed anything. Thanks for helping!")
        return Result(True, "\n".join(lines))

    # =====================================================================
    # Office admin
    # =====================================================================
    def approve_purchase(self, admin_id: str, refill_id: str) -> Result:
        with self.store.lock:
            refill, error = self._refill_for_admin(admin_id, refill_id)
            if error:
                return error
            if refill.state != S.NEEDS_APPROVAL:
                return Result(False, "This purchase doesn't need approval any more.")
            refill.log(self.clock.now(), f"over-limit purchase approved by {self.store.name(admin_id)}")
            result = self.claims.submit(refill)
            buyer = refill.purchase.buyer_id
            self._tell(buyer, f"Good news: {self.store.name(admin_id)} approved your {refill.purchase.amount} "
                              f"purchase. {result.message}")
            return Result(True, f"Approved. {self.store.name(buyer)}'s claim is on its way to HR.", refill=refill)

    def reject_purchase(self, admin_id: str, refill_id: str, reason: str | None = None) -> Result:
        with self.store.lock:
            refill, error = self._refill_for_admin(admin_id, refill_id)
            if error:
                return error
            if refill.state != S.NEEDS_APPROVAL:
                return Result(False, "This purchase doesn't need approval any more.")
            refill.state = S.REJECTED
            refill.log(self.clock.now(), f"over-limit purchase rejected by {self.store.name(admin_id)}"
                                         + (f": {reason}" if reason else ""))
            buyer = refill.purchase.buyer_id
            self._tell(buyer, f"Sorry, {self.store.name(admin_id)} didn't approve your {refill.purchase.amount} "
                              f"purchase" + (f": {reason}" if reason else "") + ". Please talk to them directly.")
            return Result(True, f"Rejected. {self.store.name(buyer)} has been told.", refill=refill)

    def allow_extra_budget(self, admin_id: str, refill_id: str, amount) -> Result:
        with self.store.lock:
            refill, error = self._refill_for_admin(admin_id, refill_id)
            if error:
                return error
            if refill.state != S.BLOCKED_BUDGET:
                return Result(False, "This refill isn't blocked by the budget.")
            office = self.store.offices[refill.office_id]
            try:
                extra = Money(amount, office.currency)
            except (TypeError, InvalidOperation):
                return Result(False, "Please enter the amount as a number.")
            if not extra.is_positive():
                return Result(False, "The amount must be more than zero.")
            now = self.clock.now()
            key = (office.id, *office.month_of(now))
            self.store.extra_budget[key] = self.store.extra_budget.get(key, Money.zero(office.currency)) + extra
            refill.log(now, f"{self.store.name(admin_id)} allowed {extra} extra budget")
            self._find_buyer(refill)
            return Result(True, f"Done: {extra} extra for {office.local(now):%B}. {self._status_line(refill)}",
                          refill=refill)

    def keep_blocked(self, admin_id: str, refill_id: str) -> Result:
        refill, error = self._refill_for_admin(admin_id, refill_id)
        if error:
            return error
        if refill.state != S.BLOCKED_BUDGET:
            return Result(False, "This refill isn't blocked by the budget.")
        return Result(True, "OK, it stays blocked until the budget resets next month.", refill=refill)

    def assign(self, admin_id: str, refill_id: str, person_id: str) -> Result:
        """Send a direct offer to someone the admin picks. People can't be made to spend
        their own money, so they still have to accept."""
        with self.store.lock:
            refill, error = self._refill_for_admin(admin_id, refill_id)
            if error:
                return error
            if refill.state not in WAITING_FOR_BUYER:
                return Result(False, "This refill isn't waiting for a buyer.")
            person = self.store.people.get(person_id)
            if person is None:
                return Result(False, "I don't know that person.")
            office = self.store.offices[refill.office_id]
            now = self.clock.now()
            reason = assignment.why_not_eligible(self.store, person, office, now, self.fx)
            if reason:
                return Result(False, f"{person.name} can't take it: {reason}.")
            if refill.state == S.OFFERED and refill.offer_to and refill.offer_to != person.id:
                self._tell(refill.offer_to, f"The {office.name} refill has been passed to someone else. "
                                            f"No need to reply. Thanks!")
            refill.log(now, f"{self.store.name(admin_id)} assigned it to {person.name}")
            self._offer(refill, person, office, now)
            return Result(True, f"Sent {person.name} a direct offer. They still need to accept, since "
                                f"it's their own money.", refill=refill)

    def cancel_refill(self, admin_id: str, refill_id: str, reason: str | None = None) -> Result:
        with self.store.lock:
            refill, error = self._refill_for_admin(admin_id, refill_id)
            if error:
                return error
            if refill.state not in BOX_EMPTY:
                return Result(False, "Only a refill that hasn't been bought yet can be cancelled.")
            office = self.store.offices[refill.office_id]
            why = f": {reason}" if reason else ""
            for person_id in {refill.committed_by, refill.offer_to} - {None}:
                self._tell(person_id, f"The {office.name} refill was cancelled by "
                                      f"{self.store.name(admin_id)}{why}. Please don't buy anything.")
            refill.state = S.CANCELLED
            refill.offer_to = refill.offer_until = None
            refill.log(self.clock.now(), f"cancelled by {self.store.name(admin_id)}{why}")
            return Result(True, f"Cancelled {refill.id}.", refill=refill)

    def mark_followed_up(self, admin_id: str, refill_id: str) -> Result:
        refill, error = self._refill_for_admin(admin_id, refill_id)
        if error:
            return error
        claim = refill.claim
        if refill.state != S.CLAIM_SUBMITTED or not claim or not claim.escalated or claim.followed_up:
            return Result(False, "This claim doesn't need following up.")
        claim.followed_up = True
        refill.log(self.clock.now(), f"{self.store.name(admin_id)} followed up with HR")
        return Result(True, "Thanks for chasing HR!", refill=refill)

    def manage_volunteer(self, admin_id: str, person_id: str, volunteer: bool) -> Result:
        office = self.store.office_run_by(admin_id)
        person = self.store.people.get(person_id)
        if office is None or person is None or person.home_office != office.id:
            return Result(False, "You can only manage volunteers from your own office.")
        if not volunteer and assignment.holds_a_refill(self.store, person_id):
            return Result(False, f"{person.name} has a refill in progress; please wait until it's done.")
        person.is_volunteer = bool(volunteer)
        return Result(True, f"{person.name} is {'now' if volunteer else 'no longer'} a volunteer.")

    def report_text(self, year: int, month: int) -> Result:
        report = monthly_report(self.store, int(year), int(month), self.settings.reporting_currency)
        return Result(True, format_report(report))

    # =====================================================================
    # Timers: called regularly (every few minutes) by a scheduler
    # =====================================================================
    def tick(self) -> None:
        with self.store.lock:
            now = self.clock.now()
            for refill in list(self.store.refills.values()):
                office = self.store.offices[refill.office_id]

                if refill.state == S.OFFERED and now >= refill.offer_until:
                    person_id = refill.offer_to
                    refill.skip_for_direct_offer.add(person_id)
                    refill.log(now, f"no reply from {self.store.name(person_id)}")
                    self._tell(person_id, f"No reply, so I've passed the {office.name} refill on. No problem!")
                    self._find_buyer(refill)

                elif refill.state == S.COMMITTED:
                    if not refill.reminder_sent and now >= refill.committed_at + self.settings.reminder_after:
                        refill.reminder_sent = True
                        self._tell(refill.committed_by,
                                   f"Reminder: please refill the {office.name} box by "
                                   f"{self._when(office, refill.deadline)}.",
                                   self._buttons(refill, Action.MARK_DONE, Action.RELEASE))
                    if now >= refill.deadline:
                        self._tell(refill.committed_by, f"Time's up on the {office.name} refill, so I've passed "
                                                        f"it to someone else. No problem!")
                        self._hand_back(refill, f"{self.store.name(refill.committed_by)} didn't finish in time")

                elif refill.state == S.OPEN and self._office_open(office, now):
                    self._find_buyer(refill)

                elif refill.state == S.BLOCKED_BUDGET and budget.can_start_refill(self.store, office, now):
                    self._find_buyer(refill)  # new month, or the admin allowed extra

                self._end_of_day_check(refill, office, now)

            self.claims.tick()
            self._send_monthly_report_if_due(now)

    # =====================================================================
    # Internals
    # =====================================================================
    def _find_buyer(self, refill: Refill) -> None:
        """Move a refill that has no buyer one step forward."""
        office = self.store.offices[refill.office_id]
        now = self.clock.now()

        # 1. Budget check
        if not budget.can_start_refill(self.store, office, now):
            if refill.state != S.BLOCKED_BUDGET:
                refill.state = S.BLOCKED_BUDGET
                refill.offer_to = refill.offer_until = None
                left = budget.remaining(self.store, office, now)
                refill.log(now, f"blocked: only {left} of the budget left")
                self._tell(office.admin_id,
                           f"The {office.name} box is empty, but only {left} of this month's budget is left "
                           f"(a typical refill is at least {office.min_purchase}).",
                           self._buttons(refill, Action.ALLOW_EXTRA_BUDGET, Action.KEEP_BLOCKED))
            return

        # 2. Only ask people during office hours
        if not self._office_open(office, now):
            if refill.state != S.OPEN:
                refill.log(now, "waiting for office hours")
            refill.state = S.OPEN
            refill.offer_to = refill.offer_until = None
            return

        # 3. Direct offer to the fairest eligible person
        if refill.direct_offers < self.settings.max_direct_offers:
            person = assignment.next_candidate(self.store, office, now, self.settings, self.fx,
                                               exclude=refill.skip_for_direct_offer)
            if person:
                self._offer(refill, person, office, now)
                return

        # 4. Broadcast: everyone eligible who hasn't said no; first tap wins
        people = assignment.eligible_volunteers(self.store, office, now, self.fx,
                                                exclude=refill.skip_for_broadcast)
        if people:
            self._broadcast(refill, office, people, now)
            return

        # 5. Nobody available: tell the admin (once a day)
        refill.state = S.OPEN
        refill.offer_to = refill.offer_until = None
        today = office.today(now)
        if refill.escalated_on != today:
            refill.escalated_on = today
            refill.log(now, "no volunteer available; admin told")
            self._tell(office.admin_id,
                       f"Nobody is available to refill the {office.name} box ({refill.id}). "
                       f"Can you assign someone?",
                       self._buttons(refill, Action.ASSIGN, Action.CANCEL_REFILL))

    def _offer(self, refill: Refill, person: Person, office: Office, now: datetime) -> None:
        limit = budget.spending_limit(self.store, office, now)
        refill.state = S.OFFERED
        refill.offer_to = person.id
        refill.offer_until = now + self.settings.offer_window
        refill.direct_offers += 1
        refill.log(now, f"offered to {person.name}")
        lines = [
            f"Can you refill the {office.name} box today?",
            f"Spend up to {limit} · finish within {self._hours(self.settings.commit_window)} h of accepting.",
            f"Please reply by {self._when(office, refill.offer_until)}.",
        ]
        hint = shopping_hint(self.store, office)
        if hint:
            lines.append(f"Tip: {hint}.")
        self._tell(person.id, "\n".join(lines), self._buttons(refill, Action.ACCEPT, Action.DECLINE))

    def _broadcast(self, refill: Refill, office: Office, people: list[Person], now: datetime) -> None:
        limit = budget.spending_limit(self.store, office, now)
        refill.state = S.BROADCAST
        refill.offer_to = refill.offer_until = None
        refill.broadcast_to = [p.id for p in people]
        refill.log(now, "broadcast to " + ", ".join(p.name for p in people))
        for person in people:
            self._tell(person.id,
                       f"Anyone free to refill the {office.name} box? First to tap gets it.\n"
                       f"Spend up to {limit}.",
                       self._buttons(refill, Action.ACCEPT))

    def _hand_back(self, refill: Refill, why: str) -> None:
        """A committed volunteer can't finish: free the refill and find someone else."""
        now = self.clock.now()
        refill.skip_for_direct_offer.add(refill.committed_by)
        refill.skip_for_broadcast.add(refill.committed_by)
        refill.log(now, why)
        refill.state = S.OPEN
        refill.committed_by = refill.committed_at = refill.deadline = None
        refill.spending_limit = None
        refill.reminder_sent = False
        refill.direct_offers = 0  # a fresh round of direct offers
        self._find_buyer(refill)

    def _end_of_day_check(self, refill: Refill, office: Office, now: datetime) -> None:
        """At closing time, tell the admin about any refill that still has no buyer."""
        if refill.state not in WAITING_FOR_BUYER:
            return
        local = office.local(now)
        if local.weekday() not in self.settings.working_days:
            return
        closing = local.replace(hour=self.settings.office_closes, minute=0, second=0, microsecond=0)
        if local < closing or office.local(refill.opened_at) > closing:
            return
        if refill.escalated_on == local.date():
            return
        refill.escalated_on = local.date()
        refill.log(now, "still no buyer at the end of the day; admin told")
        self._tell(office.admin_id,
                   f"The {office.name} box ({refill.id}) still has no buyer at the end of the day. "
                   f"Assign someone?",
                   self._buttons(refill, Action.ASSIGN, Action.CANCEL_REFILL))

    def _send_monthly_report_if_due(self, now: datetime) -> None:
        previous = self._previous_month(now)
        if self.store.last_report_sent == previous:
            return
        text = self.report_text(*previous).message
        for person_id in self.settings.management_ids:
            self._tell(person_id, text)
        self.store.last_report_sent = previous

    def _previous_month(self, now: datetime) -> tuple[int, int]:
        local = now.astimezone(ZoneInfo(self.settings.report_timezone))
        return (local.year, local.month - 1) if local.month > 1 else (local.year - 1, 12)

    def _refill_for_admin(self, admin_id: str, refill_id: str) -> tuple[Refill | None, Result | None]:
        refill = self.store.refills.get(refill_id)
        if refill is None:
            return None, Result(False, "I can't find that refill.")
        office = self.store.offices[refill.office_id]
        if office.admin_id != admin_id:
            return None, Result(False, f"Only the {office.name} office admin can do that.")
        return refill, None

    def _office_open(self, office: Office, now: datetime) -> bool:
        local = office.local(now)
        return (local.weekday() in self.settings.working_days
                and self.settings.office_opens <= local.hour < self.settings.office_closes)

    def _status_line(self, refill: Refill) -> str:
        office = self.store.offices[refill.office_id]
        if refill.state in (S.OFFERED, S.BROADCAST):
            return "Someone has been asked."
        if refill.state == S.BLOCKED_BUDGET:
            return "This month's snack budget is used up, so I've told the office admin."
        if not self._office_open(office, self.clock.now()):
            return "I'll ask a volunteer when the office opens."
        return "No volunteer is free right now, so I've told the office admin."

    @staticmethod
    def _buttons(refill: Refill, *actions: Action) -> list[Button]:
        return [Button(CATALOGUE[a].label, a, refill.id) for a in actions]

    @staticmethod
    def _when(office: Office, moment: datetime) -> str:
        return f"{office.local(moment):%a %d %b %H:%M}"

    @staticmethod
    def _hours(delta) -> int:
        return int(delta.total_seconds() // 3600)

    def _tell(self, person_id: str, text: str, buttons: Sequence[Button] = ()) -> None:
        self.chat.send(person_id, text, buttons)
