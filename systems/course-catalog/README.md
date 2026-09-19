# Course Catalog & Scheduling

Search the University of Chicago MPCS course catalog and build a schedule that
doesn't double-book you. Reads the **live catalog** at
[mpcs-courses.cs.uchicago.edu](https://mpcs-courses.cs.uchicago.edu/), for any
quarter back to 2015-16, and ships with a snapshot so everything still works
offline.

```
$ course-catalog --schedule "MPCS 53112-1" --code "MPCS 530"
Enrolled (1):
  MPCS 53112-1: Advanced Data Analytics (Wed 17:30-20:30)

2 course(s) — code ~ 'MPCS 530':
  MPCS 53014-1: Big Data Application Architecture (Mon 17:30-20:30)
  MPCS 53001-1: Databases (Tue 17:30-20:30)
```

Anything overlapping what you're already enrolled in is filtered out.

## It builds schedules now, not just checks them

Filtering answers "what still fits?" The question a student actually asks is
the other way round: *given these courses I need and these hours I refuse,
what are my options?* That is a search, not a filter.

```
$ course-catalog --build 4 --require "MPCS 55001,MPCS 53001" \
                 --days-off "Fri,Sat,Sun" --strict-days-off \
                 --no-earlier-than 10:00am --options 2

2 best schedule(s) of 4, cheapest first:

1. MPCS 55001-1, MPCS 53001-1, MPCS 51046-1, MPCS 52560-1
  cost 145
    Tue  14:00-16:50 MPCS 55001-1, 17:30-20:30 MPCS 53001-1
    Wed  14:30-17:20 MPCS 51046-1, 17:30-20:30 MPCS 52560-1
    why: extra_days 120, gaps 25

searched 320 nodes
```

Four courses, two days on campus, nothing before 10am, 25 idle minutes.

Every preference is scored in one unit — **minutes of annoyance** — so the
total is interpretable instead of an arbitrary weighted sum, and `why:` names
what actually drove it. Preferences are soft by default: a hard "nothing before
10am" can make a schedule impossible and report nothing, which is less useful
than being shown the 9:30 option with its cost spelled out. `--strict-days-off`
opts into a hard constraint where you want one.

### Sections are alternatives, not additions

`MPCS 55001-1` and `MPCS 55001-2` are the same Algorithms course at two
different times. A schedule may contain either, never both — and picking *which
section* is most of the value, because no filter over the catalog can do it. If
a 6:30 seminar rules out the 6:00 section, only a search will switch you to the
7:30 one.

This also surfaced a bug in the old `build_schedule`: it checked times and
nothing else, and two sections of one course deliberately *don't* overlap, so

```python
build_schedule(catalog, ["MPCS 55001-1", "MPCS 55001-2"])
```

happily enrolled you in Algorithms twice, under two different instructors. It
now rejects that.

### Why it is branch-and-bound

Choosing 4 courses from a 164-section catalog is 29 million combinations. Two
prunes cut it down:

1. **Conflicts.** A partial schedule that already clashes cannot be rescued by
   adding to it, so the branch dies at depth 2 instead of depth 4.
2. **Cost.** Every penalty except gaps only grows as courses are added, so a
   partial schedule's accumulated penalty is a lower bound on anything below
   it, and the branch can be cut the moment that bound reaches the cost of the
   worst schedule currently kept.

Gaps are the subtle term. They are **not** monotone — inserting a class into an
idle afternoon *reduces* total gap time by the length of the class — so a bound
that assumed gaps only grow would prune the gap-filling schedule, which is
usually the best one. The admissible version subtracts the most the remaining
picks could possibly fill. There's a test for exactly that case.

Measured on a synthetic 164-section, 80-course catalog, best 4-course schedule,
no preferences:

| | time | |
|---|---:|---|
| conflict pruning only | 137 s | |
| + cost bound, exhaustive | 19 s | 4.9M nodes, proven optimal |
| + default 200k node budget | 0.8 s | same cheapest cost, not proven |

The bundled 30-course catalog searches in 320 nodes. A test cross-checks the
bound against brute force, because a pruning bug that loses the optimum is
invisible — you still get a plausible schedule.

### It says whether the answer is proven

`search()` returns a `SearchResult` carrying `proven_optimal`. "These are the 5
best" and "these are the 5 best I had time to find" are different claims, and
reporting the second as the first would be the real bug. Two rules keep the
anytime behaviour honest: the budget never fires before at least one complete
schedule exists — an anytime algorithm that answers *nothing* is worse than a
slow one — and past a hard ceiling it gives up anyway, because the constraints
may simply be unsatisfiable and proving that can cost the whole tree.


## Live, by quarter

The bundled CSV used to be hand-maintained, which is why it went stale: the
department publishes a new quarter and the file doesn't change.

```bash
course-catalog --list-quarters              # 48 quarters, 2015-16 to now
course-catalog --quarter current --build 4  # newest published quarter
course-catalog --quarter 2026-27/winter --code "MPCS 55"
python -m course_catalog.snapshot           # refresh the bundled CSV
```

There's no API, so this parses the listing table. Three things about that table
each cost me a wrong guess first:

**Multiple meetings are separated by `<br/>` inside one cell.** A course that
meets twice a week reads `Tuesday 2pm - 3:20pm<br/>Thursday 2pm - 3:20pm`, and
stripping tags before splitting glues it into `3:20pmThursday`, which parses as
nothing. The split has to happen on the markup.

**Minutes are omitted when they're zero.** `Monday 6pm - 8pm` sits beside
`Monday 5:30pm - 8:30pm` on the same page. The time parser used to *reject*
`6pm` as malformed — there was a test asserting it — so it dropped real
courses. The real catalog settled that argument.

**A quarter is published before its times are set.** Winter 2026-27 went up
with all thirty courses and not one meeting time. That state is normal, and it
breaks the solver in a way worth stating plainly:

> A course with no meeting time conflicts with nothing, occupies no day and
> leaves no gap — so it scores **zero**, which beats every real timetable. Left
> in, the "best schedule" for a partly-published quarter is the one that
> schedules nothing at all.

So unplaceable courses are excluded from the search by default, the count is
reported, and `--include-unscheduled` opts back in. They remain searchable:
a course you can't put on a calendar is still a course you can look up.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

course-catalog                                   # everything
course-catalog --code "MPCS 511"                 # code prefix
course-catalog --keyword algorithms              # title or instructor
course-catalog --day tuesday                     # by day
course-catalog --schedule "MPCS 51040-1" --free  # what still fits
course-catalog --quarter 2025-26/spring          # any quarter, live

# build a schedule rather than filter one
course-catalog --build 3 --no-earlier-than 10:00am --days-off Fri
course-catalog --build 4 --require "MPCS 55001" --among "MPCS 53001,MPCS 51046,MPCS 52560,MPCS 51400"
course-catalog --build 3 --prefer-instructor "Chaudhary" --options 5

pytest -q       # 190 tests
ruff check .
```

## Layout

```
src/course_catalog/
  meeting.py   Day, Meeting, time parsing, overlap   (pure)
  catalog.py   Course, Catalog, search, scheduling   (pure)
  solver.py    preferences, scoring, branch-and-bound  (pure)
  mpcs.py      quarters, listing parsing, fetching     (parse is pure)
  snapshot.py  write a fetched catalog back to CSV
  cli.py       argument parsing and output
  data/        the bundled catalog CSV
```

## Modelling decision

A meeting is a day plus a **half-open** minute interval `[start, end)`. That's
the whole conflict rule:

```python
self.start < other.end and other.start < self.end
```

Half-open matters. A class ending at 7:30pm and another starting at 7:30pm are
back to back, not a conflict — a closed interval would reject a perfectly valid
schedule. There's a test for exactly that pair.

Times are stored as minutes since midnight, so 12:00am → 0 and 12:00pm → 720.
Those two are the cases that break naive AM/PM arithmetic, and both are tested.

## Bugs this version fixes

**Prefix search was actually substring search.**

```python
matched = [c for c in courses if prefix in c.code]   # substring
```

The docstring promised "code starts with the given prefix". Searching `"530"`
matched `MPCS 53014-1` — but via the digits in the *middle* of the number, not
the start. Every result looked plausible, which is why it went unnoticed.
Matching is now a real prefix test against the full code *and* the bare number,
so both `"MPCS 530"` and `"530"` work.

**The default data path could never load.**

```python
def __init__(self, filename="data/courses.csv"):
    file_path = Path(__file__).parent / filename
```

`__file__` was `notebooks/catalog.py`, so this resolved to
`notebooks/data/courses.csv` — but `data/` was a sibling of `notebooks/`, not a
child. The default always raised. The CSV is now packaged and read through
`importlib.resources`, so it resolves from an installed wheel too.

**`main.py` hardcoded an absolute path** to
`/Users/anitahuang/anita-huangz.github.io/systems/Course Catalog and Scheduling System/data/courses.csv`
— a directory that no longer exists, on one specific machine.

Also fixed:

- Malformed times parsed into plausible-looking numbers instead of raising, so
  a typo in the catalog silently misplaced a class. Times now validate, and a
  bad row reports its line number.
- A course already in your schedule was offered back to you as an option — it
  conflicts with itself.
- A meeting ending before it starts was accepted.
- `build_schedule` now rejects unknown codes rather than dropping them; a
  schedule that silently ignored a typo would look conflict-free for the wrong
  reason.

## Notes

- Day names accept `Mon`, `Monday`, or `MONDAYS`.
- Multiple meetings per course are separated by `;` and conflict independently
  — a Tue/Thu course clashes with anything on either day.
- A course with an empty meeting-times field is kept and reported as
  `unscheduled`; it conflicts with nothing.
