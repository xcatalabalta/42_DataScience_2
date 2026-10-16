# VM setup for Module 2: showing matplotlib charts

Changes made to the Alpine Linux 3.21 VM (VirtualBox) so that the charts of the
*Data Viz* module open in a window, both in the VM's XFCE session and on the host
through SSH.

---

## 1. The problem

Running a chart script showed this warning, and no window opened:

```
UserWarning: FigureCanvasAgg is not interactive, and thus cannot be shown
```

**Cause:** matplotlib draws windows through a *GUI backend* (TkAgg, QtAgg, GTK...).
When none of them can load, it silently falls back to **Agg**, which only writes
image files. `plt.show()` then has nothing to show, so it prints that warning.
`savefig()` keeps working, so the PNG files were still created.

On Alpine, a working Tk backend needs **two** packages:

| Package | Provides |
|---|---|
| `python3-tkinter` | Python's Tk library (`import tkinter`) |
| `py3-matplotlib-tk` | matplotlib's Tk backend (`matplotlib/backends/backend_tkagg.py`) |

`py3-matplotlib` alone does not include `backend_tkagg.py`: Alpine ships it in a
separate subpackage. With only `python3-tkinter` installed, matplotlib still
fell back to Agg.

---

## 2. Diagnosis (for reference)

How the cause was found, step by step:

```sh
# 1. Which Python, matplotlib, display and backend settings are in use
python3 -c "
import os, sys, matplotlib as m
print('python    :', sys.executable)
print('matplotlib:', m.__version__, m.__file__)
print('DISPLAY   :', os.environ.get('DISPLAY'))
print('MPLBACKEND:', os.environ.get('MPLBACKEND'))
print('rc file   :', m.matplotlib_fname(), '->', m.rcParams['backend'])
import tkinter; print('tkinter   :', tkinter.TkVersion)
"

# 2. Is a backend forced by the system config file? (no output = not forced)
grep -n '^ *backend' /usr/share/matplotlib/mpl-data/matplotlibrc

# 3. Is the display correct? (expected: [:0.0] in the XFCE terminal)
echo "[$DISPLAY]"

# 4. Force Tk: shows the real error instead of the silent fallback to Agg
MPLBACKEND=TkAgg python3 -c "import matplotlib.pyplot as plt; plt.plot([1, 2]); plt.show()"
```

Step 4 printed the real cause:

```
ModuleNotFoundError: No module named 'matplotlib.backends.backend_tkagg'
```

> Note: over SSH without forwarding, `DISPLAY` is empty and `agg` is the correct
> choice there. Always test the backend from a session that has a display.

---

## 3. Fix: GUI backend for matplotlib

In the VM:

```sh
sudo apk add python3-tkinter py3-matplotlib-tk
```

Check it, in the XFCE terminal:

```sh
python3 -c "import matplotlib; print(matplotlib.get_backend())"   # TkAgg
```

No matplotlib configuration file is needed: with the backend installed,
matplotlib selects TkAgg automatically whenever a display is available.

---

## 4. X11 forwarding: chart windows on the host

This lets a script run in an SSH session from the host open its window on the
host's screen.

### In the VM (once)

```sh
sudo apk add xauth                                         # X authentication for SSH
sudo sed -i 's/^#\?X11Forwarding.*/X11Forwarding yes/' /etc/ssh/sshd_config
grep '^X11Forwarding' /etc/ssh/sshd_config                 # X11Forwarding yes
sudo rc-service sshd restart                               # open sessions survive
```

### From the host (every time)

Connect with `-X` **instead of** the usual `ssh` command. If a plain session is
already open, `exit` and reconnect:

```sh
ssh -X fcatala-@localhost -p 4241       # 4241 = VirtualBox NAT port forward to the VM's SSH
```

Inside the session:

```sh
echo $DISPLAY            # e.g. localhost:10.0  (empty = forwarding not active)
./ex00/pie.py --no-feb   # the window opens on the host
```

If `DISPLAY` is empty, check that:
- `xauth` is installed in the VM;
- sshd was restarted after the change;
- the host has an X server (a Linux host has one; macOS needs XQuartz, Windows
  needs VcXsrv or WSLg).

---

## 5. Optional: viewing a PNG without a window

| Method | Command |
|---|---|
| In the terminal (any SSH session) | `sudo apk add chafa`, then `chafa ex00/pie_no_feb.png` |
| Image viewer in XFCE | `ristretto ex00/pie_no_feb.png` |
| Copy to the host (run on the host) | `scp -P 4241 fcatala-@localhost:<repo>/ex00/pie_no_feb.png .` |

`chafa` draws with coloured blocks in any terminal, and shows the real image in
terminals that support sixel or the kitty graphics protocol.

---

## 6. How the chart scripts behave

| Session | `DISPLAY` | Backend | Result |
|---|---|---|---|
| XFCE terminal in the VM | `:0.0` | TkAgg | Window in the VM + PNG saved |
| `ssh -X` from the host | `localhost:10.0` | TkAgg | Window on the host + PNG saved |
| Plain `ssh` from the host | empty | Agg (set by the script) | PNG saved only |
| `--no-show` option | any | any | PNG saved only |

The scripts switch to Agg themselves when there is no display, so they never fail
for lack of a screen.

---

## 7. Summary of changes to the VM

| Change | Command | Purpose |
|---|---|---|
| Package | `apk add python3-tkinter` | Tk library for Python |
| Package | `apk add py3-matplotlib-tk` | matplotlib's TkAgg backend |
| Package | `apk add xauth` | X11 forwarding over SSH |
| Config | `X11Forwarding yes` in `/etc/ssh/sshd_config` | Allow X11 forwarding |
| Service | `rc-service sshd restart` | Apply the sshd change |
| Optional | `apk add chafa` | View images in the terminal |

To undo the X11 forwarding: set `X11Forwarding no` and restart sshd.
