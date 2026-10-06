"""Synthetic payments data generator (seeded, so every run is reproducible).

Creates a small fintech-style world:
  * customers  (Egypt / UAE / KSA, three segments)
  * merchants  (eight categories)
  * one CSV of transactions per day, with realistic fraud patterns and deliberately
    dirty rows (duplicates, messy text, missing/negative amounts) for the pipeline to clean.

Usage:  python -m payments.generate_data --days 92
"""
from __future__ import annotations

import argparse
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

COUNTRY_CURRENCY = {"EG": "EGP", "AE": "AED", "SA": "SAR"}
CITIES = {
    "EG": ["Cairo", "Alexandria", "Giza"],
    "AE": ["Dubai", "Abu Dhabi", "Sharjah"],
    "SA": ["Riyadh", "Jeddah", "Dammam"],
}
# category -> (share of merchants, typical basket in USD, fraud risk multiplier)
CATEGORIES = {
    "GROCERY": (0.20, 30, 0.5),
    "FUEL": (0.10, 25, 0.5),
    "RESTAURANT": (0.18, 20, 0.5),
    "PHARMACY": (0.08, 18, 0.5),
    "ELECTRONICS": (0.08, 160, 3.0),
    "TRAVEL": (0.06, 220, 2.5),
    "ONLINE_RETAIL": (0.18, 45, 2.0),
    "DIGITAL_GOODS": (0.12, 12, 4.0),
}
ONLINE_CATEGORIES = {"ONLINE_RETAIL", "DIGITAL_GOODS"}
SEGMENT_SPEND = {"RETAIL": 1.0, "PREMIUM": 2.2, "SME": 3.5}
USD_PER_UNIT = {"EGP": 0.0205, "AED": 0.2723, "SAR": 0.2667}

BASE_FRAUD_RATE = 0.010
# Relative likelihood of each hour of the day for normal spending (peaks in the evening)
HOUR_WEIGHTS = np.array(
    [1, 1, 1, 1, 1, 2, 3, 5, 6, 7, 8, 9, 10, 9, 8, 8, 9, 10, 11, 10, 8, 6, 4, 2], dtype=float
)
HOUR_PROBS = HOUR_WEIGHTS / HOUR_WEIGHTS.sum()

RAW_COLUMNS = [
    "txn_id", "customer_id", "merchant_id", "txn_ts", "amount", "currency",
    "channel", "card_present", "status", "is_fraud",
]


def make_customers(rng: np.random.Generator, n: int = 8000) -> pd.DataFrame:
    country = rng.choice(list(COUNTRY_CURRENCY), size=n, p=[0.5, 0.3, 0.2])
    segment = rng.choice(list(SEGMENT_SPEND), size=n, p=[0.75, 0.15, 0.10])
    signup = pd.Timestamp("2022-01-01") + pd.to_timedelta(rng.integers(0, 1500, size=n), unit="D")
    return pd.DataFrame(
        {
            "customer_id": [f"C{i:06d}" for i in range(1, n + 1)],
            "country": country,
            "segment": segment,
            "signup_date": signup.strftime("%Y-%m-%d"),
            "activity_weight": rng.gamma(1.2, 1.0, size=n).round(4),  # how often they spend
        }
    )


def make_merchants(rng: np.random.Generator, n: int = 400) -> pd.DataFrame:
    names = list(CATEGORIES)
    category = rng.choice(names, size=n, p=[CATEGORIES[c][0] for c in names])
    country = rng.choice(list(COUNTRY_CURRENCY), size=n, p=[0.45, 0.35, 0.20])
    city = [rng.choice(CITIES[c]) for c in country]
    return pd.DataFrame(
        {
            "merchant_id": [f"M{i:05d}" for i in range(1, n + 1)],
            "merchant_name": [f"{c.title().replace('_', ' ')} Shop {i}" for i, c in enumerate(category, 1)],
            "category": category,
            "country": country,
            "city": city,
            "popularity": rng.gamma(0.8, 1.0, size=n).round(4),  # busy merchants get more traffic
        }
    )


