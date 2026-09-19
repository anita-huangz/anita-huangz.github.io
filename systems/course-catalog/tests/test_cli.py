"""The command line and the snapshot writer, exercised offline.

Between them these were the largest untested gap in the project, and the
reason it sat below everything around it.

Nothing here touches the network. The filtering and scheduling tests run
against the bundled CSV; the flags that fetch live -- `--list-quarters`,
`--quarter`, and the whole snapshot generator the weekly refresh job runs --
work by replacing `fetch_quarters` and `fetch_catalog` at the module that
calls them. That covers the code CI could otherwise never reach, including
the paths that only run when the department's site is down.
"""

import csv
from typing import ClassVar

import pytest

from course_catalog import cli as cli_module
from course_catalog import snapshot
from course_catalog.catalog import Catalog, Course
from course_catalog.cli import main
from course_catalog.meeting import Day, Meeting
from course_catalog.mpcs import CatalogUnavailable, parse_quarter
from course_catalog.snapshot import write_csv


class TestSearch:
    def test_it_lists_the_bundled_catalog(self, capsys):
        assert main([]) == 0
        assert capsys.readouterr().out.strip()

    def test_a_code_prefix_filters(self, capsys):
        assert main(["--code", "MPCS 55001"]) == 0
        out = capsys.readouterr().out
        assert "55001" in out

    def test_a_keyword_matches_title_or_instructor(self, capsys):
        assert main(["--keyword", "algorithms"]) == 0
        assert capsys.readouterr().out.strip()

    def test_a_day_filter_runs(self, capsys):
        assert main(["--day", "Tue"]) == 0
        assert capsys.readouterr().out.strip()

    def test_an_impossible_filter_says_so_rather_than_printing_nothing(self, capsys):
        # Silence on an empty result reads as a crash. The count and the filter
        # that produced it both have to appear, so the user can see it was the
        # query that matched nothing rather than the catalogue that failed.
        assert main(["--code", "MPCS 99999"]) == 0
        out = capsys.readouterr().out
        assert "0 course(s)" in out
        assert "MPCS 99999" in out


class TestScheduleBuilding:
    def test_it_builds_a_schedule(self, capsys):
        assert main(["--build", "3", "--options", "1"]) == 0
        out = capsys.readouterr().out
        assert "cost" in out.lower()

    def test_preferences_are_honoured_as_costs_not_crashes(self, capsys):
        assert main([
            "--build", "3", "--options", "1",
            "--no-earlier-than", "10am", "--days-off", "Fri,Sat,Sun",
        ]) == 0
        assert "cost" in capsys.readouterr().out.lower()

    def test_a_hard_days_off_constraint_runs(self, capsys):
        assert main([
            "--build", "2", "--options", "1",
            "--days-off", "Sat,Sun", "--strict-days-off",
        ]) == 0
        assert capsys.readouterr().out.strip()

    def test_it_reports_how_much_of_the_search_it_did(self, capsys):
        assert main(["--build", "3", "--options", "1"]) == 0
        assert "nodes" in capsys.readouterr().out.lower()

    def test_an_unbuildable_size_is_reported_not_raised(self, capsys):
        """More courses than the catalog can supply conflict-free."""
        assert main(["--build", "99", "--options", "1"]) in (0, 1)
        captured = capsys.readouterr()
        assert (captured.out + captured.err).strip()


class TestBadInput:
    def test_a_missing_csv_is_reported_not_raised(self, capsys):
        assert main(["--csv", "does-not-exist.csv"]) == 1
        assert "error" in capsys.readouterr().err.lower()

    def test_an_unparseable_time_is_reported(self, capsys):
        # 2 rather than 1: a malformed argument is a usage error, which is what
        # argparse itself returns. A missing file above is a runtime failure
        # and returns 1. The split is deliberate and worth pinning.
        assert main(["--build", "2", "--no-earlier-than", "half past ten"]) == 2
        assert "error" in capsys.readouterr().err.lower()

    def test_an_unknown_flag_exits_nonzero(self):
        with pytest.raises(SystemExit) as exit:
            main(["--not-a-real-flag"])
        assert exit.value.code != 0

    def test_help_exits_cleanly(self):
        with pytest.raises(SystemExit) as exit:
            main(["--help"])
        assert exit.value.code == 0


