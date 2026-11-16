# Questions and assumptions

The brief invites questions before starting. For this take-home I've written down the questions I would have asked, the assumption I built on for each, why, and what would change if the answer is different.

Most assumptions live in one place in the code (`snack_counter/config.py`, the office settings in `sample_data.py`, or a single function), so a different answer usually means a small, local change.

---

## Detecting an empty box

### 1. How do we know a box is empty?
- **Assumed:** a person reports it with one tap in the chat bot. A QR code on the box opens the bot with the office already filled in. There is no sensor.
- **Why:** everyone already has the chat tool. A sensor adds hardware to buy and maintain for a snack box.
- **If different:** a sensor would call the same `report_empty()` action. Nothing else changes.

### 2. Is there one snack box per office?
- **Assumed:** yes, so the rule is "at most one active refill per office".
- **If different:** the rule becomes one active refill per (office, box).

## Availability, hybrid work and holidays

### 3. Where does volunteers' availability come from?
- **Assumed:** there is no calendar, leave or desk-booking integration. Volunteers set "away" with a date picker in the bot, and no reply to an offer within 2 hours counts as "no".
- **Why:** integrations with systems we don't control are uncertain. The timeout keeps the process safe even when someone forgets to set "away"; it costs at most 2 hours.
- **If different:** calendar or leave data becomes one more check in `assignment.why_not_eligible()`.

### 4. When should people be asked?
- **Assumed:** offers go out only during office hours, Monday to Friday, 09:00–17:00 in the office's local time. Times are stored in UTC, and the budget month follows the office's local time. Public holidays are out of scope.
- **Why:** nobody buys snacks for a closed office, and messages late at night are bad for the people receiving them.
- **If different:** the hours and working days are in `config.Settings`. A holiday calendar would be another check in the same place.

### 5. How quickly should a refill happen?
- **Assumed:** within one working day. Each person has 2 hours to reply. After 3 people don't take it, it goes to everyone eligible. Whoever accepts has 24 hours to buy, with a reminder at 12 hours. If nobody has taken it by closing time, the office admin is alerted.
- **Why:** the brief's complaint is boxes sitting empty "for days".
- **If different:** every one of these numbers is in `config.Settings`.

## Volunteers and visitors

### 6. Who manages the volunteer list?
- **Assumed:** each office has an admin (for example the office manager) who manages the list. People can also join or leave themselves. Anyone can report an empty box, but only volunteers are asked to buy. The admin also handles escalations and budget overrides.
- **Why:** volunteering is voluntary, and some decisions need a named person.

### 7. Can someone visiting the other office refill its box? Whose budget pays?
- **Assumed:** yes. Who can be asked depends on where a person is *today*, not their home office. The cost is charged to the budget of the office whose box was refilled, in that office's currency. The claim is filed in the purchase currency, and HR pays the person back in their payroll currency.
- **Why:** the budget belongs to the box. The brief says HR handles the payroll currency, so the system never converts money for reimbursement.

## Choosing who buys

### 8. What does "fair" mean when choosing a buyer?
- **Assumed:** the person with the fewest refills in the last 90 days goes first. Ties go to whoever refilled longest ago, then to the lowest employee ID. Anyone owed more than a cap in unpaid claims (2 000 NOK in Oslo, 5 000 INR in Bengaluru) is skipped until they've been paid back.
- **Why:** this addresses "a few people do most refills and wait weeks for their money" directly. It's also simple to explain: "why was I picked?" has an exact answer.
- **If different:** the rules are in `assignment.why_not_eligible()` and `assignment.rank()`.

### 9. Ask one person, or post it to everyone?
- **Assumed:** ask one named person first (up to 3 people in turn), then offer it to everyone eligible, where the first to accept gets it. Accepting is atomic, so two people can never both commit.
- **Why:** asking one named person removes "someone else will do it". Offering it to everyone is the faster fallback.

## Budget

### 10. Is the monthly budget a hard limit? Does unused budget roll over?
- **Assumed:** it's a hard limit that the office admin can raise for the month. Unused budget does not roll over. Spending counts in the month of the purchase, in the office's local time.
- **Why:** management set a budget, so the safe default is to respect it, with a person deciding exceptions.

### 11. How much may one buyer spend?
- **Assumed:** the smaller of what's left this month and the top of the typical range (1 200 NOK / 3 000 INR). Once someone accepts a refill, that amount is set aside from what's left.
- **Why:** the volunteer knows the limit up front, and the system never commits more money than remains.