def make_day(
    rng: np.random.Generator, day: date, customers: pd.DataFrame, merchants: pd.DataFrame, n: int
) -> pd.DataFrame:
    """Build one clean day of transactions (dirt is added separately by `add_noise`)."""
    # --- who buys, where ---
    cust_p = customers["activity_weight"] / customers["activity_weight"].sum()
    cust = customers.iloc[rng.choice(len(customers), size=n, p=cust_p)].reset_index(drop=True)

    merch_idx = np.zeros(n, dtype=int)
    cross_border = rng.random(n) < 0.08  # 8% of purchases happen outside the home country
    for country in COUNTRY_CURRENCY:
        pool = np.flatnonzero(merchants["country"].to_numpy() == country)
        pool_p = merchants["popularity"].to_numpy()[pool]
        pool_p = pool_p / pool_p.sum()
        mask = (cust["country"].to_numpy() == country) & ~cross_border
        merch_idx[mask] = rng.choice(pool, size=mask.sum(), p=pool_p)
    all_p = merchants["popularity"] / merchants["popularity"].sum()
    merch_idx[cross_border] = rng.choice(len(merchants), size=cross_border.sum(), p=all_p)
    merch = merchants.iloc[merch_idx].reset_index(drop=True)

    is_cross = (cust["country"] != merch["country"]).to_numpy()
    category = merch["category"].to_numpy()

    # --- which transactions are fraud (more likely online, risky categories, cross-border) ---
    risk = np.array([CATEGORIES[c][2] for c in category])
    p_fraud = BASE_FRAUD_RATE * risk * np.where(is_cross, 2.5, 1.0)
    fraud = rng.random(n) < p_fraud

    # --- channel ---
    online_merchant = np.isin(category, list(ONLINE_CATEGORIES))
    ecom = online_merchant | (rng.random(n) < 0.08) | (fraud & (rng.random(n) < 0.6))
    channel = np.where(ecom, "ECOM", "POS")

    # --- amount in USD, then converted to the merchant's currency ---
    basket = np.array([CATEGORIES[c][1] for c in category]) * cust["segment"].map(SEGMENT_SPEND).to_numpy()
    amount_usd = rng.lognormal(np.log(basket), 0.7)
    bump = fraud & (rng.random(n) < 0.6)  # many fraud attempts are unusually large
    amount_usd = np.where(bump, amount_usd * rng.lognormal(np.log(3), 0.5, size=n), amount_usd)
    currency = merch["country"].map(COUNTRY_CURRENCY).to_numpy()
    amount_local = (amount_usd / pd.Series(currency).map(USD_PER_UNIT).to_numpy()).round(2)

    # --- time of day: fraud skews to the night ---
    hour = rng.choice(24, size=n, p=HOUR_PROBS)
    night_fraud = fraud & (rng.random(n) < 0.45)
    hour = np.where(night_fraud, rng.integers(0, 6, size=n), hour)
    ts = pd.Timestamp(day) + pd.to_timedelta(hour * 3600 + rng.integers(0, 3600, size=n), unit="s")

    # --- status (fraud is only ever recorded on approved payments) ---
    status = rng.choice(["APPROVED", "DECLINED", "REVERSED"], size=n, p=[0.93, 0.06, 0.01])
    status = np.where(fraud, "APPROVED", status)

    return pd.DataFrame(
        {
            "txn_id": [f"T{day:%Y%m%d}{i:06d}" for i in range(1, n + 1)],
            "customer_id": cust["customer_id"],
            "merchant_id": merch["merchant_id"],
            "txn_ts": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "amount": amount_local,
            "currency": currency,
            "channel": channel,
            "card_present": channel == "POS",
            "status": status,
            "is_fraud": fraud.astype(int),
        }
    )


def add_noise(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Make the file messy like real source systems: dupes, odd casing, missing/negative amounts."""
    df = df.copy()
    n = len(df)
    df["amount"] = df["amount"].astype(object)

    messy = rng.random(n) < 0.02
    df.loc[messy, "status"] = " " + df.loc[messy, "status"].str.lower() + " "
    lower_ccy = rng.random(n) < 0.01
    df.loc[lower_ccy, "currency"] = df.loc[lower_ccy, "currency"].str.lower()
    df.loc[rng.random(n) < 0.002, "amount"] = None             # missing amount
    neg = rng.random(n) < 0.001
    df.loc[neg, "amount"] = -df.loc[neg, "amount"].astype(float)  # sign error

    dupes = df.sample(frac=0.005, random_state=int(rng.integers(0, 1_000_000)))
    return pd.concat([df, dupes], ignore_index=True)


def weekday_factor(day: date) -> float:
    """Slightly lower volume on Fri/Sat (typical MENA weekend)."""
    return {4: 0.85, 5: 0.95}.get(day.weekday(), 1.0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=os.environ.get("RAW_PATH", "data/raw"))
    parser.add_argument("--start", default="2026-07-01")
    parser.add_argument("--days", type=int, default=92)
    parser.add_argument("--txns-per-day", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    out = Path(args.out)
    (out / "transactions").mkdir(parents=True, exist_ok=True)
    (out / "dims").mkdir(parents=True, exist_ok=True)

    dims_rng = np.random.default_rng(args.seed)
    customers = make_customers(dims_rng)
    merchants = make_merchants(dims_rng)
    customers.drop(columns="activity_weight").to_csv(out / "dims" / "customers.csv", index=False)
    merchants.drop(columns="popularity").to_csv(out / "dims" / "merchants.csv", index=False)

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    total = 0
    for offset in range(args.days):
        day = start + timedelta(days=offset)
        rng = np.random.default_rng([args.seed, offset])
        n = int(args.txns_per_day * (1 + 0.004 * offset) * weekday_factor(day))  # slow growth
        df = add_noise(make_day(rng, day, customers, merchants, n), rng)
        df[RAW_COLUMNS].to_csv(out / "transactions" / f"transactions_{day}.csv", index=False)
        total += len(df)
    print(f"Wrote {args.days} daily files ({total:,} rows) + 2 dimension files to {out}/")


if __name__ == "__main__":
    main()
