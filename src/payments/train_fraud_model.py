"""Train a fraud model on the dbt feature mart and write scores back to the warehouse.

Design choices worth knowing:
  * TIME-BASED split (train on the first 70% of the timeline, test on the rest).
    A random split would leak future behaviour into training and flatter the results.
  * Fraud is rare (~2%), so accuracy is useless. We report PR-AUC and what a fraud team
    actually cares about: "if analysts can review only the top 1% of transactions, how much
    fraud (by count and by value) do we catch?"
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from payments.envfile import load_env_file
from payments.warehouse import read_sql, write_table

NUMERIC = [
    "amount_usd", "amount_vs_avg_ratio", "cust_prior_txn_count", "txns_today_so_far",
    "minutes_since_prev_txn", "txn_hour", "is_night", "is_cross_border", "card_present_flag",
]
CATEGORICAL = ["channel", "category"]
TARGET = "is_fraud"


def review_budget_metrics(y: np.ndarray, score: np.ndarray, amount: np.ndarray, frac: float) -> dict:
    """Metrics if analysts review only the top `frac` of transactions by risk score."""
    k = max(1, int(len(y) * frac))
    top = np.argsort(-score)[:k]
    caught = y[top] == 1
    return {
        "reviewed_share": frac,
        "precision": float(caught.mean()),
        "fraud_count_recall": float(caught.sum() / y.sum()),
        "fraud_value_recall": float(amount[top][caught].sum() / amount[y == 1].sum()),
    }


def main() -> None:
    load_env_file()
    df = read_sql("select * from marts.mart_fraud_features order by txn_ts")
    # Newer DuckDB/pandas return nullable ints; sklearn wants plain floats (NaN = missing)
    df[NUMERIC] = df[NUMERIC].astype("float64")

    cutoff = df["txn_ts"].quantile(0.7)
    train, test = df[df["txn_ts"] <= cutoff], df[df["txn_ts"] > cutoff]
    print(f"train: {len(train):,} rows up to {cutoff:%Y-%m-%d} | test: {len(test):,} rows after")

    model = Pipeline([
        ("prep", ColumnTransformer(
            [("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL)],
            remainder="passthrough",          # numeric columns pass through unchanged
        )),
        ("clf", HistGradientBoostingClassifier(
            class_weight="balanced", max_iter=200, learning_rate=0.1, random_state=42)),
    ])
    features = NUMERIC + CATEGORICAL
    model.fit(train[features], train[TARGET])

    y_test = test[TARGET].to_numpy()
    score_test = model.predict_proba(test[features])[:, 1]
    amount_test = test["amount_usd"].to_numpy()

    metrics = {
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "test_fraud_rate": float(y_test.mean()),
        "roc_auc": float(roc_auc_score(y_test, score_test)),
        "pr_auc": float(average_precision_score(y_test, score_test)),
        "pr_auc_baseline": float(y_test.mean()),   # what a random model would score
        "review_budget": [
            review_budget_metrics(y_test, score_test, amount_test, f) for f in (0.01, 0.02, 0.05)
        ],
    }

    # Which features matter? (permutation importance on a sample of the test set)
    sample = test.sample(n=min(20_000, len(test)), random_state=42)
    imp = permutation_importance(
        model, sample[features], sample[TARGET],
        scoring="average_precision", n_repeats=3, random_state=42,
    )
    importance = (
        pd.DataFrame({"feature": features, "importance": imp.importances_mean})
        .sort_values("importance", ascending=False)
    )

    precision, recall, _ = precision_recall_curve(y_test, score_test)
    step = max(1, len(precision) // 300)
    pr_curve = pd.DataFrame({"precision": precision[::step], "recall": recall[::step]})

    # Write artifacts
    Path("reports").mkdir(exist_ok=True)
    Path("models").mkdir(exist_ok=True)
    Path("reports/metrics.json").write_text(json.dumps(metrics, indent=2))
    importance.to_csv("reports/feature_importance.csv", index=False)
    pr_curve.to_csv("reports/pr_curve.csv", index=False)
    joblib.dump(model, "models/fraud_model.joblib")

    # Score every approved transaction and write the result back next to the marts,
    # so BI tools can join `fraud_scores` to `fct_transactions` on txn_id.
    scores = pd.DataFrame({
        "txn_id": df["txn_id"],
        "fraud_score": model.predict_proba(df[features])[:, 1].round(5),
        "split": np.where(df["txn_ts"] <= cutoff, "train", "test"),
        "scored_at": datetime.now(timezone.utc).replace(tzinfo=None),
    })
    write_table(scores, "marts", "fraud_scores")

    top1 = metrics["review_budget"][0]
    print(f"ROC-AUC {metrics['roc_auc']:.3f} | PR-AUC {metrics['pr_auc']:.3f} "
          f"(random = {metrics['pr_auc_baseline']:.3f})")
    print(f"Reviewing the top 1% catches {top1['fraud_count_recall']:.0%} of fraud cases "
          f"and {top1['fraud_value_recall']:.0%} of fraud value")


if __name__ == "__main__":
    main()
