#!/usr/bin/env python3
"""
ex02 / mustache.py  (module 2 - Data Viz)  --  "My beautiful mustache"

Statistics and box plots ("mustache" = whiskers) of the purchases
(event_type = 'purchase') in the data warehouse table "customers", from
the beginning of October 2022 to the end of February 2023.

Terminal output, in the format of pandas' describe() like the subject:
  count, mean, std, min, 25% (first quartile), 50% (median = second
  quartile), 75% (third quartile) and max of the price of the items
  purchased; then the same statistics for the average basket per user.

Charts (saved next to this script):
  1. mustache_price.png     box plot of every purchase price, outliers
                            drawn (refunds, i.e. negative prices, included)
  2. mustache_box.png       the same box plot without the outliers, to
                            see the box and the whiskers
  3. mustache_basket.png    box plot of the average basket per user: for
                            each day, the sales divided by the customers
                            who bought that day (the measure of ex01's
                            third chart, whose reference values ~27-42 ₳
                            match the subject's third box plot)

Box plot rules (same as matplotlib's and seaborn's defaults):
  box = first to third quartile, line inside = median, whiskers = the
  furthest data points within 1.5 x IQR of the box, outliers = beyond.
  Quartiles use linear interpolation, like pandas.

Options:
  --no-feb    leave out February 2023, to compare with the reference
              output of the subject (made without February)
  --no-show   only save the images, do not open the windows

Run it (both work; shebang present and file is executable):
    ./mustache.py [--no-feb] [--no-show]
    python3 mustache.py [--no-feb] [--no-show]
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

# Colours of the subject's reference box plots (seaborn "darkgrid"
# style), sampled from the images of the subject PDF.
SURFACE = "#ffffff"                 # figure background, around the plot
PLOT_BG = "#eaeaf2"                 # plot area: seaborn darkgrid grey
GRID = "#ffffff"                    # white grid lines over the grey
EDGE = "#5d5d5d"                    # box outline, whiskers, median, outliers
BOX_ALL = "#5975a4"                 # 1st plot: seaborn "deep" blue, muted
BOX_PRICE = "#7dba7f"               # 2nd plot: green
BOX_BASKET = "#78aac8"              # 3rd plot: blue
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


def fetch_prices(conn, end):
    """
    Read the price of every purchase of the period. The prices travel as
    float8 (not NUMERIC), so psycopg2 builds floats instead of Decimals.
    Arguments:
        conn: open psycopg2 connection
        end:  first day NOT included (date)
    Returns:
        the prices (numpy array of float)
    """
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT price::float8 FROM {TABLE} "
            f"WHERE event_type = 'purchase' AND price IS NOT NULL "
            f"  AND event_time >= %s AND event_time < %s;",
            (START, end),
        )
        prices = np.fromiter((p for p, in cur), dtype=float)
    if prices.size == 0:
        sys.exit(f"ERROR: no purchases found in {TABLE} "
                 f"between {START} and {end}.")
    return prices


def fetch_baskets(conn, end):
    """
    Average basket per user, one value per day: the sales of the day
    divided by the distinct customers who bought that day.
    Arguments:
        conn: open psycopg2 connection
        end:  first day NOT included (date)
    Returns:
        the daily averages (numpy array of float)
    """
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT (sum(price) / count(DISTINCT user_id))::float8 "
            f"FROM {TABLE} "
            f"WHERE event_type = 'purchase' "
            f"  AND event_time >= %s AND event_time < %s "
            f"GROUP BY event_time::date;",
            (START, end),
        )
        return np.fromiter((v for v, in cur), dtype=float)


def describe(values):
    """
    Print the statistics of `values` in the format of pandas' describe():
    quartiles by linear interpolation, standard deviation of a sample.
    Arguments:
        values: the data (numpy array of float)
    Returns:
        None
    """
    q1, q2, q3 = np.percentile(values, [25, 50, 75])
    rows = (("count", values.size), ("mean", values.mean()),
            ("std", values.std(ddof=1)), ("min", values.min()),
            ("25%", q1), ("50%", q2), ("75%", q3), ("max", values.max()))
    for name, value in rows:
        print(f"{name:<6}{value:>14.6f}")


def new_chart(title, xlabel):
    """
    Create a figure in the style of the subject's charts (seaborn
    "darkgrid"): grey plot area, white vertical grid lines behind the
    data, no box.
    Arguments:
        title:  chart title (str)
        xlabel: x axis label (str)
    Returns:
        tuple (fig, ax)
    """
    fig, ax = plt.subplots(figsize=(8, 3.6), facecolor=SURFACE)
    ax.set_facecolor(PLOT_BG)
    ax.set_title(title, color=TEXT_PRIMARY, fontsize=13, loc="left", pad=12)
    ax.set_xlabel(xlabel, color=TEXT_PRIMARY, fontsize=10)
    ax.grid(axis="x", color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors=TEXT_PRIMARY, labelsize=9, length=0)
    return fig, ax


def draw_box(ax, values, color, fliers):
    """
    Draw one horizontal box plot in the seaborn look: coloured box, grey
    outline, whiskers and median, grey diamonds for the outliers.
    Arguments:
        ax:     matplotlib axes
        values: the data (numpy array of float)
        color:  fill colour of the box (str)
        fliers: draw the outliers (bool)
    Returns:
        None
    """
    line = {"color": EDGE, "linewidth": 1.25}
    # matplotlib 3.10 replaced vert=False by orientation="horizontal"
    major, minor = (int(x) for x in matplotlib.__version__.split(".")[:2])
    horizontal = ({"orientation": "horizontal"} if (major, minor) >= (3, 10)
                  else {"vert": False})
    ax.boxplot(values, widths=0.8, patch_artist=True, showfliers=fliers,
               boxprops={"facecolor": color, "edgecolor": EDGE,
                         "linewidth": 1.25},
               medianprops=line, whiskerprops=line, capprops=line,
               flierprops={"marker": "d", "markersize": 5,
                           "markerfacecolor": EDGE,
                           "markeredgecolor": EDGE},
               **horizontal)
    ax.set_yticks([])                   # boxplot() sets a "1" tick label


def footer(fig, text):
    """
    Write a short note under the chart.
    Arguments:
        fig:  matplotlib figure
        text: the note (str)
    Returns:
        None
    """
    fig.text(0.01, -0.04, text, color=TEXT_SECONDARY, fontsize=8)


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
    Parse the options, read the purchases, print the statistics, then
    draw, save and show the three box plots.
    Arguments:
        none (reads --no-feb and --no-show from the command line)
    Returns:
        None (exits with a non-zero status on error)
    """
    parser = argparse.ArgumentParser(description="Box plots of the prices.")
    parser.add_argument("--no-feb", action="store_true",
                        help=f"only purchases before {FEB_START}")
    parser.add_argument("--no-show", action="store_true",
                        help="save the images without opening windows")
    args = parser.parse_args()
    end = FEB_START if args.no_feb else END

    conn = connect_db()
    try:
        prices = fetch_prices(conn, end)
        baskets = fetch_baskets(conn, end)
    except psycopg2.Error as e:
        sys.exit(f"ERROR: query failed.\n{e}")
    finally:
        conn.close()

    period = f"{START:%Y-%m-%d} to {end:%Y-%m-%d} (excluded)"
    print(f"Period: {period}")
    print(f"\nPrice of the items purchased ({CURRENCY}):")
    describe(prices)
    print(f"\nAverage basket per user, per day ({CURRENCY}):")
    describe(baskets)
    print()

    fig1, ax = new_chart("Price of the items purchased", "price")
    draw_box(ax, prices, BOX_ALL, fliers=True)
    footer(fig1, f"{prices.size:,} purchases  ·  {period}")

    fig2, ax = new_chart("Price of the items purchased, without outliers",
                         "price")
    draw_box(ax, prices, BOX_PRICE, fliers=False)
    footer(fig2, "Box: first to third quartile  ·  line: median  ·  "
           "whiskers: 1.5 x IQR")

    fig3, ax = new_chart("Average basket per user",
                         f"average spend/customer per day in {CURRENCY}")
    draw_box(ax, baskets, BOX_BASKET, fliers=True)
    footer(fig3, f"{baskets.size} days  ·  {period}")

    here = os.path.dirname(os.path.abspath(__file__))
    suffix = "_no_feb" if args.no_feb else ""
    for name, fig in (("price", fig1), ("box", fig2), ("basket", fig3)):
        path = os.path.join(here, f"mustache_{name}{suffix}.png")
        fig.savefig(path, dpi=150, facecolor=SURFACE, bbox_inches="tight")
        print(f"Chart saved to {path}")
    if not args.no_show and can_show():
        plt.show()                      # the three windows at once
    plt.close("all")


if __name__ == "__main__":
    main()
