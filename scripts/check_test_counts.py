#!/usr/bin/env python3
"""Fail when a stated test count no longer matches the suite.

Three places advertise how many tests a project has -- its own README, the
entry in the root README, and the `scale` line the portfolio site renders --
and all three drifted badly before this existed: the site claimed 176 tests for
a project that had 268, and the root README's total was 325 short.

A number nobody checks is a number that goes stale, and a stale number in the
one place a reader looks for evidence of rigour is worse than no number.

Two modes, matching how CI runs:

    check_test_counts.py <project>   collect that project's suite and compare
                                     every count claimed about it, then check
                                     the root README's total adds up
    check_test_counts.py --browser N compare the browser count in the root
                                     README and in site/README.md against N
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: "268 tests", "516 Python tests", "1,819 tests" -- the first such phrase in a
#: sentence is the one making the claim.
COUNT = re.compile(r"([\d,]+)\s+(?:Python\s+)?tests\b")


def parse(text: str) -> int:
    return int(text.replace(",", ""))


def collected(project: Path) -> int:
    """How many tests the suite actually has, straight from pytest."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,  # a collection error is reported below, not raised
    )
    match = re.search(r"(\d+) tests? collected", result.stdout)
    if not match:
        sys.exit(
            f"could not collect {project}:\n{result.stdout[-2000:]}{result.stderr[-2000:]}"
        )
    return int(match.group(1))


def claims_in_project_readme(project: Path) -> list[tuple[str, int]]:
    readme = project / "README.md"
    if not readme.exists():
        return []
    return [
        (f"{readme.relative_to(ROOT)}:{n}", parse(m.group(1)))
        for n, line in enumerate(readme.read_text().splitlines(), start=1)
        if (m := COUNT.search(line))
    ]


def claim_in_root_readme(relative: str) -> tuple[str, int] | None:
    """The `](path) · N tests` heading for one project."""
    pattern = re.compile(rf"\]\({re.escape(relative)}\)[^\n]*?·\s*([\d,]+)\s+tests\b")
    for n, line in enumerate((ROOT / "README.md").read_text().splitlines(), start=1):
        if match := pattern.search(line):
            return f"README.md:{n}", parse(match.group(1))
    return None


def claim_in_site_data(relative: str) -> tuple[str, int] | None:
    """The `scale` line of the project's entry in the site's project data."""
    text = (ROOT / "site/src/data/projects.ts").read_text()
    entry = re.search(
        rf'"path":\s*"{re.escape(relative)}".*?"scale":\s*"(.*?)"', text, re.DOTALL
    )
    if not entry:
        return None
    if not (match := COUNT.search(entry.group(1))):
        return None
    return "site/src/data/projects.ts (scale)", parse(match.group(1))


def badge_in_site_data(relative: str) -> tuple[str, int] | None:
    """The numeric `tests` field behind the card badge and the detail header.

    This is the count a visitor actually sees first -- "✓ 268 tests" on the
    card -- and the hero's headline total is the sum of these, not of the
    prose. An earlier version of this script checked only the `scale` string
    and reported every project clean while all fifteen badges were stale.
    """
    text = (ROOT / "site/src/data/projects.ts").read_text()
    entry = re.search(
        rf'"path":\s*"{re.escape(relative)}".*?"tests":\s*(\d+)', text, re.DOTALL
    )
    if not entry:
        return None
    return "site/src/data/projects.ts (tests)", int(entry.group(1))


def totals_line() -> tuple[int, int, int, int]:
    """The headline `N tests -- P in Python, and B in the browser` figures."""
    text = (ROOT / "README.md").read_text()
    match = re.search(
        r"\*\*([\d,]+) tests\*\*\s*—\s*([\d,]+) in Python, and ([\d,]+) in the browser",
        text,
    )
    if not match:
        sys.exit("README.md no longer states a test total in the expected form")
    line = text[: match.start()].count("\n") + 1
    return parse(match.group(1)), parse(match.group(2)), parse(match.group(3)), line


def check_project(relative: str) -> list[str]:
    project = ROOT / relative
    actual = collected(project)
    problems = []

    claims = claims_in_project_readme(project)
    for where, claimed in claims:
        if claimed != actual:
            problems.append(f"{where}: claims {claimed} tests, suite has {actual}")

    for finder, label in (
        (claim_in_root_readme, "root README"),
        (claim_in_site_data, "site project data (scale)"),
        (badge_in_site_data, "site card badge"),
    ):
        found = finder(relative)
        if found is None:
            problems.append(f"{label}: no test count found for {relative}")
            continue
        where, claimed = found
        if claimed != actual:
            problems.append(f"{where}: claims {claimed} tests, suite has {actual}")

    print(f"{relative}: {actual} tests, {len(claims) + 3} claim(s) checked")
    return problems


def check_totals() -> list[str]:
    """The headline total has to equal the per-project numbers under it.

    Each of those is verified against a real run by its own CI job, so checking
    the arithmetic here is enough to make the total trustworthy too.
    """
    total, python_total, browser_total, line = totals_line()
    listed = [
        parse(m) for m in re.findall(r"·\s*([\d,]+)\s+tests\b", (ROOT / "README.md").read_text())
    ]
    problems = []
    if sum(listed) != python_total:
        problems.append(
            f"README.md:{line}: says {python_total:,} Python tests, but the "
            f"{len(listed)} projects listed below add up to {sum(listed):,}"
        )
    if python_total + browser_total != total:
        problems.append(
            f"README.md:{line}: {python_total:,} + {browser_total:,} "
            f"is {python_total + browser_total:,}, not {total:,}"
        )
    if not problems:
        print(f"totals: {python_total:,} + {browser_total:,} = {total:,}, and the parts agree")
    return problems


def check_browser(actual: int) -> list[str]:
    _, _, browser_total, line = totals_line()
    problems = []
    if browser_total != actual:
        problems.append(
            f"README.md:{line}: claims {browser_total} browser tests, vitest ran {actual}"
        )
    site_readme = ROOT / "site/README.md"
    for n, text in enumerate(site_readme.read_text().splitlines(), start=1):
        match = COUNT.search(text)
        if match and parse(match.group(1)) != actual:
            problems.append(
                f"site/README.md:{n}: claims {parse(match.group(1))} tests, vitest ran {actual}"
            )
    if not problems:
        print(f"browser: {actual} tests, every claim agrees")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", nargs="?", help="Project directory, e.g. systems/fastcache.")
    parser.add_argument("--browser", type=int, help="Test count vitest just reported.")
    args = parser.parse_args(argv)

    if args.browser is not None:
        problems = check_browser(args.browser)
    elif args.project:
        problems = check_project(args.project.rstrip("/")) + check_totals()
    else:
        parser.error("pass a project directory or --browser N")

    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
