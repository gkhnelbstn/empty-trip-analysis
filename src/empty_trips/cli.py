"""``empty-trips generate`` writes the synthetic fleet; ``empty-trips report`` prints the result.

Connection settings come from the standard libpq variables (PGHOST, PGUSER, ...).
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta

import psycopg

from empty_trips.generate import generate
from empty_trips.load import write

REPORT_SQL = "select * from marts.mart_savings_scenario"


def _generate(args: argparse.Namespace) -> int:
    start = datetime.combine(args.start, datetime.min.time())
    t0 = time.monotonic()
    data = generate(trucks=args.trucks, days=args.days, start=start, seed=args.seed)
    t1 = time.monotonic()
    with psycopg.connect() as conn:
        counts = write(
            conn, data, seed=args.seed, start=start, end=start + timedelta(days=args.days)
        )
    t2 = time.monotonic()
    print(
        ", ".join(f"{k}={v:,}" for k, v in counts.items())
        + f" (simulate {t1 - t0:.1f}s, load {t2 - t1:.1f}s)"
    )
    return 0


def _eur(x: float) -> str:
    return f"EUR {x:,.0f}"


def _report(_: argparse.Namespace) -> int:
    with psycopg.connect() as conn, conn.cursor() as cur:
        cur.execute(REPORT_SQL)
        cols = [c.name for c in cur.description]
        row = dict(zip(cols, cur.fetchone(), strict=True))
    lines = [
        f"Fleet: {row['trucks']} trucks, {row['period_days']} days observed",
        f"Empty trips:          {row['empty_trips']:,}"
        f"  ({row['empty_trips_per_year']:,.0f} a year)",
        f"Empty km:             {row['empty_km']:,.0f} of {row['total_km']:,.0f} km"
        f"  ({row['empty_km_share']:.1%})",
        f"Cost per empty km:    EUR {row['cost_per_empty_km']:.3f}",
        f"Annual cost of empty running:  {_eur(row['annual_empty_cost'])}",
        f"Scenario: cut empty km by {row['reduction_share']:.0%}",
        f"  gross saving        {_eur(row['gross_saving'])}",
        f"  - detour km         {_eur(row['detour_cost'])}",
        f"  - programme cost    {_eur(row['programme_cost'])}",
        f"  = net saving        {_eur(row['net_saving'])} a year",
    ]
    print("\n".join(lines))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="empty-trips", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="simulate the fleet and load it into PostgreSQL")
    g.add_argument("--trucks", type=int, default=120)
    g.add_argument("--days", type=int, default=365)
    g.add_argument("--start", type=date.fromisoformat, default=date(2025, 1, 1))
    g.add_argument("--seed", type=int, default=7)
    g.set_defaults(func=_generate)

    r = sub.add_parser("report", help="print the savings scenario (after dbt build)")
    r.set_defaults(func=_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
