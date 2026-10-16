#!/usr/bin/env python3
"""
ex01 / chart.py  (module 2 - Data Viz)  --  "initial data exploration"

Three charts of the purchases (event_type = 'purchase') in the data
warehouse table "customers" built in module 01, from the beginning of
October 2022 to the end of February 2023:

  1. Number of customers per day       (line)   chart_customers.png
  2. Total sales per month, million ₳  (bars)   chart_sales.png
  3. Average spend per customer, ₳/day (area)   chart_spend.png

Definitions (one row of the daily query per calendar day):
  - customers of a day : distinct user_id with at least one purchase
  - sales of a day     : sum of the prices of the purchases (refunds,
                         i.e. negative prices, included as they are)
  - average spend      : sales of the day / customers of the day
  - sales of a month   : sum of the sales of its days

How it works:
  - PostgreSQL does the aggregation (GROUP BY day), so ~150 rows travel
    to Python instead of every purchase event.
  - The monthly totals are added up in Python from the same daily rows,
    so the three charts always come from one consistent query.
  - All prices are in Altairian Dollars (₳).

Options:
  --no-feb    leave out February 2023, to compare with the reference
              charts of the subject (made without February)
  --no-show   only save the images, do not open the windows

Output:
  a monthly summary in the terminal, and the three charts saved next to
  this script (with the suffix _no_feb when --no-feb is used). The windows
  open only when a display and an interactive backend are available.

Run it (both work; shebang present and file is executable):
    ./chart.py [--no-feb] [--no-show]
    python3 chart.py [--no-feb] [--no-show]
"""

import os
import sys
import getpass
import argparse
from datetime import date, timedelta

import psycopg2

import matplotlib
if not os.environ.get("DISPLAY"):
    matplotlib.use("Agg")           # no display (SSH, cron): file only
import matplotlib.pyplot as plt     # noqa: E402  (backend must be set first)
import matplotlib.dates as mdates   # noqa: E402