class TestSnapshotWriter:
    def test_it_round_trips_through_the_loader(self, tmp_path, capsys):
        """A snapshot nobody can read back is not a snapshot."""
        from course_catalog.mpcs import parse_listing

        # A tbody is required: the parser anchors on it rather than on the
        # table, because the page wraps its header row in a thead.
        html = (
            "<table><tbody><tr><td>MPCS 51040-1</td><td>Intro</td>"
            "<td>A Teacher</td><td>Monday 6:00pm - 8:00pm</td></tr></tbody></table>"
        )
        courses = parse_listing(html)
        out = tmp_path / "snap.csv"
        write_csv(courses, out)

        rows = list(csv.DictReader(out.open()))
        assert len(rows) == len(courses)
        assert main(["--csv", str(out)]) == 0
        assert capsys.readouterr().out.strip()

    def test_it_writes_a_header_even_with_no_courses(self, tmp_path):
        out = tmp_path / "empty.csv"
        write_csv([], out)
        assert out.read_text().strip(), "an empty file would not be loadable"


def course(code: str, *, scheduled: bool = True) -> Course:
    """A course with one Monday evening meeting, or none."""
    meetings = (Meeting(Day.MONDAY, 18 * 60, 20 * 60),) if scheduled else ()
    return Course(
        code=code,
        name=f"Course {code}",
        instructor="A Teacher",
        location="Ryerson 251",
        meetings=meetings,
    )


class TestNewestScheduledQuarter:
    """Which quarter a snapshot should come from.

    The department publishes a quarter's course list months before its meeting
    times, so the newest quarter is usually unscheduled — and a snapshot with
    no times is useless to a timetable builder, which is the point of the
    project. This walks back until it finds one with real times.
    """

    @staticmethod
    def with_quarters(monkeypatch, catalogs: dict[str, list[Course]]):
        """Serve fixed catalogs, newest first, and record what was fetched."""
        asked: list[str] = []
        quarters = [parse_quarter(q) for q in catalogs]

        def fetch_quarters(*, client=None, **kwargs):
            return quarters

        def fetch_catalog(quarter, *, client=None, **kwargs):
            asked.append(str(quarter))
            return Catalog(catalogs[str(quarter)])

        monkeypatch.setattr(snapshot, "fetch_quarters", fetch_quarters)
        monkeypatch.setattr(snapshot, "fetch_catalog", fetch_catalog)
        return asked

    def test_an_unscheduled_quarter_is_walked_past(self, monkeypatch):
        asked = self.with_quarters(
            monkeypatch,
            {
                "2027-28/autumn": [course(f"MPCS 5{i:04d}", scheduled=False) for i in range(20)],
                "2026-27/spring": [course(f"MPCS 6{i:04d}") for i in range(12)],
            },
        )
        quarter, catalog = snapshot.newest_scheduled_quarter()
        assert str(quarter) == "2026-27/spring"
        assert len(catalog) == 12
        assert asked == ["2027-28/autumn", "2026-27/spring"], "it should stop at the first hit"

    def test_a_partially_scheduled_quarter_below_the_floor_does_not_count(self, monkeypatch):
        # A handful of times published early is not a usable snapshot either.
        self.with_quarters(
            monkeypatch,
            {
                "2027-28/autumn": [course("MPCS 50001")] + [
                    course(f"MPCS 5{i:04d}", scheduled=False) for i in range(20)
                ],
                "2026-27/spring": [course(f"MPCS 6{i:04d}") for i in range(12)],
            },
        )
        quarter, _ = snapshot.newest_scheduled_quarter(minimum=10)
        assert str(quarter) == "2026-27/spring"

    def test_the_floor_is_adjustable(self, monkeypatch):
        self.with_quarters(monkeypatch, {"2027-28/autumn": [course("MPCS 50001")]})
        quarter, _ = snapshot.newest_scheduled_quarter(minimum=1)
        assert str(quarter) == "2027-28/autumn"

    def test_no_quarter_with_times_is_an_error_not_an_empty_snapshot(self, monkeypatch):
        # Writing an empty CSV here would replace good bundled data with
        # nothing, on a schedule, with no one watching.
        self.with_quarters(
            monkeypatch, {"2027-28/autumn": [course("MPCS 50001", scheduled=False)]}
        )
        with pytest.raises(CatalogUnavailable, match="no quarter has published"):
            snapshot.newest_scheduled_quarter()


