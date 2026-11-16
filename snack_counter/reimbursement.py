"""Getting volunteers their money back.

* The claim is filed automatically the moment a refill is done.
* Our refill ID is the claim's reference, and we always look it up before
  creating, so a retry after a timeout can never create a second claim.
* If HR is down, the claim waits in SUBMIT_PENDING and is retried on the next
  tick (production: with exponential backoff). The volunteer does nothing.
* We poll HR daily, tell the volunteer about approval and payment, and chase
  claims that are still pending after 10 days.
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from .actions import CATALOGUE, Action
from .config import Settings
from .models import Claim, Refill, RefillState
from .ports import Button, ChatPort, Clock, HRPort, HRUnavailable
from .result import Result
from .store import InMemoryStore

S = RefillState


class ReimbursementService:
    def __init__(self, store: InMemoryStore, clock: Clock, chat: ChatPort, hr: HRPort, settings: Settings) -> None:
        self.store = store
        self.clock = clock
        self.chat = chat
        self.hr = hr
        self.settings = settings

    def submit(self, refill: Refill) -> Result:
        """File (or re-try filing) the HR claim for a completed refill."""
        now = self.clock.now()
        office = self.store.offices[refill.office_id]
        purchase = refill.purchase
        assert purchase is not None
        refill.claim = refill.claim or Claim(reference=refill.id)

        try:
            claim_id = self.hr.find_claim(refill.id) or self.hr.create_claim(
                employee_id=purchase.buyer_id,
                amount=purchase.amount.amount,
                currency=purchase.amount.currency,
                description=(
                    f"Snack refill, {office.name} office, "
                    f"{office.local(purchase.purchased_at):%d %b %Y}: {', '.join(purchase.items)} "
                    f"(ref {refill.id})"
                ),
                receipt=purchase.receipt,
                reference=refill.id,
            )
        except HRUnavailable:
            if refill.state != S.SUBMIT_PENDING:
                refill.state = S.SUBMIT_PENDING
                refill.log(now, "HR not reachable; will retry")
            return Result(
                True,
                "HR's system isn't answering right now. I'll keep trying; there's nothing more you need to do.",
                refill=refill,
            )

        refill.claim.hr_claim_id = claim_id
        refill.claim.submitted_at = now
        refill.claim.last_checked = now
        refill.state = S.CLAIM_SUBMITTED
        refill.log(now, f"claim {claim_id} filed with HR")
        return Result(
            True,
            f"Claim {claim_id} filed with HR for {purchase.amount}. "
            f"Approval usually takes 1–10 days; I'll tell you when it's approved.",
            refill=refill,
        )

    def tick(self) -> None:
        now = self.clock.now()
        for refill in list(self.store.refills.values()):
            if refill.state == S.SUBMIT_PENDING:
                result = self.submit(refill)
                if refill.state == S.CLAIM_SUBMITTED:
                    self._tell(refill.purchase.buyer_id, result.message)
            elif refill.state in (S.CLAIM_SUBMITTED, S.APPROVED):
                claim = refill.claim
                if now - claim.last_checked >= self.settings.hr_poll_interval:
                    self._poll(refill, now)
            if refill.state == S.CLAIM_SUBMITTED:
                self._chase_if_stale(refill, now)

    def _poll(self, refill: Refill, now: datetime) -> None:
        claim = refill.claim
        try:
            status = self.hr.get_status(claim.hr_claim_id)
        except HRUnavailable:
            return
        claim.last_checked = now
        purchase = refill.purchase
        buyer = purchase.buyer_id

        if status.status in ("APPROVED", "PAID") and refill.state == S.CLAIM_SUBMITTED:
            refill.state = S.APPROVED
            claim.approved_at = now
            refill.log(now, f"claim {claim.hr_claim_id} approved by HR")
            if status.status == "APPROVED":
                self._tell(buyer, f"Good news: HR approved your claim {claim.hr_claim_id} for {purchase.amount}.")
        if status.status == "PAID":
            refill.state = S.REIMBURSED
            claim.reimbursed_at = now
            refill.log(now, f"claim {claim.hr_claim_id} paid")
            self._tell(buyer, f"You've been paid back for claim {claim.hr_claim_id} ({purchase.amount}), "
                              f"in your payroll currency. Thanks for refilling!")
        elif status.status == "REJECTED":
            refill.state = S.REJECTED
            claim.rejection_reason = status.reason
            refill.log(now, f"claim {claim.hr_claim_id} rejected by HR: {status.reason}")
            office = self.store.offices[refill.office_id]
            self._tell(buyer, f"HR rejected claim {claim.hr_claim_id} ({purchase.amount}): {status.reason}. "
                              f"{self.store.name(office.admin_id)} has been told and will help sort it out.")
            self._tell(office.admin_id, f"HR rejected {self.store.name(buyer)}'s claim {claim.hr_claim_id} "
                                        f"({purchase.amount}) for refill {refill.id}: {status.reason}.")

    def _chase_if_stale(self, refill: Refill, now: datetime) -> None:
        claim = refill.claim
        if claim.escalated or now - claim.submitted_at < self.settings.stale_claim_after:
            return
        claim.escalated = True
        office = self.store.offices[refill.office_id]
        days = (now - claim.submitted_at).days
        refill.log(now, "claim pending too long; admin told")
        self._tell(
            office.admin_id,
            f"{self.store.name(refill.purchase.buyer_id)}'s claim {claim.hr_claim_id} "
            f"({refill.purchase.amount}) has been pending with HR for {days} days. Could you follow up with HR?",
            [Button(CATALOGUE[Action.MARK_FOLLOWED_UP].label, Action.MARK_FOLLOWED_UP, refill.id)],
        )

    def _tell(self, person_id: str, text: str, buttons: Sequence[Button] = ()) -> None:
        self.chat.send(person_id, text, buttons)
