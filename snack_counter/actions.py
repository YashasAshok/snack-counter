"""The complete, fixed list of things anyone can tell the bot.

Every interaction is one of these actions, shown as a button, a picker or a
short form. Nothing is typed as free text, so nothing needs interpreting.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Role(Enum):
    EMPLOYEE = "employee"    # anyone with a company login
    VOLUNTEER = "volunteer"
    ADMIN = "admin"          # office admin (HR/Ops), one per office


class Action(Enum):
    # Employee
    REPORT_EMPTY = "report_empty"
    JOIN_VOLUNTEERS = "join_volunteers"
    # Volunteer
    ACCEPT = "accept"
    DECLINE = "decline"
    RELEASE = "release"
    MARK_DONE = "mark_done"
    SET_AWAY = "set_away"
    SET_VISIT = "set_visit"
    MY_STATUS = "my_status"
    LEAVE_VOLUNTEERS = "leave_volunteers"
    # Office admin
    APPROVE_PURCHASE = "approve_purchase"
    REJECT_PURCHASE = "reject_purchase"
    ALLOW_EXTRA_BUDGET = "allow_extra_budget"
    KEEP_BLOCKED = "keep_blocked"
    ASSIGN = "assign"
    CANCEL_REFILL = "cancel_refill"
    MARK_FOLLOWED_UP = "mark_followed_up"
    MANAGE_VOLUNTEERS = "manage_volunteers"
    MONTHLY_REPORT = "monthly_report"


@dataclass(frozen=True)
class ActionSpec:
    label: str                         # what the button says
    role: Role                         # who may use it
    needs_refill: bool = False         # is it about a specific refill?
    required: tuple[str, ...] = ()     # form fields that must be filled in
    optional: tuple[str, ...] = ()     # form fields that may be left empty


CATALOGUE: dict[Action, ActionSpec] = {
    Action.REPORT_EMPTY: ActionSpec("Snack box is empty", Role.EMPLOYEE, optional=("office",)),
    Action.JOIN_VOLUNTEERS: ActionSpec("Join volunteers", Role.EMPLOYEE),

    Action.ACCEPT: ActionSpec("I'll do it", Role.VOLUNTEER, needs_refill=True),
    Action.DECLINE: ActionSpec("Can't today", Role.VOLUNTEER, needs_refill=True, optional=("reason",)),
    Action.RELEASE: ActionSpec("Can't make it after all", Role.VOLUNTEER, needs_refill=True),
    Action.MARK_DONE: ActionSpec(
        "Mark as done", Role.VOLUNTEER, needs_refill=True,
        required=("amount", "receipt", "items"), optional=("ran_out", "left_over"),
    ),
    Action.SET_AWAY: ActionSpec("Set away", Role.VOLUNTEER, required=("start", "end")),
    Action.SET_VISIT: ActionSpec("I'm visiting another office", Role.VOLUNTEER, required=("office", "start", "end")),
    Action.MY_STATUS: ActionSpec("My status", Role.VOLUNTEER),
    Action.LEAVE_VOLUNTEERS: ActionSpec("Leave volunteers", Role.VOLUNTEER),

    Action.APPROVE_PURCHASE: ActionSpec("Approve", Role.ADMIN, needs_refill=True),
    Action.REJECT_PURCHASE: ActionSpec("Reject", Role.ADMIN, needs_refill=True, optional=("reason",)),
    Action.ALLOW_EXTRA_BUDGET: ActionSpec("Allow extra budget", Role.ADMIN, needs_refill=True, required=("amount",)),
    Action.KEEP_BLOCKED: ActionSpec("Keep blocked", Role.ADMIN, needs_refill=True),
    Action.ASSIGN: ActionSpec("Assign to…", Role.ADMIN, needs_refill=True, required=("person",)),
    Action.CANCEL_REFILL: ActionSpec("Cancel refill", Role.ADMIN, needs_refill=True, optional=("reason",)),
    Action.MARK_FOLLOWED_UP: ActionSpec("Mark claim followed up", Role.ADMIN, needs_refill=True),
    Action.MANAGE_VOLUNTEERS: ActionSpec("Manage volunteers", Role.ADMIN, required=("person", "volunteer")),
    Action.MONTHLY_REPORT: ActionSpec("Monthly report", Role.ADMIN, required=("year", "month")),
}
