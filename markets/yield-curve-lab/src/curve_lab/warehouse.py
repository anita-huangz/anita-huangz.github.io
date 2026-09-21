"""The curve in DuckDB, and the features that are easier to express in SQL.

DuckDB rather than a hosted warehouse for one reason: this package has to run
offline in CI with no credentials, and a 30-day trial is not a foundation for
something that should still work in a year. The SQL here is ordinary -- window
functions, a join, an unpivot -- so the schema and the queries port to
Snowflake or Postgres unchanged. What does not port is the setup cost, which
is zero.

The warehouse is not decoration. Feature engineering over a term structure is
mostly lags, rolling windows and differences across tenors, and that is what
window functions are for: `LAG(yield, 5) OVER (PARTITION BY tenor ORDER BY
date)` says what it means, where the pandas equivalent is a groupby-shift that
silently misaligns if the frame is not sorted. The `long` table makes the
partition natural.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

from .data import TENORS, Curve

#: Schema, created on open. `wide` is the snapshot as loaded; `long` is the
#: same data one row per tenor per day, which is the shape window functions
#: and the API both want.
SCHEMA = """
CREATE OR REPLACE TABLE curve_wide AS SELECT * FROM curve_input;

CREATE OR REPLACE TABLE tenor (
    tenor    VARCHAR PRIMARY KEY,
    maturity DOUBLE NOT NULL
);

CREATE OR REPLACE TABLE curve_long (
    date     DATE   NOT NULL,
    tenor    VARCHAR NOT NULL,
    maturity DOUBLE NOT NULL,
    yield    DOUBLE NOT NULL,
    PRIMARY KEY (date, tenor)
);
"""


@dataclass
class Warehouse:
    """A DuckDB connection with the curve loaded. Close it or use `with`."""

    connection: duckdb.DuckDBPyConnection

    def __enter__(self) -> Warehouse:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def sql(self, query: str, **parameters: object) -> pd.DataFrame:
        """Run a query and get a DataFrame. Parameters are passed, never formatted in."""
        if parameters:
            return self.connection.execute(query, parameters).df()
        return self.connection.execute(query).df()

    @property
    def rows(self) -> int:
        return int(self.sql("SELECT count(*) AS n FROM curve_long")["n"].iloc[0])

    def wide(self) -> pd.DataFrame:
        frame = self.sql("SELECT * FROM curve_wide ORDER BY date")
        return frame.set_index("date")

    def spread(self, short: str, long: str) -> pd.DataFrame:
        """A two-leg spread in basis points, computed in SQL."""
        return self.sql(
            """
            SELECT s.date,
                   (l.yield - s.yield) * 100 AS spread_bp
            FROM curve_long s
            JOIN curve_long l USING (date)
            WHERE s.tenor = $short AND l.tenor = $long
            ORDER BY s.date
            """,
            short=short,
            long=long,
        )

    def features(self, lags: tuple[int, ...] = (1, 5, 21, 63)) -> pd.DataFrame:
        """Per-tenor predictive features, built with window functions.

        Everything here is strictly backward-looking. The window frames are
        written `ROWS BETWEEN n PRECEDING AND 1 PRECEDING` rather than
        `CURRENT ROW` on purpose: a rolling mean that includes today is a
        feature that knows today's answer, and it is the single easiest way
        to build a model that looks brilliant and predicts nothing.
        """
        lag_columns = ",\n".join(
            f"       yield - LAG(yield, {n}) OVER w AS change_{n}d" for n in lags
        )
        # The daily change is computed in a CTE rather than inline: DuckDB
        # refuses a window function inside another window function, and the
        # rolling volatility needs the change it is the volatility of.
        return self.sql(
            f"""
            WITH stepped AS (
                SELECT date,
                       tenor,
                       maturity,
                       yield,
            {lag_columns},
                       AVG(yield) OVER (
                           PARTITION BY tenor ORDER BY date
                           ROWS BETWEEN 21 PRECEDING AND 1 PRECEDING
                       ) AS mean_21d
                FROM curve_long
                WINDOW w AS (PARTITION BY tenor ORDER BY date)
            )
            SELECT *,
                   STDDEV_SAMP(change_1d) OVER (
                       PARTITION BY tenor ORDER BY date
                       ROWS BETWEEN 21 PRECEDING AND 1 PRECEDING
                   ) AS vol_21d
            FROM stepped
            ORDER BY date, maturity
            """
        )

    def summary(self) -> pd.DataFrame:
        """One row per tenor: coverage and dispersion. For the API's landing call."""
        return self.sql(
            """
            SELECT tenor,
                   maturity,
                   count(*)          AS observations,
                   min(date)         AS first_date,
                   max(date)         AS last_date,
                   round(min(yield), 2) AS min_yield,
                   round(max(yield), 2) AS max_yield,
                   round(avg(yield), 3) AS mean_yield
            FROM curve_long
            GROUP BY tenor, maturity
            ORDER BY maturity
            """
        )


def open_warehouse(curve: Curve, path: str | Path | None = None) -> Warehouse:
    """Load a curve into DuckDB. `path` None means in-memory."""
    connection = duckdb.connect(str(path) if path is not None else ":memory:")
    wide = curve.frame.reset_index()
    wide["date"] = pd.to_datetime(wide["date"]).dt.date
    connection.register("curve_input", wide)
    connection.execute(SCHEMA)

    maturities = pd.DataFrame(
        {"tenor": curve.tenors, "maturity": [TENORS[t] for t in curve.tenors]}
    )
    connection.register("tenor_input", maturities)
    connection.execute("INSERT INTO tenor SELECT * FROM tenor_input")

    # UNPIVOT is the readable way to go wide -> long, and it keeps the tenor
    # names as data rather than as column positions.
    columns = ", ".join(f'"{t}"' for t in curve.tenors)
    connection.execute(
        f"""
        INSERT INTO curve_long
        SELECT u.date, u.tenor, t.maturity, u.yield
        FROM (
            UNPIVOT curve_wide
            ON {columns}
            INTO NAME tenor VALUE yield
        ) AS u
        JOIN tenor t USING (tenor)
        """
    )
    connection.unregister("curve_input")
    connection.unregister("tenor_input")
    return Warehouse(connection=connection)
