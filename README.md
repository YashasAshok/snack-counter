# Snack Counter Automation

Core logic for a chat bot that keeps the Oslo and Bengaluru snack boxes stocked: it picks a buyer fairly, hands refills on when nobody acts, prevents double purchases, checks the budget, files HR claims automatically and produces the monthly report.

The chat tool and the HR system are simulated (`snack_counter/fakes.py`). Design: [`docs/design.md`](docs/design.md).

## Run it

Python 3.10 or newer. Only the tests need an extra package (`pytest`).

```bash
python3 demo.py            # one November in both offices, printed as a chat transcript
python3 -m pytest -v       # the tests
```

## Layout

```
snack_counter/
  money.py           Money: exact decimals, one currency; mixing NOK and INR raises an error
  models.py          Office, Person, Refill (+ states), Purchase, Claim
  actions.py         the fixed list of actions: label, who may use it, what the form asks for
  bot.py             button taps → checks → service; which buttons each person sees
  refill_service.py  the lifecycle, atomic accept, deadlines (tick)
  assignment.py      who is eligible, fairest first (pure functions)
  budget.py          remaining budget and spending limit
  reimbursement.py   filing HR claims (never twice), checking status, chasing slow ones
  reporting.py       monthly report per office + combined total in NOK
  insights.py        shopping hints from what ran out / was left over
  ports.py           interfaces: chat, HR, clock, exchange rates
  fakes.py           simulated chat, HR, clock and exchange rates
  store.py           in-memory storage (+ the database constraints production needs)
  config.py          every timeout and limit in one place
  app.py             wires it together; run_until() moves the simulated clock
  sample_data.py     the offices and people used by the demo and tests
demo.py              scripted demo
tests/               one file per rule area, plus an end-to-end run of the demo
docs/design.md       design document
```

## The rules the tests prove

| Rule | Tests |
|---|---|
| Two people can't both commit to the same refill | `test_concurrency.py` (two threads tap at the same instant, 20 runs) |
| A second "empty" report doesn't create a second refill | `test_lifecycle.py`, `test_concurrency.py` |
| An offer nobody answers, or a refill nobody finishes, goes to someone else | `test_timeouts.py` |
| Buyers are chosen fairly; away, busy and owed-too-much people are skipped | `test_assignment.py` |
| Visitors can refill the office they're visiting, charged to that office | `test_visitors.py` |
| Budgets per office, per local month; limits; blocking; admin approval | `test_budget.py` |
| Currencies are never mixed; the report totals are right across both | `test_money.py`, `test_reporting.py` |
| HR claims are filed automatically, never duplicated, tracked and chased | `test_reimbursement.py` |
| Only the right people can do each action; stale buttons do nothing | `test_bot.py` |
| Shopping hints | `test_insights.py` |
| The whole demo month adds up | `test_end_to_end.py` |
