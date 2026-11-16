# Snack Counter Automation: Design

## What "automate" means here

Today the process fails because **nobody owns a refill**, **nothing is shared** and **nothing is recorded**. The solution is a **chat bot** in the company chat tool (everyone already has it and a company login), backed by a small service that:

1. gives every refill **one named owner with a deadline**, and hands it on automatically when they don't act;
2. allows **one active refill per office**, and makes accepting it **atomic**;
3. picks the buyer **fairly**, and doesn't ask people who are still owed money;
4. **files the HR claim automatically** when the refill is done, then tracks it until it's paid;
5. records every purchase (amount, currency, items), so the **monthly report** comes for free.

Everything anyone needs to tell the bot is a **small, fixed set of about 16 actions** (employee, volunteer, office admin), so people use **buttons, pickers and short forms**, not commands or free text. The bot shows each person **only the buttons that are valid for them right now**, and the service **re-checks every action**, so an old or double-tapped button can't do any harm.

## How a refill moves from "empty" to "reimbursed"

```
OPEN ─► OFFERED (one person, 2 h) ─accept─► COMMITTED (24 h to buy) ─done─► CLAIM_SUBMITTED ─► APPROVED ─► REIMBURSED
            │ no / no reply → next person          │ hand back / deadline → next person
            └─ after 3 direct offers: BROADCAST (first tap wins)
Side states: BLOCKED_BUDGET · NEEDS_APPROVAL (over the limit) · SUBMIT_PENDING (HR down) · REJECTED · CANCELLED
```

1. **Report:** anyone taps *Snack box is empty* (a QR code on the box opens the bot with the office filled in). A second report joins the open refill.
2. **Budget check:** if less than a typical minimum purchase is left, the refill is blocked and the office admin decides (*Allow extra budget* / *Keep blocked*). It unblocks by itself next month.
3. **Offer:** the fairest eligible volunteer gets a direct offer with a spending limit and a shopping hint: *[I'll do it] [Can't today]*, 2 hours to reply, office hours only.
4. **Hand on:** a decline or no reply goes to the next person. After 3 direct offers it goes to everyone eligible, and the first tap wins. If nobody has taken it by closing time, the admin is asked to assign someone.
5. **Buy:** the buyer has 24 hours (reminder at 12 hours) and can hand it back at any time.
6. **Done:** a short form with the amount, receipt photo, items, what ran out and what was left over. Over the limit → the admin approves first.
7. **Claim:** filed straight away with the amount, currency, description, receipt and employee ID. The refill ID is the reference, so retries never create a duplicate. HR is checked daily; claims pending for more than 10 days are chased.

## Main parts and the data each keeps

| Part | Responsibility | Data |
|---|---|---|
| Offices (config) | Currency, budget, typical range, owed cap, time zone, admin | one row per office |
| People | Who volunteers, where they are | employee ID, home office, volunteer flag, away periods, visits |
| Action catalogue + bot | The fixed actions; who may use each; which buttons to show | audit log of every action |
| Refill service | Lifecycle, atomic accept, deadlines (`tick`) | refill: state, reporters, current offer, who was asked, buyer, deadline, limit, history |
| Assignment | Eligibility and fair ranking (pure functions) | none (derived) |
| Budget | Remaining budget and spending limit | extra budget allowed by admins |
| Purchases | What was bought | amount + currency, items, ran out / left over, receipt, date, exchange rate to NOK |
| Reimbursement | Submit and track HR claims | HR claim ID, status, dates, rejection reason |
| Reporting / insights | Monthly report, shopping hints | none (derived) |
| Ports | Chat, HR, clock, exchange rates as interfaces | simulated in `fakes.py` |

## How the listed problems are prevented

| Problem | Prevention |
|---|---|
| Box empty for days | One named owner at a time, 2 h to reply, 24 h to buy; automatic hand-on; broadcast fallback; admin alerted at closing time |
| Two people buy the same day | One box-empty refill per office; accept is check-and-set under one lock (in production: unique constraint + conditional update); stale buttons are refused |
| A few people do most refills and wait weeks | Ranking by fewest refills in 90 days, then longest since last; people owed more than a cap (2 000 NOK / 5 000 INR) are skipped; claims filed instantly; *My status* shows what's owed; claims older than 10 days are chased |
| Nobody knows spend or what gets eaten | Every purchase is recorded; monthly report per office in local currency plus a combined total in NOK, each purchase converted at its stored purchase-date rate; items and what ran out feed the report and the hints |

## Key assumptions

- Empty is reported by people; there is no sensor. Availability is self-declared, and no reply counts as "no".
- **Visitors** can refill the office they're visiting; the cost is charged to that office's budget in its currency, and HR pays them in their payroll currency.
- The budget is a **hard limit with an admin override**, with no rollover. The month follows the **office's local time**.
- The spending limit is the smaller of what's left and the top of the typical range. Over the limit → admin approval.
- HR returns a claim ID, is polled (no webhooks assumed), and can reject claims. The typed amount is trusted; HR checks the receipt.
- Reporting currency is NOK. The chat tool supports buttons and forms (fallback: numbered replies).

## Trade-offs

- **Direct offer before broadcast:** clear ownership and fairness, at the cost of up to ~6 h in the worst case.
- **Fixed actions instead of free text or AI:** nothing to misread, no AI cost, deterministic tests; anything unusual goes to the admin.
- **Self-declared availability + timeouts:** no integrations needed; a forgotten "away" costs one 2 h timeout.
- **Purchase-date rate stored on each purchase:** reports are reproducible, but may differ slightly from what HR actually pays out.
- **Daily HR polling:** works with any HR API; status can be up to a day old.
- **In-memory store with a lock:** simple to read; production needs the database constraints described above.

## Deliberately not built

A separate UI (chat is the interface) · free-text or AI interpretation (the inputs are finite) · receipt scanning (HR already checks receipts) · sensors · real chat/HR integrations (interfaces show where they plug in) · demand prediction or early warning (needs data first; shopping hints are the day-one version) · company cards (the real long-term fix, but a finance decision) · public-holiday calendars and multi-box offices (configuration extensions).

## Running it

`python3 demo.py` plays one November in both offices as a chat transcript. `python3 -m pytest -v` runs the tests.
