#!/usr/bin/env python3
"""
ex03 / Building.py  (module 2 - Data Viz)  --  "Highest Building"

Two bar charts (histograms) of the customers who bought something
(event_type = 'purchase') in the data warehouse table "customers", from
the beginning of October 2022 to the end of February 2023, side by side
in one window and saved in one image:

  left   frequency       : number of customers by number of orders
  right  monetary value  : number of customers by Altairian Dollars spent

Definitions (one row per user_id, computed by PostgreSQL):
  - frequency      : number of purchase events of the customer (orders)
  - monetary value : sum of the prices of those purchases, in ₳
                     (refunds, i.e. negative prices, included)

Range shown:
  A few customers buy hundreds of times; with them, the first bar would
  hold almost everyone. Like the subject's reference charts, only the
  customers inside FREQ_RANGE and MONEY_RANGE are drawn (the ranges read
  on the reference axes). The terminal tells how many are left out, and
  --full draws everyone. Each chart has 5 bars of equal width between
  the smallest and largest value drawn, as in the reference.

Options:
  --no-feb    leave out February 2023, to compare with the reference
              charts of the subject (made without February)
  --full      draw every customer, without the range limits
  --no-show   only save the image, do not open the window

Output:
  the bars (ranges and customers) in the terminal, and both charts in
  building.png (or building_no_feb.png) next to this script.

Run it (both work; shebang present and file is executable):
    ./Building.py [--no-feb] [--full] [--no-show]
    python3 Building.py [--no-feb] [--full] [--no-show]
"""

import os
import sys
import getpass
import argparse
from datetime import date

import numpy as np
import psycopg2

import matplotlib
if not os.environ.get("DISPLAY"):
    matplotlib.use("Agg")           # no display (SSH, cron): file only
import matplotlib.pyplot as plt     # noqa: E402  (backend must be set first)
from matplotlib.ticker import MultipleLocator   # noqa: E402


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

BINS = 5                            # bars per chart, as in the reference
FREQ_RANGE = (1, 38)                # orders shown (reference x axis)
FREQ_TICK = 10                      # one x value every 10 orders
MONEY_RANGE = (-30, 230)            # ₳ shown (reference x axis)

# Colours of the subject's reference charts (seaborn "darkgrid" style),
# sampled from the image of the subject PDF.
SURFACE = "#ffffff"                 # figure background, around the plots
PLOT_BG = "#eaeaf2"                 # plot area: seaborn darkgrid grey
GRID = "#ffffff"                    # white grid lines and bar edges
BAR = "#b0c4de"                     # bars (lightsteelblue)
TEXT_PRIMARY = "#262626"            # seaborn text colour
TEXT_SECONDARY = "#555555"          # footer notes
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


def fetch_customers(conn, end):
    """
    Frequency and monetary value of every customer who bought in the
    period, in one pass over TABLE (one row per user_id).
    Arguments:
        conn: open psycopg2 connection
        end:  first day NOT included (date)
    Returns:
        tuple (frequency, monetary): numpy arrays of the same length,
        one value per customer (int, float)
    """
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*), coalesce(sum(price), 0)::float8 "
            f"FROM {TABLE} "
            f"WHERE event_type = 'purchase' "
            f"  AND event_time >= %s AND event_time < %s "
            f"GROUP BY user_id;",
            (START, end),
        )
        rows = cur.fetchall()
    if not rows:
        sys.exit(f"ERROR: no purchases found in {TABLE} "
                 f"between {START} and {end}.")
    frequency = np.array([r[0] for r in rows], dtype=int)
    monetary = np.array([r[1] for r in rows], dtype=float)
    return frequency, monetary


def in_range(values, limits, full):
    """
    Keep the values inside `limits` (both ends included), unless `full`.
    Arguments:
        values: the data (numpy array)
        limits: (low, high) (tuple of numbers)
        full:   keep every value (bool)
    Returns:
        the values kept (numpy array)
    """
    if full:
        return values
    low, high = limits
    return values[(values >= low) & (values <= high)]


def print_bins(name, unit, values, kept, limits, full):
    """
    Print the bars of one chart (range and customers) and how many
    customers are left out of the range shown.
    Arguments:
        name:   what is measured, e.g. "frequency" (str)
        unit:   unit of the values, e.g. "orders" (str)
        values: every customer (numpy array)
        kept:   the customers drawn (numpy array)
        limits: (low, high) range shown (tuple)
        full:   no range applied (bool)
    Returns:
        None
    """
    shown = "all values" if full else f"{limits[0]} to {limits[1]} {unit}"
    print(f"\n{name} ({unit}), range shown: {shown}")
    print(f"  customers: {values.size:,}  min {values.min():,.2f}  "
          f"median {np.median(values):,.2f}  max {values.max():,.2f}")
    counts, edges = np.histogram(kept, bins=BINS)
    for n, low, high in zip(counts, edges[:-1], edges[1:]):
        print(f"  {low:>10,.2f} to {high:>10,.2f}  {n:>10,}")
    left_out = values.size - kept.size
    print(f"  left out of the range: {left_out:,} "
          f"({100 * left_out / values.size:.2f} %)")


