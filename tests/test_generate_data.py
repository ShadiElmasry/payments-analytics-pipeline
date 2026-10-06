from datetime import date

import numpy as np

from payments.generate_data import add_noise, make_customers, make_day, make_merchants


def build_day(seed=1, n=6000):
    rng = np.random.default_rng(seed)
    customers, merchants = make_customers(rng, 500), make_merchants(rng, 60)
    return rng, make_day(rng, date(2026, 7, 1), customers, merchants, n)


def test_same_seed_gives_same_data():
    _, a = build_day(seed=7)
    _, b = build_day(seed=7)
    assert a.equals(b)


def test_fraud_rate_is_realistic_and_only_on_approved():
    _, df = build_day()
    assert 0.003 < df["is_fraud"].mean() < 0.04
    assert (df.loc[df["is_fraud"] == 1, "status"] == "APPROVED").all()


def test_fraud_is_more_common_online_than_in_store():
    _, df = build_day(n=20000)
    by_channel = df.groupby("channel")["is_fraud"].mean()
    assert by_channel["ECOM"] > by_channel["POS"]


def test_noise_adds_duplicates_and_bad_values_without_losing_columns():
    rng, df = build_day()
    noisy = add_noise(df, rng)
    assert list(noisy.columns) == list(df.columns)
    assert len(noisy) > len(df)                    # duplicates were added
    assert noisy["amount"].isna().any()            # some amounts went missing
    assert noisy["txn_id"].duplicated().any()
