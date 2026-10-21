"""Figures. Every chart should answer one question and be readable without the caption."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def calibration_plot(table, path: str, title: str = "Calibration: price vs realized frequency") -> None:
    fig, ax = plt.subplots(figsize=(5.5, 5.5))
    ax.plot([0, 1], [0, 1], "--", color="gray", label="Perfect calibration")
    ax.errorbar(table["mean_price"], table["freq"], yerr=1.96 * table["se"], fmt="o-", capsize=3,
                label="Observed (95% CI, naive)")
    for _, r in table.iterrows():
        ax.annotate(f"n={int(r['n'])}", (r["mean_price"], r["freq"]), fontsize=6,
                    textcoords="offset points", xytext=(4, -9))
    ax.set_xlabel("Market price (implied probability)")
    ax.set_ylabel("Fraction that resolved YES")
    ax.set_title(title)
    ax.legend(loc="upper left")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