def style(ax, xlabel):
    """
    Apply the subject's style to one chart: grey plot area, white grid
    lines behind the bars, no box.
    Arguments:
        ax:     matplotlib axes
        xlabel: x axis label (str)
    Returns:
        None
    """
    ax.set_facecolor(PLOT_BG)
    ax.set_xlabel(xlabel, color=TEXT_PRIMARY, fontsize=11)
    ax.set_ylabel("customers", color=TEXT_PRIMARY, fontsize=11)
    ax.grid(color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors=TEXT_PRIMARY, labelsize=10, length=0)


def draw(frequency, monetary, full, title_note):
    """
    Draw both histograms side by side in one figure; the frequency
    chart has one x value every FREQ_TICK orders.
    Arguments:
        frequency:  orders per customer drawn (numpy array)
        monetary:   ₳ per customer drawn (numpy array)
        full:       no range applied (bool)
        title_note: text of the footer (str)
    Returns:
        the figure (matplotlib Figure)
    """
    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 4.4),
                                      facecolor=SURFACE)
    bars = {"bins": BINS, "color": BAR, "edgecolor": GRID, "linewidth": 1}
    left.hist(frequency, **bars)
    style(left, "frequency")
    if not full:                        # 0, 10, 20, 30 as in the reference
        left.xaxis.set_major_locator(MultipleLocator(FREQ_TICK))
    left.set_title("Orders per customer", color=TEXT_PRIMARY,
                   fontsize=12, loc="left")
    right.hist(monetary, **bars)
    style(right, f"monetary value in {CURRENCY}")
    right.set_title("Altairian Dollars spent per customer",
                    color=TEXT_PRIMARY, fontsize=12, loc="left")
    fig.tight_layout()
    fig.text(0.01, -0.03, title_note, color=TEXT_SECONDARY, fontsize=8)
    return fig


def can_show():
    """
    Tell whether a chart window can be opened: a display must exist AND
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
        print("NOTE: no interactive matplotlib backend, so the chart is "
              "only saved.\n      To open a window, install Tk and its "
              "matplotlib backend:\n      sudo apk add python3-tkinter "
              "py3-matplotlib-tk")
        return False
    return True


def main():
    """
    Parse the options, compute frequency and monetary value per customer,
    print the bars, then draw, save and show both charts in one window.
    Arguments:
        none (reads --no-feb, --full and --no-show from the command line)
    Returns:
        None (exits with a non-zero status on error)
    """
    parser = argparse.ArgumentParser(
        description="Frequency and monetary value of the customers.")
    parser.add_argument("--no-feb", action="store_true",
                        help=f"only purchases before {FEB_START}")
    parser.add_argument("--full", action="store_true",
                        help="draw every customer, without range limits")
    parser.add_argument("--no-show", action="store_true",
                        help="save the image without opening a window")
    args = parser.parse_args()
    end = FEB_START if args.no_feb else END

    conn = connect_db()
    try:
        frequency, monetary = fetch_customers(conn, end)
    except psycopg2.Error as e:
        sys.exit(f"ERROR: query failed.\n{e}")
    finally:
        conn.close()

    period = f"{START:%Y-%m-%d} to {end:%Y-%m-%d} (excluded)"
    print(f"Period: {period}")
    freq_kept = in_range(frequency, FREQ_RANGE, args.full)
    money_kept = in_range(monetary, MONEY_RANGE, args.full)
    print_bins("frequency", "orders", frequency, freq_kept,
               FREQ_RANGE, args.full)
    print_bins("monetary value", CURRENCY, monetary, money_kept,
               MONEY_RANGE, args.full)
    print()

    note = (f"{frequency.size:,} customers  ·  {period}"
            + ("" if args.full else
               f"  ·  shown: {FREQ_RANGE[0]}-{FREQ_RANGE[1]} orders, "
               f"{MONEY_RANGE[0]} to {MONEY_RANGE[1]} {CURRENCY}"))
    fig = draw(freq_kept, money_kept, args.full, note)

    name = "building" + ("_no_feb" if args.no_feb else "") \
        + ("_full" if args.full else "") + ".png"
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    fig.savefig(path, dpi=150, facecolor=SURFACE, bbox_inches="tight")
    print(f"Chart saved to {path}")
    if not args.no_show and can_show():
        plt.show()
    plt.close("all")


if __name__ == "__main__":
    main()
