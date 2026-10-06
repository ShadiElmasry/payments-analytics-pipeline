"""Build README charts (docs/images/) and CSV exports of the marts (exports/) for BI tools."""
from __future__ import annotations

import json
import os
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")  # no display needed (works in CI)
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

IMG = Path("docs/images")
BLUE, ORANGE, GREY = "#2f6fdb", "#e8743b", "#8a8f98"


def style(ax, title: str) -> None:
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25)


def main() -> None:
    IMG.mkdir(parents=True, exist_ok=True)
    Path("exports").mkdir(exist_ok=True)
    con = duckdb.connect(os.environ.get("DUCKDB_PATH", "data/warehouse.duckdb"), read_only=True)

    # 1) Daily GMV with a 7-day average
    kpi = con.execute("select * from marts.mart_daily_kpis order by txn_date").df()
    kpi["gmv_7d"] = kpi["gmv_usd"].rolling(7, min_periods=1).mean()
    fig, ax = plt.subplots(figsize=(9, 3.6))
    ax.bar(kpi["txn_date"], kpi["gmv_usd"] / 1e3, color=BLUE, alpha=0.35, width=0.9, label="Daily")
    ax.plot(kpi["txn_date"], kpi["gmv_7d"] / 1e3, color=BLUE, lw=2.2, label="7-day average")
    ax.set_ylabel("Approved GMV (USD thousands)")
    ax.legend(frameon=False)
    style(ax, "Daily approved GMV")
    fig.tight_layout()
    fig.savefig(IMG / "daily_gmv.png", dpi=150)
    plt.close(fig)

    # 2) Fraud rate by merchant category
    cat = con.execute("""
        select category, avg(is_fraud) * 100 as fraud_rate_pct
        from marts.fct_transactions where status = 'APPROVED'
        group by category order by fraud_rate_pct
    """).df()
    fig, ax = plt.subplots(figsize=(9, 3.8))
    ax.barh(cat["category"], cat["fraud_rate_pct"], color=ORANGE)
    ax.set_xlabel("Fraud rate on approved transactions (%)")
    style(ax, "Where fraud concentrates: digital goods and electronics")
    ax.grid(axis="x", alpha=0.25)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(IMG / "fraud_by_category.png", dpi=150)
    plt.close(fig)

    # 3) Precision-recall curve and 4) feature importance (written by the training step)
    if Path("reports/metrics.json").exists():
        metrics = json.loads(Path("reports/metrics.json").read_text())
        pr = pd.read_csv("reports/pr_curve.csv")
        fig, ax = plt.subplots(figsize=(5.5, 4.2))
        ax.plot(pr["recall"], pr["precision"], color=BLUE, lw=2.2, label="Model")
        ax.axhline(metrics["pr_auc_baseline"], color=GREY, ls="--", label="Random guessing")
        ax.set_xlabel("Recall (share of fraud caught)")
        ax.set_ylabel("Precision")
        ax.set_title(f"Precision-recall (PR-AUC {metrics['pr_auc']:.2f})",
                     loc="left", fontsize=12, fontweight="bold")
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(frameon=False)
        fig.tight_layout()
        fig.savefig(IMG / "pr_curve.png", dpi=150)
        plt.close(fig)

        imp = pd.read_csv("reports/feature_importance.csv").sort_values("importance")
        fig, ax = plt.subplots(figsize=(6.5, 4.2))
        ax.barh(imp["feature"], imp["importance"], color=BLUE)
        ax.set_xlabel("Drop in PR-AUC when the feature is shuffled")
        style(ax, "What the model relies on")
        ax.grid(axis="x", alpha=0.25)
        ax.grid(axis="y", visible=False)
        fig.tight_layout()
        fig.savefig(IMG / "feature_importance.png", dpi=150)
        plt.close(fig)

    # CSV exports so Power BI / Qlik / Excel can load the marts without a database driver
    for table in ["mart_daily_kpis", "mart_merchant_performance", "fct_transactions", "fraud_scores"]:
        try:
            con.execute(f"select * from marts.{table}").df().to_csv(f"exports/{table}.csv", index=False)
        except duckdb.CatalogException:
            pass
    con.close()
    print("charts -> docs/images/ | CSV exports -> exports/")


if __name__ == "__main__":
    main()