### 12. What about a purchase above the typical range?
- **Assumed:** spending more than the limit sends the purchase to the office admin to approve or reject before any claim reaches HR. Spending less than the typical minimum is fine.
- **Why:** it's rare, and the volunteer has already spent their own money, so a person should decide rather than the system refusing outright.

### 13. What happens when the budget is nearly used up?
- **Assumed:** if less than a typical minimum purchase is left (300 NOK / 500 INR), the refill is blocked and the office admin is told. It restarts automatically when the new month begins, or when the admin allows extra budget.

## Money and the monthly report

### 14. Which currency should management's combined report use?
- **Assumed:** NOK.
- **Why:** head office is most likely in Norway.
- **If different:** it's one value in `config.Settings`.

### 15. Which exchange rate should the report use?
- **Assumed:** the rate on the purchase date, stored with each purchase.
- **Why:** re-running an old report always gives the same number. The rate source sits behind an interface; the tests use a fixed test rate of 0.12 NOK per INR.
- **If different:** for a month-end rate, the conversion happens when the report is built instead.

### 16. When does money count as spent?
- **Assumed:** when the snacks are bought, not when the person is paid back. The report shows both "spent" and "reimbursed so far". Rejected and cancelled refills don't count.
- **Why:** the money left someone's pocket that day, so the budget has to reflect it straight away.

## The HR system

### 17. What does the HR system tell us?
- **Assumed:** creating a claim returns a claim ID straight away. HR doesn't notify us of changes, so we check each claim's status once a day. Claims can be rejected, with a reason.
- **Why:** checking regularly works whether or not HR can send notifications, which is the safest assumption about a system another company runs.
- **If different:** if HR can notify us, those notifications would replace the daily check in `reimbursement.py`.

### 18. What if HR is down, or a request times out?
- **Assumed:** every claim is filed with the refill's ID as its reference, and the system always looks that reference up before creating a claim, so a retry can never create a second one. If HR is down, the claim waits and is retried automatically; the volunteer doesn't need to do anything.
- **Why:** a duplicate claim would mean paying someone twice.

### 19. What causes the slow reimbursements?
- **Assumed:** both late manual submission and HR's 1–10 days to approve. The system removes the first by filing claims instantly. It makes the second visible: volunteers can see what they're owed, claims pending for more than 10 days are chased with the admin, and people who are owed a lot aren't asked to spend more.

## Receipts and snack data

### 20. Can we trust the amount the volunteer enters?
- **Assumed:** yes. The volunteer types the amount, and a receipt photo is required. HR checks the receipt when approving, so HR's approval is the real control. Typos are caught by a review step before submitting, by the over-limit check and by HR. There is no automatic receipt reading.
- **Why:** it would duplicate a check HR already does. Pre-filling the amount from the receipt photo is a possible later addition.

### 21. What does "which snacks actually get eaten" mean?
- **Assumed:** the items ticked when a refill is marked done, plus optional "ran out first" and "left over" ticks, plus how often each office runs out. This feeds the monthly report and a shopping hint shown in each offer.
- **Why:** measuring real consumption would need sensors or manual counting. This is a good-enough proxy that costs nothing extra.

## The chat interface and the build

### 22. Does the chat tool support buttons and forms?
- **Assumed:** yes (for example Slack Block Kit or Microsoft Teams Adaptive Cards).
- **If different:** use numbered replies ("Reply 1 to accept"). It's the same fixed actions, so the core logic doesn't change.

### 23. Should people type free text to the bot?
- **Assumed:** no. Everything anyone needs to tell the bot is a small, fixed set of 19 actions across employees, volunteers and office admins (listed in `snack_counter/actions.py`), so buttons, pickers and short forms are faster and can't be misread. Typed text gets a menu of the available actions.
- **Why:** with a finite set of inputs, there's nothing to interpret, no AI cost, and the tests are fully predictable.

### 24. Are company cards in scope?
- **Assumed:** no. They would remove out-of-pocket spending entirely, which is the real long-term fix, but that's a finance and policy decision rather than software. I'd recommend it.

### 25. What are the build constraints?
- **Assumed:** a Python standard-library implementation with in-memory storage and no separate UI is enough to show the core logic. Production would use a database with a unique constraint on "one active refill per office" and a conditional update when accepting; `snack_counter/store.py` describes this.