class TestSnapshotCommand:
    """`python -m course_catalog.snapshot`, which the weekly refresh runs."""

    @staticmethod
    def serve(monkeypatch, courses, quarters=("2026-27/autumn",)):
        monkeypatch.setattr(
            snapshot, "fetch_quarters", lambda **k: [parse_quarter(q) for q in quarters]
        )
        monkeypatch.setattr(snapshot, "fetch_catalog", lambda q, **k: Catalog(courses))

    def test_it_writes_a_snapshot_that_reads_back(self, monkeypatch, tmp_path, capsys):
        courses = [course(f"MPCS 5{i:04d}") for i in range(12)]
        self.serve(monkeypatch, courses)
        out = tmp_path / "courses.csv"

        assert snapshot.main(["--quarter", "2026-27/autumn", "--out", str(out)]) == 0
        assert len(Catalog.from_csv(out)) == 12
        printed = capsys.readouterr().out
        assert "12 course(s), 12 with meeting times" in printed
        assert str(out) in printed

    def test_current_resolves_to_the_newest_scheduled_quarter(self, monkeypatch, tmp_path, capsys):
        self.serve(
            monkeypatch,
            [course(f"MPCS 5{i:04d}") for i in range(12)],
            quarters=("2026-27/autumn",),
        )
        out = tmp_path / "courses.csv"
        assert snapshot.main(["--quarter", "current", "--out", str(out)]) == 0
        assert "2026-27" in capsys.readouterr().out

    @pytest.mark.parametrize("word", ["current", "LATEST", "Newest"])
    def test_the_aliases_for_current_are_case_insensitive(self, monkeypatch, tmp_path, word):
        self.serve(monkeypatch, [course(f"MPCS 5{i:04d}") for i in range(12)])
        assert snapshot.main([f"--quarter={word}", "--out", str(tmp_path / "c.csv")]) == 0

    def test_a_malformed_quarter_is_reported_not_raised(self, monkeypatch, tmp_path, capsys):
        self.serve(monkeypatch, [course("MPCS 50001")])
        assert snapshot.main(["--quarter", "not-a-quarter", "--out", str(tmp_path / "c.csv")]) == 1
        assert "error:" in capsys.readouterr().err

    def test_an_unreachable_catalog_leaves_the_existing_file_alone(
        self, monkeypatch, tmp_path, capsys
    ):
        # The refresh job runs unattended against a live site. A fetch failure
        # must not truncate the bundled CSV on its way out.
        out = tmp_path / "courses.csv"
        out.write_text("code,name,instructor,location,meeting times\n")
        before = out.read_text()

        def unavailable(*args, **kwargs):
            raise CatalogUnavailable("https://example.edu", "502 Bad Gateway")

        monkeypatch.setattr(snapshot, "fetch_catalog", unavailable)
        assert snapshot.main(["--quarter", "2026-27/autumn", "--out", str(out)]) == 1
        assert "502 Bad Gateway" in capsys.readouterr().err
        assert out.read_text() == before

    def test_a_snapshot_that_does_not_read_back_fails_the_job(
        self, monkeypatch, tmp_path, capsys
    ):
        # The round-trip check is the only thing standing between a subtly
        # malformed writer and a committed file nothing can load, so it has to
        # actually fail rather than warn.
        self.serve(monkeypatch, [course(f"MPCS 5{i:04d}") for i in range(12)])
        monkeypatch.setattr(
            snapshot.Catalog, "from_csv", classmethod(lambda cls, path: Catalog([]))
        )
        assert snapshot.main(["--quarter", "2026-27/autumn", "--out", str(tmp_path / "c.csv")]) == 1
        assert "read back 0" in capsys.readouterr().err

    def test_help_exits_cleanly(self):
        with pytest.raises(SystemExit) as exit:
            snapshot.main(["--help"])
        assert exit.value.code == 0


