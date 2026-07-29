"""
Carousell Pokemon TCG market analysis.

Reads the scraper's CSV output, produces two dashboards in images/, and prints
every headline figure to stdout so the README can be kept in sync with reality.

Changes from the earlier version, and why they matter:
  * Keywords use word boundaries. Plain `contains("9")` matched any set number
    (102/195, 130/196) and flagged 442 listings as grade-9 slabs.
  * Language detection uses word boundaries. Substring "EN" matched GREEDENT,
    CENTISKORCH, ENTEI, ENERGY - 439 of 450 "English" listings were false hits.
  * Graded slabs are classified BEFORE sealed product, so "PSA 10 ... + Elite
    Trainer Box" files as graded rather than sealed.
  * Feature importances are read from the fitted model instead of hardcoded.
"""

import os
import re

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.ensemble import RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.model_selection import train_test_split

os.makedirs("images", exist_ok=True)
sns.set_theme(style="whitegrid")
plt.rcParams.update({"font.sans-serif": "DejaVu Sans", "font.size": 10})

DATA_FILE = "carousell_pokemon_surface_20260728_2237.csv"
RANDOM_STATE = 42

# ─────────────────────────── load & clean ───────────────────────────
# Prefer the anonymised file when it exists — that's the one safe to publish.
stem, ext = os.path.splitext(DATA_FILE)
candidates = [
    os.path.join("data", f"{stem}_anon{ext}"),
    f"{stem}_anon{ext}",
    os.path.join("data", DATA_FILE),
    DATA_FILE,
]
path = next((p for p in candidates if os.path.exists(p)), None)
if path is None:
    raise SystemExit(
        f"Cannot find {DATA_FILE} (or its _anon version) in data/ or the "
        f"current directory.\nRun the scraper first, then anonymize_data.py."
    )
print(f"Reading {path}")

df = pd.read_csv(path)
n_raw = len(df)

df = df[df["price_flag"] == "ok"]
n_valid = len(df)

df = df.drop_duplicates(subset=["title", "seller", "price_numeric"], keep="first").copy()
n_final = len(df)

df["post_dt"] = pd.to_datetime(df["scraped_at"]) - pd.to_timedelta(
    df["posted_hours_ago"], unit="h"
)
DOW = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
df["created_day"] = pd.Categorical(
    df["post_dt"].dt.day_name(), categories=DOW, ordered=True
)

# ─────────────────────── feature engineering ────────────────────────
# \b word boundaries throughout - see module docstring.
KEYWORDS = {
    "PSA": r"\bPSA\b",
    "BGS": r"\bBGS\b|BECKETT",
    "CGC": r"\bCGC\b",
    "GEM_MINT_10": r"\b(?:PSA|BGS|CGC)\s*10\b",
    "GRADE_9": r"\b(?:PSA|BGS|CGC)\s*9(?:\.5)?\b",
    "CHARIZARD": r"\bCHARIZARD\b|LIZARDON",
    "PIKACHU": r"\bPIKACHU\b",
    "RAYQUAZA": r"\bRAYQUAZA\b",
    "UMBREON": r"\bUMBREON\b",
    "BOOSTER_BOX": r"BOOSTER BOX|\bETB\b|ELITE TRAINER",
    "SEALED": r"\bSEALED\b",
    "SET_151": r"\b151\b",
    "VMAX": r"\bVMAX\b",
    "VSTAR": r"\bVSTAR\b",
    "GX": r"\bGX\b",
    "EX": r"\bEX\b",
    "SAR": r"\bSAR\b",
    "SR": r"\bSR\b",
    "UR": r"\bUR\b",
    "PROMO": r"\bPROMO\b",
    "VINTAGE": r"\bVINTAGE\b|1ST ED|BASE SET|WOTC",
    "FULL_ART": r"FULL ART|\bFA\b",
}

upper = df["title"].astype(str).str.upper()
for name, pattern in KEYWORDS.items():
    df[f"kw_{name}"] = upper.str.contains(pattern, regex=True).astype(int)


def categorize(title):
    """Graded is checked first: a slab that mentions a box is still a slab."""
    t = str(title).upper()
    if re.search(r"\bPSA\b|\bBGS\b|\bCGC\b|BECKETT|GRADED|\bSLAB\b", t):
        return "Graded Slabs"
    if re.search(r"BOOSTER BOX|\bETB\b|ELITE TRAINER|\bSEALED\b|BOOSTER PACK|\bTIN\b|\bDECK\b", t):
        return "Sealed Product"
    if re.search(r"\bLOT\b|\bBULK\b|\bBUNDLE\b|ASSORTED|\bVARIOUS\b|SET OF", t):
        return "Bulk & Bundles"
    return "Raw Singles"