def load_env():
    """
    Load the project settings into os.environ, from two files at the
    repository root (one level above this script):
      1. .env            created by `make getpass`, includes the password
      2. env_sample.txt  committed defaults (everything except the password)
    A variable already set to a non-empty value is never overridden, so
    the priority is: shell / make environment > .env > env_sample.txt.
    An EMPTY variable counts as unset: make exports the empty PGPASSWORD
    of env_sample.txt when .env does not exist yet, and that must not hide
    the password that `make getpass` has just written to .env.
    Arguments:
        none
    Returns:
        list of the files that were loaded (list of str)
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    loaded = []
    for name in (".env", "env_sample.txt"):
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key, value = key.strip(), value.strip()
                if value and not os.environ.get(key):   # empty = unset
                    os.environ[key] = value
        loaded.append(path)
    return loaded


def setting(name):
    """
    Read one project setting from the environment (filled by load_env()).
    Arguments:
        name: variable name, e.g. "PGDATABASE" (str)
    Returns:
        its value (str); exits with a clear message if it is missing
    """
    value = os.environ.get(name)
    if not value:
        sys.exit(f"ERROR: setting {name} not found "
                 "(check env_sample.txt / .env).")
    return value


load_env()

# Settings: .env (with password) or env_sample.txt -- see load_env()
DB_NAME = setting("PGDATABASE")
DB_USER = setting("PGUSER")
DB_HOST = setting("PGHOST")
DB_PORT = int(setting("PGPORT"))

TABLE = "customers"
START = date(2022, 10, 1)           # first day of the period
FEB_START = date(2023, 2, 1)        # end of the period with --no-feb
END = date(2023, 3, 1)              # end of the period (excluded)

# One series per chart, so one colour: the first slot of the validated
# categorical palette (light mode). Text never wears the series colour.
SERIES = "#2a78d6"
SURFACE = "#fcfcfb"                 # chart background
GRID = "#e4e3df"                    # recessive grid lines
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
CURRENCY = "₳"                 # ₳  Altairian Dollar (DejaVu has it)


def connect_db():
    """
    Open a connection to the database without storing any password in the
    code. It first tries WITHOUT a password: libpq then uses, if present,
    PGPASSWORD, loaded from the project's .env (written by
    `make getpass`) or exported by the shell. Only if that first
    attempt fails does it prompt for the password (no echo) and try
    once more.
    Arguments:
        none (reads DB_NAME, DB_USER, DB_HOST and DB_PORT)
    Returns:
        an open psycopg2 connection
    Exits:
        with an error message if the second attempt also fails
    """
    params = dict(dbname=DB_NAME, user=DB_USER, host=DB_HOST, port=DB_PORT)
    try:
        return psycopg2.connect(**params)
    except psycopg2.OperationalError:
        pass                            # no stored password, or a wrong one
    password = getpass.getpass(f"Password for PostgreSQL user '{DB_USER}': ")
    try:
        return psycopg2.connect(password=password, **params)
    except psycopg2.OperationalError as e:
        sys.exit(f"ERROR: could not connect to the database.\n{e}")


def fetch_daily(conn, end):
    """
    Aggregate the purchases per calendar day, in one pass over TABLE.
    Arguments:
        conn: open psycopg2 connection
        end:  first day NOT included (date)
    Returns:
        list of (day, customers, purchases, sales), one per day with
        purchases, in date order (list of tuple: date, int, int, float)
    """
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT event_time::date AS day, "
            f"       count(DISTINCT user_id), count(*), sum(price) "
            f"FROM {TABLE} "
            f"WHERE event_type = 'purchase' "
            f"  AND event_time >= %s AND event_time < %s "
            f"GROUP BY day ORDER BY day;",
            (START, end),
        )
        rows = cur.fetchall()
    if not rows:
        sys.exit(f"ERROR: no purchases found in {TABLE} "
                 f"between {START} and {end}.")
    return [(d, c, n, float(s or 0)) for d, c, n, s in rows]


def monthly(daily):
    """
    Add up the daily rows per month.
    Arguments:
        daily: rows from fetch_daily() (list of tuple)
    Returns:
        list of (first day of month, days, purchases, sales,
        customer-days) in month order (list of tuple)
    """
    months = {}
    for day, customers, purchases, sales in daily:
        key = day.replace(day=1)
        days, n, s, c = months.get(key, (0, 0, 0.0, 0))
        months[key] = (days + 1, n + purchases, s + sales, c + customers)
    return [(m, *v) for m, v in sorted(months.items())]


def print_summary(daily, months):
    """
    Print one line per month and the totals, to check the charts.
    Arguments:
        daily:  rows from fetch_daily() (list of tuple)
        months: rows from monthly() (list of tuple)
    Returns:
        None
    """
    print(f"Period: {daily[0][0]} -> {daily[-1][0]} ({len(daily)} days "
          f"with purchases)")
    print(f"{'month':<9}{'days':>5}{'purchases':>12}{'sales ' + CURRENCY:>15}"
          f"{'customers/day':>15}{'spend/customer':>16}")
    for m, days, n, s, c in months:
        print(f"{m:%Y-%m}  {days:>5}{n:>12,}{s:>15,.2f}"
              f"{c / days:>15,.0f}{s / c:>16.2f}")
    days = sum(r[1] for r in months)
    n = sum(r[2] for r in months)
    s = sum(r[3] for r in months)
    c = sum(r[4] for r in months)
    print(f"{'total':<9}{days:>5}{n:>12,}{s:>15,.2f}"
          f"{c / days:>15,.0f}{s / c:>16.2f}")
    print(f"mean price of a purchase: {s / n:.6f} {CURRENCY}")


def new_chart(title, ylabel):
    """
    Create a figure with the common style: light surface, recessive grid
    behind the data, no box, text in the text colours.
    Arguments:
        title:  chart title (str)
        ylabel: y axis label (str)
    Returns:
        tuple (fig, ax)
    """
    fig, ax = plt.subplots(figsize=(8, 4.6), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    ax.set_title(title, color=TEXT_PRIMARY, fontsize=13, loc="left", pad=12)
    ax.set_ylabel(ylabel, color=TEXT_SECONDARY, fontsize=10)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=TEXT_SECONDARY, labelsize=9, length=0)
    return fig, ax


def month_axis(ax, end):
    """
    Label the x axis of a daily chart with the month names, at the first
    day of each month, and fit it exactly to the period.
    Arguments:
        ax:  matplotlib axes
        end: first day NOT included (date)
    Returns:
        None
    """
    ax.set_xlim(START, end - timedelta(days=1))
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.grid(axis="x", color=GRID, linewidth=0.8)


def footer(fig, daily):
    """
    Write the period covered under the chart.
    Arguments:
        fig:   matplotlib figure
        daily: rows from fetch_daily() (list of tuple)
    Returns:
        None
    """
    fig.text(0.01, 0.01, f"Purchases only  ·  {daily[0][0]:%Y-%m-%d} to "
             f"{daily[-1][0]:%Y-%m-%d}", color=TEXT_SECONDARY, fontsize=8)


def draw_customers(daily, end):
    """
    Line chart of the number of customers per day.
    Arguments:
        daily: rows from fetch_daily() (list of tuple)
        end:   first day NOT included (date)
    Returns:
        the figure (matplotlib Figure)
    """
    fig, ax = new_chart("Customers who bought, per day",
                        "Number of customers")
    ax.plot([r[0] for r in daily], [r[1] for r in daily],
            color=SERIES, linewidth=2)
    ax.set_ylim(bottom=0)
    month_axis(ax, end)
    footer(fig, daily)
    return fig


def draw_sales(months):
    """
    Bar chart of the total sales per month, in million ₳, each bar
    labelled with its value.
    Arguments:
        months: rows from monthly() (list of tuple)
    Returns:
        the figure (matplotlib Figure)
    """
    fig, ax = new_chart("Total sales per month",
                        f"total sales in million of {CURRENCY}")
    names = [f"{m:%b}" for m, *_ in months]
    values = [s / 1e6 for _, _, _, s, _ in months]
    bars = ax.bar(names, values, width=0.7, color=SERIES,
                  edgecolor=SURFACE, linewidth=2)
    ax.bar_label(bars, labels=[f"{v:.2f}" for v in values], padding=4,
                 color=TEXT_PRIMARY, fontsize=9)
    ax.set_xlabel("month", color=TEXT_SECONDARY, fontsize=10)
    ax.set_ylim(0, max(values) * 1.12)
    fig.text(0.01, 0.01, "Purchases only, refunds included",
             color=TEXT_SECONDARY, fontsize=8)
    return fig


def draw_spend(daily, end):
    """
    Area chart of the average spend per customer, per day.
    Arguments:
        daily: rows from fetch_daily() (list of tuple)
        end:   first day NOT included (date)
    Returns:
        the figure (matplotlib Figure)
    """
    fig, ax = new_chart("Average spend per customer, per day",
                        f"average spend/customers in {CURRENCY}")
    days = [r[0] for r in daily]
    spend = [r[3] / r[1] for r in daily]
    ax.fill_between(days, spend, color=SERIES, alpha=0.25, linewidth=0)
    ax.plot(days, spend, color=SERIES, linewidth=2)
    ax.set_ylim(bottom=0)
    month_axis(ax, end)
    footer(fig, daily)
    return fig


def can_show():
    """
    Tell whether chart windows can be opened: a display must exist AND
    matplotlib must have an interactive backend (e.g. TkAgg). Without one,
    matplotlib falls back to the file-only "Agg" backend.
    Arguments:
        none
    Returns:
        True if plt.show() can open a window, False otherwise (bool)
    """
    if not os.environ.get("DISPLAY"):
        return False
    if matplotlib.get_backend().lower() == "agg":
        print("NOTE: no interactive matplotlib backend, so the charts are "
              "only saved.\n      To open windows, install Tk and its "
              "matplotlib backend:\n      sudo apk add python3-tkinter "
              "py3-matplotlib-tk")
        return False
    return True


def main():
    """
    Parse the options, query the daily purchases, print the monthly
    summary, then draw, save and show the three charts.
    Arguments:
        none (reads --no-feb and --no-show from the command line)
    Returns:
        None (exits with a non-zero status on error)
    """
    parser = argparse.ArgumentParser(description="Charts of the purchases.")
    parser.add_argument("--no-feb", action="store_true",
                        help=f"only purchases before {FEB_START}")
    parser.add_argument("--no-show", action="store_true",
                        help="save the images without opening windows")
    args = parser.parse_args()
    end = FEB_START if args.no_feb else END

    conn = connect_db()
    try:
        daily = fetch_daily(conn, end)
    except psycopg2.Error as e:
        sys.exit(f"ERROR: query failed.\n{e}")
    finally:
        conn.close()

    months = monthly(daily)
    print_summary(daily, months)

    here = os.path.dirname(os.path.abspath(__file__))
    suffix = "_no_feb" if args.no_feb else ""
    charts = (("customers", draw_customers(daily, end)),
              ("sales", draw_sales(months)),
              ("spend", draw_spend(daily, end)))
    for name, fig in charts:
        path = os.path.join(here, f"chart_{name}{suffix}.png")
        fig.savefig(path, dpi=150, facecolor=SURFACE, bbox_inches="tight")
        print(f"Chart saved to {path}")
    if not args.no_show and can_show():
        plt.show()                      # the three windows at once
    plt.close("all")


if __name__ == "__main__":
    main()