class TestSnapshotFileFormat:
    def test_lines_end_with_lf_so_the_weekly_refresh_sees_no_spurious_change(self, tmp_path):
        # `csv` defaults to CRLF; git normalises on commit, so a CRLF file on
        # disk differs from the committed one and the refresh job reports a
        # change every single week.
        out = tmp_path / "c.csv"
        write_csv([course("MPCS 50001")], out)
        assert b"\r\n" not in out.read_bytes()

    def test_rows_are_sorted_by_code_so_diffs_stay_readable(self, tmp_path):
        out = tmp_path / "c.csv"
        write_csv([course("MPCS 52000"), course("MPCS 51000")], out)
        codes = [row["code"] for row in csv.DictReader(out.open())]
        assert codes == ["MPCS 51000", "MPCS 52000"]

    def test_meetings_are_written_in_the_form_the_parser_accepts(self, tmp_path):
        # `str(Meeting)` is a shorter 24-hour form for the terminal that
        # `Meeting.parse` cannot read back.
        out = tmp_path / "c.csv"
        write_csv([course("MPCS 50001")], out)
        row = next(csv.DictReader(out.open()))
        assert row["meeting times"] == "Monday 6:00pm - 8:00pm"


class TestLiveCatalogPaths:
    """The flags that reach the department's site, exercised offline.

    These are the branches a reader is most likely to try first and the ones a
    test suite is most likely to skip, because they are the ones that need the
    network. Patching the two fetch functions at the CLI's own namespace keeps
    them honest without one.
    """

    QUARTERS: ClassVar[list[str]] = ["2026-27/autumn", "2025-26/spring"]

    @staticmethod
    def serve(monkeypatch, *, quarters=None, courses=None, fail=None):
        quarter_objects = [parse_quarter(q) for q in (quarters or TestLiveCatalogPaths.QUARTERS)]
        asked: list[str] = []

        def fetch_quarters(**kwargs):
            if fail == "quarters":
                raise CatalogUnavailable("https://mpcs.uchicago.edu", "connection refused")
            return quarter_objects

        def fetch_catalog(quarter, **kwargs):
            if fail == "catalog":
                raise CatalogUnavailable("https://mpcs.uchicago.edu", "502 Bad Gateway")
            asked.append(str(quarter))
            return Catalog(courses or [course("MPCS 51040"), course("MPCS 52011")])

        monkeypatch.setattr(cli_module, "fetch_quarters", fetch_quarters)
        monkeypatch.setattr(cli_module, "fetch_catalog", fetch_catalog)
        return asked

    def test_list_quarters_prints_what_is_published(self, monkeypatch, capsys):
        self.serve(monkeypatch)
        assert main(["--list-quarters"]) == 0
        out = capsys.readouterr().out
        assert "2 quarter(s)" in out
        assert "2026-27/autumn" in out

    def test_list_quarters_reports_an_outage_rather_than_a_traceback(
        self, monkeypatch, capsys
    ):
        self.serve(monkeypatch, fail="quarters")
        assert main(["--list-quarters"]) == 1
        assert "connection refused" in capsys.readouterr().err

    def test_a_named_quarter_is_fetched_live_and_labelled_as_such(self, monkeypatch, capsys):
        asked = self.serve(monkeypatch)
        assert main(["--quarter", "2026-27/autumn"]) == 0
        assert asked == ["2026-27/autumn"]
        assert "live from the department" in capsys.readouterr().out

    def test_current_takes_the_newest_published_quarter(self, monkeypatch, capsys):
        asked = self.serve(monkeypatch)
        assert main(["--quarter", "current"]) == 0
        assert asked == ["2026-27/autumn"], "the list is newest-first"
        capsys.readouterr()

    def test_an_unreachable_department_site_suggests_list_quarters(
        self, monkeypatch, capsys
    ):
        self.serve(monkeypatch, fail="catalog")
        assert main(["--quarter", "2026-27/autumn"]) == 1
        err = capsys.readouterr().err
        assert "502 Bad Gateway" in err
        assert "--list-quarters" in err, "the error should say how to recover"

    def test_a_malformed_quarter_is_a_user_error(self, monkeypatch, capsys):
        self.serve(monkeypatch)
        assert main(["--quarter", "sometime-soon"]) == 1
        assert "error:" in capsys.readouterr().err

    def test_courses_without_times_are_counted_where_the_reader_will_see_it(
        self, monkeypatch, capsys
    ):
        # Printed to stdout directly under the total it qualifies. On stderr it
        # interleaves above the count and reads like a failure.
        self.serve(
            monkeypatch,
            courses=[course("MPCS 51040"), course("MPCS 52011", scheduled=False)],
        )
        assert main(["--quarter", "2026-27/autumn"]) == 0
        out = capsys.readouterr().out
        assert "1 of them have no published meeting time" in out
        assert out.index("2 course(s)") < out.index("1 of them")