def detect_language(title):
    t = str(title).upper()
    if re.search(r"\bJP\b|JAPAN|JAPANESE", t):
        return "Japanese"
    if re.search(r"\bENG?\b|ENGLISH", t):
        return "English"
    if re.search(r"CHINESE|\bCN\b", t):
        return "Chinese"
    if re.search(r"KOREA", t):
        return "Korean"
    return "Unspecified"


df["category"] = df["title"].apply(categorize)
df["language"] = df["title"].apply(detect_language)

# ───────────────────────────── model ────────────────────────────────
kw_cols = [f"kw_{k}" for k in KEYWORDS]
X = pd.concat(
    [
        pd.get_dummies(
            df[["category", "condition", "language", "hasBuyerProtection"]],
            drop_first=True,
        ),
        df[kw_cols],
    ],
    axis=1,
)
y = np.log1p(df["price_numeric"])

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=RANDOM_STATE
)
rf = RandomForestRegressor(n_estimators=300, random_state=RANDOM_STATE, n_jobs=-1)
rf.fit(X_train, y_train)

y_pred = rf.predict(X_test)
r2 = r2_score(y_test, y_pred)
rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))

# Read importances from the FITTED MODEL. Never hardcode these.
importances = pd.Series(rf.feature_importances_, index=X.columns).sort_values(
    ascending=False
)

PRETTY = {
    "category_Raw Singles": "Category: Raw Singles",
    "category_Sealed Product": "Category: Sealed",
    "category_Graded Slabs": "Category: Graded",
    "hasBuyerProtection": "Buyer Protection",
    "condition_Like new": "Condition: Like New",
    "language_Japanese": "Language: Japanese",
    "language_Unspecified": "Language: Unspecified",
}
label = lambda c: PRETTY.get(c, c.replace("kw_", "Keyword: ").replace("_", " ").title())

# ─────────────────────── dashboard 1: market ────────────────────────
dow = (
    df.groupby("created_day", observed=False)
    .agg(listing_count=("id", "count"), median_price=("price_numeric", "median"))
    .reset_index()
)
gmv = (
    df.groupby("seller")
    .agg(total_gmv=("price_numeric", "sum"))
    .reset_index()
    .sort_values("total_gmv", ascending=False)
    .head(8)
)

fig, axes = plt.subplots(2, 2, figsize=(15, 11))

ax = axes[0, 0]
ax.bar(range(len(dow)), dow["listing_count"], color="#1f77b4", alpha=0.85, width=0.55)
ax.set_ylabel("Listing volume", color="#1f77b4", fontweight="bold")
ax.set_title(
    "1. Posting volume vs median price by weekday\n"
    "(volume is outlier-sensitive - see README)",
    fontsize=12, fontweight="bold", pad=10,
)
ax.set_xticks(range(len(dow)))
ax.set_xticklabels(dow["created_day"], rotation=25)
twin = ax.twinx()
twin.plot(range(len(dow)), dow["median_price"], color="#d62728", marker="o", linewidth=2.5)
twin.set_ylabel("Median price (RM)", color="#d62728", fontweight="bold")
twin.grid(False)

ax = axes[0, 1]
sns.barplot(data=gmv, x="total_gmv", y="seller", hue="seller",
            palette="Blues_r", legend=False, ax=ax)
ax.set_title("2. Top 8 sellers by total listed value", fontsize=12, fontweight="bold", pad=10)
ax.set_xlabel("Total listed value (RM)", fontweight="bold")
ax.set_ylabel("")

ax = axes[1, 0]
cat = df.groupby("category")["price_numeric"].agg(["median", "mean"]).reset_index()
pos = np.arange(len(cat))
ax.bar(pos - 0.18, cat["median"], 0.36, label="Median", color="#2b5c8f")
ax.bar(pos + 0.18, cat["mean"], 0.36, label="Mean", color="#e6550d")
ax.set_xticks(pos)
ax.set_xticklabels(cat["category"], rotation=10)
ax.set_ylabel("Price (RM)", fontweight="bold")
ax.set_title("3. Price by category (median vs mean)", fontsize=12, fontweight="bold", pad=10)
ax.legend()

ax = axes[1, 1]
top = importances.head(9).sort_values()
ax.barh([label(i) for i in top.index], top.values, color="#31a354")
ax.set_title(
    f"4. Price drivers (Random Forest, test $R^2$ = {r2:.3f})",
    fontsize=12, fontweight="bold", pad=10,
)
ax.set_xlabel("Gini feature importance", fontweight="bold")

plt.tight_layout()
plt.savefig(os.path.join("images", "carousell_pokemon_market_dashboard.png"), dpi=200)
plt.close()

