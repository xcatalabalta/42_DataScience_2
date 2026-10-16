#!/usr/bin/env python3
"""
ex04 / elbow.py  (module 2 - Data Viz)  --  "Elbow"

Elbow Method to choose the number of customer groups (clusters) for the
e-mail targeting of exercise 05.

Customers are described by their RFM profile, computed by PostgreSQL
from the purchases (event_type = 'purchase') of the period, one row per
user_id:
  - recency   : days from the customer's last purchase to the end of
                the period (small = bought recently)
  - frequency : number of purchases
  - monetary  : Altairian Dollars spent (sum of the prices, refunds
                included)

Method:
  1. Standardise each feature (z-score: minus its mean, divided by its
     standard deviation), so that ₳, days and counts weigh the same.
  2. For k = 1 .. 10, run k-means and keep its WCSS (within-cluster sum
     of squares, also called inertia): the sum of the squared distances
     from each customer to the centre of its cluster. With k = 1 it is
     the total variance, n_customers x 3 features.
  3. Plot WCSS against k. WCSS always falls when k grows; the "elbow" is
     the k after which adding a cluster no longer gains much. It is
     located here as the point of the curve furthest from the straight
     line joining its first and last points, and printed with the gain
     of every step so the choice can be explained.

k-means is written with numpy (k-means++ start, Lloyd iterations, best
of N_INIT runs, fixed seed), so the result is reproducible and no other
library is needed.

Options:
  --no-feb    leave out February 2023, to compare with the reference
              chart of the subject (made without February)
  --no-show   only save the image, do not open the window

Output:
  the WCSS table and the elbow in the terminal, and the chart saved as
  elbow.png (or elbow_no_feb.png) next to this script.

Run it (both work; shebang present and file is executable):
    ./elbow.py [--no-feb] [--no-show]
    python3 elbow.py [--no-feb] [--no-show]
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

K_MAX = 10                          # k = 1 .. K_MAX, as in the reference
N_INIT = 3                          # k-means runs per k, best one kept
MAX_ITER = 100                      # Lloyd iterations per run
SEED = 42                           # fixed: same result at every run

# Colours of the subject's reference chart (seaborn "darkgrid" style),
# sampled from the image of the subject PDF.
SURFACE = "#ffffff"                 # figure background, around the plot
PLOT_BG = "#eaeaf2"                 # plot area: seaborn darkgrid grey
GRID = "#ffffff"                    # white grid lines
LINE = "#4c72b0"                    # seaborn "deep" blue
TEXT_PRIMARY = "#262626"            # seaborn text colour
TEXT_SECONDARY = "#555555"          # notes


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


def fetch_rfm(conn, end):
    """
    RFM profile of every customer who bought in the period, in one pass
    over TABLE (one row per user_id).
    Arguments:
        conn: open psycopg2 connection
        end:  first day NOT included, also the reference date of the
              recency (date)
    Returns:
        array of shape (customers, 3): recency in days, frequency,
        monetary in ₳ (numpy array of float)
    """
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT extract(epoch FROM %s::timestamp - max(event_time))"
            f"         / 86400.0, "
            f"       count(*), "
            f"       coalesce(sum(price), 0) "
            f"FROM {TABLE} "
            f"WHERE event_type = 'purchase' "
            f"  AND event_time >= %s AND event_time < %s "
            f"GROUP BY user_id;",
            (end, START, end),
        )
        rows = cur.fetchall()
    if not rows:
        sys.exit(f"ERROR: no purchases found in {TABLE} "
                 f"between {START} and {end}.")
    return np.array(rows, dtype=float)


def standardise(features):
    """
    Z-score every column: (value - mean) / standard deviation. A column
    with no spread is only centred (division by 1).
    Arguments:
        features: array of shape (n, d) (numpy array of float)
    Returns:
        the standardised array, same shape (numpy array of float)
    """
    std = features.std(axis=0)
    std[std == 0] = 1.0
    return (features - features.mean(axis=0)) / std


def sq_distances(points, centres):
    """
    Squared Euclidean distance from every point to every centre.
    Arguments:
        points:  array of shape (n, d) (numpy array of float)
        centres: array of shape (k, d) (numpy array of float)
    Returns:
        array of shape (n, k) (numpy array of float)
    """
    return ((points[:, None, :] - centres[None, :, :]) ** 2).sum(axis=2)


def kmeans_pp(points, k, rng):
    """
    k-means++ start: the first centre is a random point; each next one is
    drawn with a probability proportional to its squared distance to the
    nearest centre already chosen, so the centres start well spread.
    Arguments:
        points: array of shape (n, d) (numpy array of float)
        k:      number of centres (int)
        rng:    numpy random generator
    Returns:
        array of shape (k, d) (numpy array of float)
    """
    centres = [points[rng.integers(len(points))]]
    nearest = sq_distances(points, np.array(centres))[:, 0]
    for _ in range(1, k):
        total = nearest.sum()
        if total == 0:                  # fewer distinct points than k
            idx = rng.integers(len(points))
        else:
            idx = rng.choice(len(points), p=nearest / total)
        centres.append(points[idx])
        nearest = np.minimum(nearest,
                             sq_distances(points, points[idx][None])[:, 0])
    return np.array(centres)


def kmeans(points, k, rng):
    """
    k-means (Lloyd's algorithm): assign each point to its nearest centre,
    move each centre to the mean of its points, repeat until the centres
    stop moving. Run N_INIT times from k-means++ starts; keep the lowest
    WCSS.
    Arguments:
        points: array of shape (n, d) (numpy array of float)
        k:      number of clusters (int)
        rng:    numpy random generator
    Returns:
        tuple (wcss, labels, centres): float, array (n,), array (k, d)
    """
    best = None
    for _ in range(N_INIT):
        centres = kmeans_pp(points, k, rng)
        for _ in range(MAX_ITER):
            dist = sq_distances(points, centres)
            labels = dist.argmin(axis=1)
            moved = centres.copy()
            for c in range(k):
                members = points[labels == c]
                if len(members):
                    moved[c] = members.mean(axis=0)
                else:                   # empty cluster: furthest point
                    moved[c] = points[dist.min(axis=1).argmax()]
            if np.allclose(moved, centres, rtol=0, atol=1e-7):
                break
            centres = moved
        dist = sq_distances(points, centres)
        labels = dist.argmin(axis=1)
        wcss = float(dist[np.arange(len(points)), labels].sum())
        if best is None or wcss < best[0]:
            best = (wcss, labels, centres)
    return best


def find_elbow(ks, wcss):
    """
    Locate the elbow: the point of the curve furthest from the straight
    line joining its first and last points, with both axes scaled to
    0..1 so that k and WCSS weigh the same.
    Arguments:
        ks:   values of k (list of int)
        wcss: WCSS for each k (list of float)
    Returns:
        the k of the elbow (int)
    """
    x = (np.array(ks) - ks[0]) / (ks[-1] - ks[0])
    y = np.array(wcss)
    y = (y - y.min()) / (y.max() - y.min() or 1.0)
    # distance to the line from (0, 1) to (1, 0), i.e. x + y - 1 = 0
    distance = np.abs(x + y - 1) / np.sqrt(2)
    return ks[int(distance.argmax())]


def print_table(ks, wcss, elbow):
    """
    Print WCSS for each k with the gain of each extra cluster, and the
    elbow found.
    Arguments:
        ks:    values of k (list of int)
        wcss:  WCSS for each k (list of float)
        elbow: the k of the elbow (int)
    Returns:
        None
    """
    print(f"{'k':>3}{'WCSS':>16}{'gain vs k-1':>16}{'gain %':>9}")
    for i, (k, w) in enumerate(zip(ks, wcss)):
        if i == 0:
            print(f"{k:>3}{w:>16,.0f}{'':>16}{'':>9}")
            continue
        gain = wcss[i - 1] - w
        mark = "   <- elbow" if k == elbow else ""
        print(f"{k:>3}{w:>16,.0f}{gain:>16,.0f}"
              f"{100 * gain / wcss[i - 1]:>8.1f}%{mark}")
    print(f"\nElbow: k = {elbow}. Up to k = {elbow} each extra cluster "
          f"removes a large part\nof the remaining WCSS; after it the "
          f"gains become small and steady,\nso more groups would split "
          f"customers without describing them much better.")


def draw(ks, wcss, elbow):
    """
    Draw the Elbow Method chart in the subject's style, with the elbow
    marked.
    Arguments:
        ks:    values of k (list of int)
        wcss:  WCSS for each k (list of float)
        elbow: the k of the elbow (int)
    Returns:
        the figure (matplotlib Figure)
    """
    fig, ax = plt.subplots(figsize=(6.4, 4.8), facecolor=SURFACE)
    ax.set_facecolor(PLOT_BG)
    ax.plot(ks, wcss, color=LINE, linewidth=1.5)
    i = ks.index(elbow)
    ax.plot(elbow, wcss[i], "o", color=LINE, markersize=8,
            markeredgecolor=SURFACE, markeredgewidth=2)
    ax.annotate(f"elbow: k = {elbow}", (elbow, wcss[i]),
                xytext=(14, 10), textcoords="offset points",
                color=TEXT_PRIMARY, fontsize=10)
    ax.set_title("The Elbow Method", color=TEXT_PRIMARY, fontsize=12)
    ax.set_xlabel("Number of clusters", color=TEXT_PRIMARY, fontsize=11)
    ax.set_ylabel("WCSS", color=TEXT_PRIMARY, fontsize=11)
    ax.grid(color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors=TEXT_PRIMARY, labelsize=10, length=0)
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
    Parse the options, build the RFM features, run k-means for k = 1 ..
    K_MAX, print the WCSS table and the elbow, then draw, save and show
    the chart.
    Arguments:
        none (reads --no-feb and --no-show from the command line)
    Returns:
        None (exits with a non-zero status on error)
    """
    parser = argparse.ArgumentParser(description="Elbow Method (k-means).")
    parser.add_argument("--no-feb", action="store_true",
                        help=f"only purchases before {FEB_START}")
    parser.add_argument("--no-show", action="store_true",
                        help="save the image without opening a window")
    args = parser.parse_args()
    end = FEB_START if args.no_feb else END

    conn = connect_db()
    try:
        rfm = fetch_rfm(conn, end)
    except psycopg2.Error as e:
        sys.exit(f"ERROR: query failed.\n{e}")
    finally:
        conn.close()

    print(f"Period: {START:%Y-%m-%d} to {end:%Y-%m-%d} (excluded)")
    print(f"Customers: {len(rfm):,}  (features: recency, frequency, "
          f"monetary, standardised)")
    for name, col in zip(("recency (days)", "frequency", "monetary (₳)"),
                         rfm.T):
        print(f"  {name:<15} mean {col.mean():>10,.2f}   "
              f"median {np.median(col):>10,.2f}   max {col.max():>12,.2f}")
    print()

    points = standardise(rfm)
    rng = np.random.default_rng(SEED)
    ks = list(range(1, K_MAX + 1))
    wcss = []
    for k in ks:
        wcss.append(kmeans(points, k, rng)[0])
        print(f"\rk-means: k = {k}/{K_MAX}", end="", flush=True)
    print("\r" + " " * 24 + "\r", end="")

    elbow = find_elbow(ks, wcss)
    print_table(ks, wcss, elbow)
    print()

    fig = draw(ks, wcss, elbow)
    name = "elbow_no_feb.png" if args.no_feb else "elbow.png"
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    fig.savefig(path, dpi=150, facecolor=SURFACE, bbox_inches="tight")
    print(f"Chart saved to {path}")
    if not args.no_show and can_show():
        plt.show()
    plt.close("all")


if __name__ == "__main__":
    main()
