# Box plots: the basics and how to read them

A **box plot** (also called a *box-and-whisker plot*, hence the "mustache" of
exercise 02) summarises a whole distribution of numbers in one small drawing.
It shows where the middle of the data is, how spread out it is, whether it is
symmetric, and which values are unusual, all at once.

---

## 1. The five-number summary

A box plot is built from five statistics, plus a rule for outliers:

| Statistic | Meaning |
|---|---|
| **Minimum** (of the whiskers) | smallest value that is *not* an outlier |
| **Q1**, first quartile (25 %) | 25 % of the values are below it |
| **Q2**, median (50 %) | the middle value: half below, half above |
| **Q3**, third quartile (75 %) | 75 % of the values are below it |
| **Maximum** (of the whiskers) | largest value that is *not* an outlier |

The **interquartile range** is the width of the middle half of the data:

```
IQR = Q3 - Q1
```

---

## 2. Anatomy

```
              Q1     median    Q3
               |       |       |
  o    |-------+-------+-------+---------------|      o   o  o
  ^    ^       [  25 % | 25 %  ]               ^      ^
  |    |       <------ IQR ---->               |      |
outlier |          the box: middle 50 %      whisker  outliers
     whisker                                   end
       end
   <---------->                   <-------------->
   lower whisker                  upper whisker
```

- **The box** goes from Q1 to Q3: it holds the middle 50 % of the values.
- **The line inside the box** is the median.
- **The whiskers** extend from the box to the furthest data points that are
  still within **1.5 × IQR** of the box (Tukey's rule, the default in
  matplotlib, seaborn and pandas):

  ```
  lower fence = Q1 - 1.5 × IQR
  upper fence = Q3 + 1.5 × IQR
  ```

  A whisker stops at the last **real data point** inside its fence, not at
  the fence itself. That is why the two whiskers often have different
  lengths.
- **Outliers** (*fliers*) are the points beyond the fences, drawn one by one
  (diamonds in seaborn, circles in matplotlib).

---

## 3. How to read one

| What you see | What it means |
|---|---|
| Position of the median | the typical value |
| Width of the box (IQR) | how spread out the usual values are; a narrow box means similar values |
| Median not centred in the box | **skewed** distribution: the longer side is where the values stretch out |
| One whisker much longer than the other | skew as well, in the direction of the long whisker |
| Many outliers on one side only | a long **tail** on that side (e.g. a few very expensive products) |
| Outliers on both sides | extreme values in both directions (e.g. refunds and luxury items) |

### Skewness at a glance

```
symmetric        |-----[   |   ]-----|
right-skewed     |--[ |    ]-------------|   o o  o     (long tail of high values)
left-skewed      o  o   |------------[    | ]--|        (long tail of low values)
```

A quick numeric check: in a **right-skewed** distribution the **mean is
larger than the median**, because the few large values pull the mean up but
not the median.

### Median vs mean

The median, the quartiles and the box are **robust**: a handful of extreme
values barely moves them. The mean and the standard deviation are **not**:
one huge value can shift them a lot. A box plot therefore shows the typical
behaviour of the data even when outliers are present.

---

## 4. Worked example: exercise 02

The subject's statistics for the price of the items purchased (Oct 2022 to
Jan 2023):

```
count   741644.000000
mean         5.575068
std         10.264594
min        -79.370000
25%          1.590000
50%          3.330000
75%          6.030000
max        327.780000
```

**Fences:**

```
IQR         = 6.03 - 1.59         = 4.44
upper fence = 6.03 + 1.5 × 4.44   = 12.69
lower fence = 1.59 - 1.5 × 4.44   = -5.07
```

**What the three charts of the subject show:**

1. **With outliers:** the box is squeezed into a thin line near 0, because the
   x axis has to reach from −79 to 328. Thousands of diamonds to the right are
   the products above 12.69 ₳; the few on the left are **refunds** (negative
   prices). This chart shows the extremes, but the typical values are
   unreadable.
2. **Without outliers:** the same box, zoomed in. The upper whisker ends just
   below 12.69 (the upper fence). The lower whisker stops at about 0: no price
   lies between −5.07 and 0, so the lowest value inside the fence is a price
   of about 0.
3. **Average basket:** a much narrower, almost symmetric box around 32 ₳, with
   a few outlier days (sales peaks and quiet days).

**Interpretation of the prices:**

- Half of the purchased items cost **less than 3.33 ₳** (the median).
- The middle half cost **between 1.59 and 6.03 ₳**: mostly cheap products.
- **mean (5.58) > median (3.33)**, plus the long upper whisker and the cloud of
  high outliers, means the distribution is strongly **right-skewed**: a few
  expensive items (up to 327.78 ₳) raise the mean.
- The **standard deviation (10.26)** is larger than the whole IQR, again
  because of the tail. For this kind of data the median and the IQR describe
  the typical purchase better than the mean and the standard deviation.

---

## 5. Quartiles: how they are computed

With an even number of values, or when 25 % does not land exactly on a value,
the quartile falls *between* two values. There are several conventions;
**pandas, numpy (default) and PostgreSQL's `percentile_cont`** all use
**linear interpolation**:

```
position = p × (n - 1)          # p = 0.25, 0.50, 0.75; positions start at 0
value    = v[floor] + (v[ceil] - v[floor]) × (position - floor)
```

Example with 8 sorted values `1 2 3 4 5 6 7 8` and p = 0.25:
position = 0.25 × 7 = 1.75 → between `v[1] = 2` and `v[2] = 3` →
Q1 = 2 + 0.75 × 1 = **2.75**.

`mustache.py` uses `numpy.percentile`, so its output matches the subject's
`describe()` table to the last decimal.

---

## 6. Strengths and limits

| Strengths | Limits |
|---|---|
| Summarises millions of values in one shape | Hides the shape inside the box: two peaks (bimodal data) look like one |
| Robust to outliers | Says nothing about how many values there are (add the count) |
| Easy to compare groups side by side | Outliers by the 1.5 × IQR rule are *unusual*, not necessarily *wrong* |
| Shows skew and tails immediately | With a huge range (chart 1) the box can become unreadable: plot without outliers too |

When the internal shape matters, pair the box plot with a **histogram** or a
**violin plot** (a box plot with the density drawn around it).

---

## 7. In matplotlib

```python
ax.boxplot(values,
           orientation="horizontal",   # vert=False before matplotlib 3.10
           whis=1.5,                   # fence rule (default)
           showfliers=True,            # False hides the outliers
           patch_artist=True)          # needed to fill the box with a colour
```

| Parameter | Effect |
|---|---|
| `whis=1.5` | fence distance in IQRs; `whis=(0, 100)` makes the whiskers reach min and max |
| `showfliers` | draw or hide the outliers (it does **not** change the box or the whiskers) |
| `showmeans=True` | also marks the mean, useful to see the skew |
| `widths` | thickness of the box |