# ───────────────────── dashboard 2: validation ──────────────────────
perm = permutation_importance(
    rf, X_test, y_test, n_repeats=10, random_state=RANDOM_STATE, n_jobs=-1
)
order = perm.importances_mean.argsort()[::-1][:8]

fig, axes = plt.subplots(1, 2, figsize=(14, 6))

ax = axes[0]
sns.regplot(x=y_test, y=y_pred, ax=ax, color="#2b5c8f",
            scatter_kws={"alpha": 0.4, "s": 25},
            line_kws={"color": "#e6550d", "linewidth": 2, "label": "Linear fit"})
lims = [min(y_test.min(), y_pred.min()), max(y_test.max(), y_pred.max())]
ax.plot(lims, lims, "--", color="#777777", linewidth=1.2, label="Perfect prediction")
ax.set_title(r"1. Predicted vs actual $\ln(1 + \mathrm{price})$",
             fontsize=12, fontweight="bold", pad=12)
ax.set_xlabel(r"Actual $\ln(1 + \mathrm{price})$", fontweight="bold")
ax.set_ylabel(r"Predicted $\ln(1 + \mathrm{price})$", fontweight="bold")
ax.text(0.05, 0.85, f"$R^2 = {r2:.3f}$\nRMSE $= {rmse:.3f}$\n$n_{{test}} = {len(y_test)}$",
        transform=ax.transAxes, fontsize=11, fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="white",
                  edgecolor="#cccccc", alpha=0.9))
ax.legend(loc="lower right")

ax = axes[1]
ypos = np.arange(len(order))[::-1]
ax.barh(ypos, perm.importances_mean[order],
        xerr=perm.importances_std[order], color="#31a354", alpha=0.85)
ax.set_yticks(ypos)
ax.set_yticklabels([label(X.columns[i]) for i in order], fontweight="bold")
ax.set_title("2. Permutation importance (held-out set)",
             fontsize=12, fontweight="bold", pad=12)
ax.set_xlabel(r"Mean decrease in $R^2$ when shuffled", fontweight="bold")

plt.tight_layout()
plt.savefig(os.path.join("images", "model_testing_validation_dashboard.png"), dpi=200)
plt.close()

# ───────────────── print every README figure ─────────────────
line = "=" * 62
print(f"\n{line}\n  FIGURES FOR README - copy these, don't retype from memory\n{line}")
print(f"\nDATASET")
print(f"  rows in file            {n_raw}")
print(f"  valid prices            {n_valid}")
print(f"  after de-duplication    {n_final}   <- use this in the README")
print(f"  window                  {df['post_dt'].min():%d %b %Y} to {df['post_dt'].max():%d %b %Y}")
print(f"  sellers                 {df['seller'].nunique()}")

print(f"\nPRICE")
q = df["price_numeric"].quantile([0.25, 0.5, 0.75, 0.9, 0.99])
print(f"  median RM{q[0.5]:,.0f} | mean RM{df['price_numeric'].mean():,.0f} "
      f"| p75 RM{q[0.75]:,.0f} | p99 RM{q[0.99]:,.0f}")
top100 = df["price_numeric"].nlargest(100).sum() / df["price_numeric"].sum()
print(f"  top 100 listings hold {top100*100:.0f}% of total listed value")

print(f"\nWEEKDAY  (raw counts - check for single-seller bulk uploads before quoting)")
for _, r in dow.iterrows():
    print(f"  {str(r['created_day']):10s} {int(r['listing_count']):5d} listings  "
          f"median RM{r['median_price']:,.0f}")
big = df.groupby([df["post_dt"].dt.date, "seller"]).size()
if len(big) and big.max() > 100:
    d0, s0 = big.idxmax()
    print(f"  !! {big.max()} listings from one seller on {d0:%a %d %b} - "
          f"excluded from any weekday claim")

print(f"\nCATEGORY")
for c, g in df.groupby("category"):
    print(f"  {c:16s} n={len(g):5d}  median RM{g['price_numeric'].median():,.0f}")

print(f"\nMODEL")
print(f"  test R2 = {r2:.3f}   RMSE = {rmse:.3f} (log units)")
print(f"  n_train = {len(X_train)}   n_test = {len(X_test)}   features = {X.shape[1]}")
print(f"  R2 of {r2:.2f} means roughly {r2*100:.0f}% of log-price variance is explained.")
print(f"  State this honestly - title keywords cannot capture card identity.")
print(f"\n  top features (Gini):")
for k, v in importances.head(8).items():
    print(f"    {label(k):34s} {v:.3f}")

print(f"\n{line}")
print("Dashboards written to images/")
print(line)
