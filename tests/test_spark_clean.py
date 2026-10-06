import pytest

from payments.spark_clean import clean_transactions, get_spark


@pytest.fixture(scope="session")
def spark():
    session = get_spark("tests")
    yield session
    session.stop()


COLUMNS = ["txn_id", "customer_id", "merchant_id", "txn_ts", "amount", "currency",
           "channel", "card_present", "status", "is_fraud"]


def row(txn_id, amount="10.50", status="APPROVED", ts="2026-07-01 10:00:00", currency="EGP"):
    return (txn_id, "C1", "M1", ts, amount, currency, "POS", "True", status, "0")


def test_cleaning_rules(spark):
    raw = spark.createDataFrame(
        [
            row("T1"),
            row("T1"),                          # duplicate id
            row("T2", amount="-5"),             # negative amount
            row("T3", amount=None),             # missing amount
            row("T4", ts="not a timestamp"),    # unparseable time
            row("T5", status=" approved ", currency="egp"),  # messy text
        ],
        COLUMNS,
    )
    out = {r["txn_id"]: r for r in clean_transactions(raw).collect()}

    assert sorted(out) == ["T1", "T5"]                    # only the valid, unique rows survive
    assert out["T5"]["status"] == "APPROVED"              # trimmed + upper-cased
    assert out["T5"]["currency"] == "EGP"
    assert str(out["T1"]["txn_date"]) == "2026-07-01"     # partition column derived from timestamp
    assert out["T1"]["card_present"] is True              # text -> boolean
