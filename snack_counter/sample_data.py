"""Sample offices and people used by the demo and the tests.

(The real offices have about 15 and 20 volunteers; a handful is enough to show every rule.)
"""

from __future__ import annotations

from decimal import Decimal

from .config import Settings
from .models import Office, Person
from .money import Money

OSLO = "OSLO"
BENGALURU = "BLR"

# Employee IDs
SOFIE = "E-001"   # management: receives the monthly report
MARTE = "E-100"   # Oslo office admin
LARS = "E-101"
INGRID = "E-102"
OLA = "E-103"
PRIYA = "E-104"   # Oslo-based, visits Bengaluru in the demo
KARI = "E-105"    # Oslo employee, not a volunteer
RAVI = "E-200"    # Bengaluru office admin
ARJUN = "E-201"
DIVYA = "E-202"
RAHUL = "E-203"
SNEHA = "E-204"   # Bengaluru employee, not a volunteer

# Test value, not a real market rate
TEST_FX_RATES = {("INR", "NOK"): Decimal("0.12")}


def sample_offices() -> list[Office]:
    return [
        Office(OSLO, "Oslo", "NOK",
               monthly_budget=Money(6000, "NOK"), min_purchase=Money(300, "NOK"),
               max_purchase=Money(1200, "NOK"), owed_cap=Money(2000, "NOK"),
               timezone="Europe/Oslo", admin_id=MARTE),
        Office(BENGALURU, "Bengaluru", "INR",
               monthly_budget=Money(15000, "INR"), min_purchase=Money(500, "INR"),
               max_purchase=Money(3000, "INR"), owed_cap=Money(5000, "INR"),
               timezone="Asia/Kolkata", admin_id=RAVI),
    ]


def sample_people() -> list[Person]:
    return [
        Person(SOFIE, "Sofie", OSLO),
        Person(MARTE, "Marte", OSLO),
        Person(LARS, "Lars", OSLO, is_volunteer=True),
        Person(INGRID, "Ingrid", OSLO, is_volunteer=True),
        Person(OLA, "Ola", OSLO, is_volunteer=True),
        Person(PRIYA, "Priya", OSLO, is_volunteer=True),
        Person(KARI, "Kari", OSLO),
        Person(RAVI, "Ravi", BENGALURU),
        Person(ARJUN, "Arjun", BENGALURU, is_volunteer=True),
        Person(DIVYA, "Divya", BENGALURU, is_volunteer=True),
        Person(RAHUL, "Rahul", BENGALURU, is_volunteer=True),
        Person(SNEHA, "Sneha", BENGALURU),
    ]


def sample_settings() -> Settings:
    return Settings(management_ids=(SOFIE,))
