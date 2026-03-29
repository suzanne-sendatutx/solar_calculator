#!/usr/bin/env python3
"""Plot grid export vs battery size to visualise diminishing returns."""

import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from solar_calculator import parse_nem12, get_sorted_dates, calc_with_battery, parse_args

BATTERY_SIZES = [s / 2 for s in range(0, 101)]  # 0.0 to 50.0 in 0.5 kWh steps
GROWTH_PCTS = [0, 20, 40, 60, 80, 100]


def sweep(data, dates, cfg, growth_pcts):
    """Run battery sweep for each growth percentage.

    Returns dict: {pct: {'imports': [...], 'exports': [...], 'costs': [...], 'grid_import_days': [...]}}
    """
    results = {}
    for pct in growth_pcts:
        growth_factor = 1.0 + pct / 100.0
        imports, exports, costs, grid_import_days = [], [], [], []
        for size in BATTERY_SIZES:
            import_kwh, export_kwh, cost, grid_import_day_count = calc_with_battery(
                data, dates, cfg,
                growth_factor=growth_factor,
                battery_size_override=size,
            )
            imports.append(import_kwh)
            exports.append(export_kwh)
            costs.append(cost)
            grid_import_days.append(grid_import_day_count)
        results[pct] = {
            "imports": imports,
            "exports": exports,
            "costs": costs,
            "grid_import_days": grid_import_days,
        }
    return results


def main():
    cfg = parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(script_dir, cfg.nem12_file)

    data = parse_nem12(filepath)
    dates = get_sorted_dates(data)

    # ── Sweep all battery sizes × growth percentages ─────────────────────
    results = sweep(data, dates, cfg, GROWTH_PCTS)

    # ── Plot 1: Grid Export ───────────────────────────────────────────────
    fig1, ax1 = plt.subplots(figsize=(10, 6))
    for pct in GROWTH_PCTS:
        ax1.plot(BATTERY_SIZES, results[pct]["exports"],
                 linewidth=2, label=f"+{pct}% usage")
    ax1.set_xlabel("Battery Size (kWh)")
    ax1.set_ylabel("Annual Grid Export (kWh)")
    ax1.set_title("Grid Export vs Battery Size by Usage Growth")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    out1 = os.path.join(script_dir, "export_vs_battery.png")
    fig1.savefig(out1, dpi=150, bbox_inches="tight")
    print(f"Saved plot to {out1}")

    # ── Plot 2: Grid Import ───────────────────────────────────────────────
    fig2, ax2 = plt.subplots(figsize=(10, 6))
    for pct in GROWTH_PCTS:
        ax2.plot(BATTERY_SIZES, results[pct]["imports"],
                 linewidth=2, label=f"+{pct}% usage")
    ax2.set_xlabel("Battery Size (kWh)")
    ax2.set_ylabel("Annual Grid Import (kWh)")
    ax2.set_title("Grid Import vs Battery Size by Usage Growth")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    out2 = os.path.join(script_dir, "import_vs_battery.png")
    fig2.savefig(out2, dpi=150, bbox_inches="tight")
    print(f"Saved plot to {out2}")

    # ── Plot 3: Annual Energy Cost ────────────────────────────────────────
    fig3, ax3 = plt.subplots(figsize=(10, 6))
    for pct in GROWTH_PCTS:
        ax3.plot(BATTERY_SIZES, results[pct]["costs"],
                 linewidth=2, label=f"+{pct}% usage")
    ax3.set_xlabel("Battery Size (kWh)")
    ax3.set_ylabel("Annual Energy Cost ($)")
    ax3.set_title("Annual Energy Cost vs Battery Size by Usage Growth")
    ax3.legend()
    ax3.grid(True, alpha=0.3)

    out3 = os.path.join(script_dir, "cost_vs_battery.png")
    fig3.savefig(out3, dpi=150, bbox_inches="tight")
    print(f"Saved plot to {out3}")

    # ── Plot 4: Days With Any Grid Import ────────────────────────────────
    fig4, ax4 = plt.subplots(figsize=(10, 6))
    for pct in GROWTH_PCTS:
        ax4.plot(BATTERY_SIZES, results[pct]["grid_import_days"],
                 linewidth=2, label=f"+{pct}% usage")
    ax4.set_xlabel("Battery Size (kWh)")
    ax4.set_ylabel("Days per Year With Any Grid Import")
    ax4.set_title("Grid Import Days vs Battery Size")
    ax4.legend()
    ax4.grid(True, alpha=0.3)

    out4 = os.path.join(script_dir, "grid_import_days_vs_battery.png")
    fig4.savefig(out4, dpi=150, bbox_inches="tight")
    print(f"Saved plot to {out4}")


if __name__ == "__main__":
    main()
