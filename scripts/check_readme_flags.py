#!/usr/bin/env python3
"""Fail when a README documents a command-line flag the parser does not have.

This has happened: the earnings-drift README once described a `--buckets`
flag that was never implemented. A reader who copies a command out of a
README and gets `unrecognized arguments` learns something about the project
that no amount of test coverage makes up for.

Only the project's *own* commands are checked. A fenced block may legitimately
run `docker compose up --build` or `pytest -q --cov`, and those flags belong to
someone else's parser -- so a line is only inspected when it invokes a console
script declared in `pyproject.toml` or a `python -m <package>` entry point.
That is what makes this precise enough to run without an allowlist of
third-party flags to keep up to date.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent

#: `--flag`, long form only. Short flags are too easy to confuse with a minus.
FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")

#: argparse gives these to every parser without being asked.
BUILT_IN = {"--help"}


def commands(project: Path) -> set[str]:
    """Names that invoke this project: its console scripts and its modules."""
    config = tomllib.loads((project / "pyproject.toml").read_text())
    scripts = set(config.get("project", {}).get("scripts", {}))
    # Importable packages, both the installed ones under src/ and any that sit
    # beside it -- the AI platform runs its eval harness as `python -m evals.*`.
    packages = {
        d.name
        for parent in (project / "src", project)
        if parent.is_dir()
        for d in parent.iterdir()
        if d.is_dir() and (d / "__init__.py").exists()
    }
    return scripts | packages


def declared_flags(project: Path) -> set[str]:
    """Every long flag mentioned anywhere in the project's Python."""
    found: set[str] = set()
    for path in project.rglob("*.py"):
        if any(part in {".venv", "build", "node_modules"} for part in path.parts):
            continue
        found |= set(FLAG.findall(path.read_text(errors="replace")))
    return found


#: An inline code span. A flag written as `--offline` in prose is as much a
#: claim about this project's interface as one written in a shell block, and
#: across every README here not one such mention belongs to another tool.
INLINE = re.compile(r"`([^`]*)`")


def _invocation(line: str, names: set[str]) -> str | None:
    """The project command a shell line runs, if it runs one.

    Strips what precedes the command: a blockquote marker, a prompt, and any
    `VAR=value` assignments -- the AI platform's record command is written
    `FILING_INTEL_REPLAY_RECORD=true ... python -m evals.harness`.
    """
    stripped = line.lstrip("> ").lstrip("$ ").strip()
    head = [w for w in stripped.split() if "=" not in w.split("/")[0] or w.startswith("-")]
    if not head:
        return None
    if len(head) >= 3 and Path(head[0]).name.startswith("python") and head[1] == "-m":
        return head[2].split(".")[0]
    return head[0] if head[0] in names else None


def documented_flags(readme: Path, names: set[str]) -> list[tuple[int, str, str]]:
    """Every flag the README attributes to this project. (line, command, flag)."""
    out = []
    for number, line in enumerate(readme.read_text(errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        invoked = _invocation(line, names)
        if invoked in names:
            for flag in FLAG.findall(line):
                out.append((number, invoked, flag))
            continue
        # Not a command line: still check anything in backticks.
        for span in INLINE.findall(line):
            for flag in FLAG.findall(span):
                out.append((number, "documented", flag))
    return out


def check(relative: str) -> list[str]:
    project = ROOT / relative
    readme = project / "README.md"
    if not readme.exists():
        return []
    names = commands(project)
    known = declared_flags(project) | BUILT_IN
    problems = []
    checked = 0
    for number, command, flag in documented_flags(readme, names):
        checked += 1
        if flag not in known:
            problems.append(
                f"{relative}/README.md:{number}: `{command} {flag}` -- no such flag"
            )
    print(f"{relative}: {checked} documented flag use(s) checked")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", help="Project directory, e.g. systems/fastcache.")
    args = parser.parse_args(argv)

    problems = check(args.project.rstrip("/"))
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
