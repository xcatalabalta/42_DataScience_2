#!/usr/bin/env python3
"""
ex00 / pie.py  (module 2 - Data Viz)  --  "American apple Pie"

Pie chart of what people do on the site: the share of each event_type
(view, cart, remove_from_cart, purchase) in the data warehouse table
"customers" built in module 01.

How it works:
  - The counting is done by PostgreSQL (GROUP BY event_type), so only four
    rows travel to Python instead of ~19 million events.
  - The same query returns the first and last event_time, printed to show
    which period the chart covers.
  - Each event_type always gets the same colour (a fixed mapping, not the
    rank of the slice), so the charts with and without February compare
    directly. The palette passes the colour-blind separation checks; every
    slice carries its name and percentage, so colour is never needed alone.

Options:
  --no-feb    leave out the events from 2023-02-01 on, to compare with the
              reference chart of the subject (made without February)
  --no-show   only save the image, do not open a window

Output:
  a table of counts and percentages in the terminal, and the chart saved as
  pie.png (or pie_no_feb.png) next to this script. The window opens only
  when a display is available (e.g. in the XFCE session, not over SSH).

Run it (both work; shebang present and file is executable):
    ./pie.py [--no-feb] [--no-show]
    python3 pie.py [--no-feb] [--no-show]
"""

import os
import sys
import getpass
import argparse
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
FEB_START = "2023-02-01"            # first instant excluded by --no-feb

# Fixed colour per event type (validated categorical palette, light mode):
# the colour follows the event type, never the size of its slice.
COLORS = {
    "view": "#2a78d6",              # blue
    "cart": "#eb6834",              # orange
    "remove_from_cart": "#1baf7a",  # aqua
    "purchase": "#eda100",          # yellow
}
SPARE_COLORS = ["#e87ba4", "#008300", "#6250d6", "#e34948"]  # unexpected types
SURFACE = "#fcfcfb"                 # chart background
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"


def connect_db():
    """
    Open a connection to the database without storing any password in the
    code. It first tries WITHOUT a password: libpq then uses, if present,
    PGPASSWORD, loaded from the project's .env (written by
    `make getpass`) or exported by the shell. Only if that first attempt
    fails does it prompt for the password (no echo) and try once more.
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


def fetch_counts(conn, no_feb):
    """
    Count the events of each type in one pass over TABLE (biggest first),
    with the first and last event_time of the period covered.
    Arguments:
        conn:   open psycopg2 connection
        no_feb: if True, only events before FEB_START are counted (bool)
    Returns:
        tuple (rows, first, last): rows is a list of (event_type, count),
        first and last are datetimes (list of tuple, datetime, datetime)
    """
    where = "WHERE event_time < %s" if no_feb else ""
    params = (FEB_START,) if no_feb else ()
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT event_type, count(*), min(event_time), max(event_time) "
            f"FROM {TABLE} {where} "
            f"GROUP BY event_type ORDER BY count(*) DESC;",
            params,
        )
        result = cur.fetchall()
    if not result:
        sys.exit(f"ERROR: no events found in {TABLE}.")
    rows = [(event_type, n) for event_type, n, _, _ in result]
    first = min(r[2] for r in result)
    last = max(r[3] for r in result)
    return rows, first, last


def print_table(rows, first, last):
    """
    Print the count and percentage of each event type, and the period.
    Arguments:
        rows:  list of (event_type, count), biggest first (list of tuple)
        first: first event_time covered (datetime)
        last:  last event_time covered (datetime)
    Returns:
        None
    """
    total = sum(n for _, n in rows)
    print(f"Period: {first} -> {last}")
    print(f"{'event_type':<18}{'events':>12}{'share':>9}")
    for event_type, n in rows:
        print(f"{event_type:<18}{n:>12,}{100 * n / total:>8.1f}%")
    print(f"{'total':<18}{total:>12,}{100.0:>8.1f}%")


def colors_for(types):
    """
    Give each event type its fixed colour; types outside COLORS take the
    spare colours in order (never a generated colour).
    Arguments:
        types: event types in slice order (list of str)
    Returns:
        list of hex colours, one per type (list of str)
    """
    spare = iter(SPARE_COLORS)
    return [COLORS.get(t) or next(spare, "#9a9a96") for t in types]


def draw_pie(rows, first, last, path, show):
    """
    Draw the pie chart, save it to `path`, and show it if asked.
    Slices are separated by a 2 px gap in the background colour; each one
    is labelled with its event type and percentage.
    Arguments:
        rows:  list of (event_type, count), biggest first (list of tuple)
        first: first event_time covered (datetime)
        last:  last event_time covered (datetime)
        path:  image file to write (str)
        show:  open a window with the chart (bool)
    Returns:
        None
    """
    types = [t for t, _ in rows]
    counts = [n for _, n in rows]
    fig, ax = plt.subplots(figsize=(7, 5.2), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    _, labels, pcts = ax.pie(
        counts,
        labels=types,
        colors=colors_for(types),
        autopct="%1.1f%%",
        pctdistance=0.68,
        wedgeprops={"edgecolor": SURFACE, "linewidth": 2},
        textprops={"color": TEXT_PRIMARY, "fontsize": 11},
    )
    for label in labels:
        label.set_color(TEXT_SECONDARY)
    ax.axis("equal")
    ax.set_title("What people do on the site", color=TEXT_PRIMARY,
                 fontsize=14, pad=18)
    fig.text(0.5, 0.04,
             f"{sum(counts):,} events  ·  {first:%Y-%m-%d} to {last:%Y-%m-%d}",
             ha="center", color=TEXT_SECONDARY, fontsize=9)
    fig.savefig(path, dpi=150, facecolor=SURFACE, bbox_inches="tight")
    print(f"Chart saved to {path}")
    if show:
        plt.show()
    plt.close(fig)


def main():
    """
    Parse the options, query the event counts, print them and draw the pie.
    Arguments:
        none (reads --no-feb and --no-show from the command line)
    Returns:
        None (exits with a non-zero status on error)
    """
    parser = argparse.ArgumentParser(description="Pie chart of event types.")
    parser.add_argument("--no-feb", action="store_true",
                        help=f"only events before {FEB_START}")
    parser.add_argument("--no-show", action="store_true",
                        help="save the image without opening a window")
    args = parser.parse_args()

    conn = connect_db()
    try:
        rows, first, last = fetch_counts(conn, args.no_feb)
    except psycopg2.Error as e:
        sys.exit(f"ERROR: query failed.\n{e}")
    finally:
        conn.close()

    print_table(rows, first, last)
    name = "pie_no_feb.png" if args.no_feb else "pie.png"
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    show = bool(os.environ.get("DISPLAY")) and not args.no_show
    draw_pie(rows, first, last, path, show)


if __name__ == "__main__":
    main()