class TestUnschedulableCourses:
    """Courses with no published time need saying out loud, not dropping.

    They conflict with nothing, so they score zero and would outrank every
    real timetable — which is why they are excluded by default and the
    exclusion is reported rather than silent.
    """

    @staticmethod
    def csv_of(courses, tmp_path):
        path = tmp_path / "catalog.csv"
        write_csv(courses, path)
        return str(path)

    def test_the_count_set_aside_is_reported_when_nothing_can_be_built(
        self, tmp_path, capsys
    ):
        path = self.csv_of(
            [course(f"MPCS 5{i:04d}", scheduled=False) for i in range(4)], tmp_path
        )
        assert main(["--csv", path, "--build", "2"]) == 1
        out = capsys.readouterr().out
        assert "No conflict-free schedule" in out
        assert "4 course(s) were set aside" in out

    def test_including_them_is_opt_in_and_then_they_can_be_scheduled(
        self, tmp_path, capsys
    ):
        path = self.csv_of(
            [course(f"MPCS 5{i:04d}", scheduled=False) for i in range(4)], tmp_path
        )
        assert main(["--csv", path, "--build", "2", "--include-unscheduled"]) == 0
        assert "best schedule(s)" in capsys.readouterr().out

    def test_a_successful_build_still_reports_what_it_left_out(self, tmp_path, capsys):
        courses = [
            Course("MPCS 51040", "A", "T", "R251", (Meeting(Day.MONDAY, 1080, 1200),)),
            Course("MPCS 52011", "B", "T", "R251", (Meeting(Day.TUESDAY, 1080, 1200),)),
            course("MPCS 53000", scheduled=False),
        ]
        assert main(["--csv", self.csv_of(courses, tmp_path), "--build", "2"]) == 0
        assert "1 course(s) set aside" in capsys.readouterr().out


class TestMoreBadInput:
    def test_an_unknown_day_is_a_user_error(self, capsys):
        assert main(["--day", "Blursday"]) == 2
        assert "error:" in capsys.readouterr().err

    def test_an_unknown_course_in_a_schedule_is_a_user_error(self, capsys):
        assert main(["--schedule", "MPCS 00000"]) == 2
        assert "error:" in capsys.readouterr().err

    def test_a_free_filter_needs_a_schedule_to_be_free_of(self, capsys):
        assert main(["--free", "--schedule", "MPCS 51040"]) in (0, 2)
        capsys.readouterr()
