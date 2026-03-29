#!/usr/bin/env python3
"""Find the largest battery size that pays back within a given number of years.

Uses a binary search over battery capacity. Battery cost is assumed to scale
linearly with size (cost = cost_per_kwh * size_kwh).

Shares NEM12 parsing and simulation logic with solar_calculator.py.
"""

import argparse
import os
import sys

from solar_calculator import (
    DEFAULT_NEM12_FILE,
    DEFAULT_ENERGY_RATE,
    DEFAULT_DAILY_SUPPLY_CHARGE,
    DEFAULT_FEED_IN_TARIFF,
    DEFAULT_ENERGY_INFLATION,
    DEFAULT_USAGE_GROWTH,
    DEFAULT_BATTERY_RESERVE_PCT,
    DEFAULT_BATTERY_EFFICIENCY,
    DEFAULT_HW_START_INTERVAL,
    DEFAULT_HW_END_INTERVAL,
    parse_nem12,
    get_sorted_dates,
    calc_no_battery,
    calc_with_battery,
)


def parse_args():
    p = argparse.ArgumentParser(
        description="Find the largest battery that pays back within N years",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--nem12-file", default=DEFAULT_NEM12_FILE,
                   help="Path to NEM12 CSV file")
    p.add_argument("--energy-rate", type=float, default=DEFAULT_ENERGY_RATE,
                   help="Energy import rate ($/kWh)")
    p.add_argument("--daily-supply-charge", type=float, default=DEFAULT_DAILY_SUPPLY_CHARGE,
                   help="Daily supply charge ($/day)")
    p.add_argument("--feed-in-tariff", type=float, default=DEFAULT_FEED_IN_TARIFF,
                   help="Feed-in tariff for exports ($/kWh)")
    p.add_argument("--energy-inflation", type=float, default=DEFAULT_ENERGY_INFLATION,
                   help="Annual energy cost inflation rate")
    p.add_argument("--usage-growth", type=float, default=DEFAULT_USAGE_GROWTH,
                   help="Usage increase factor (e.g. 0.05 = 5%% higher than current)")
    p.add_argument("--cost-per-kwh", type=float, default=889.0,
                   help="Battery cost per kWh of capacity ($)")
    p.add_argument("--battery-reserve", type=float, default=DEFAULT_BATTERY_RESERVE_PCT,
                   help="Battery reserve fraction (0-1)")
    p.add_argument("--battery-efficiency", type=float, default=DEFAULT_BATTERY_EFFICIENCY,
                   help="Battery round-trip efficiency (0-1)")
    p.add_argument("--hw-start", type=int, default=DEFAULT_HW_START_INTERVAL,
                   help="Hot water start interval (5-min index, 120=10am)")
    p.add_argument("--hw-end", type=int, default=DEFAULT_HW_END_INTERVAL,
                   help="Hot water end interval (5-min index, 168=2pm, exclusive)")
    p.add_argument("--payback-years", type=int, default=10,
                   help="Target payback period (years)")
    p.add_argument("--max-search-kwh", type=float, default=100.0,
                   help="Upper bound for battery size search (kWh)")
    return p.parse_args()


def ten_year_savings_for_size(data, dates, cfg, battery_kwh, payback_years):
    """Return cumulative savings over payback_years for a given battery size."""
    cumulative = 0.0
    for year in range(1, payback_years + 1):
        growth = 1 + cfg.usage_growth
        rate = (1 + cfg.energy_inflation) ** (year - 1)

        _, _, nb_cost = calc_no_battery(data, dates, cfg, growth, rate)
        _, _, bt_cost, _ = calc_with_battery(data, dates, cfg, growth, rate,
                     battery_size_override=battery_kwh)
        cumulative += nb_cost - bt_cost
    return cumulative


def main():
    cfg = parse_args()

    # We need cfg.battery_size set for calc_with_battery fallback, but we
    # always pass battery_size_override so it won't matter. Set a dummy.
    cfg.battery_size = 0.0

    print(f"Finding largest battery with {cfg.payback_years}-year payback")
    print("=" * 60)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(script_dir, cfg.nem12_file)

    data = parse_nem12(filepath)
    dates = get_sorted_dates(data)

    if not dates:
        print("Error: No valid data found in NEM12 file.")
        sys.exit(1)

    num_days = len(dates)
    print(f"\nData: {num_days} days ({dates[0]} to {dates[-1]})")
    print(f"\nConfiguration:")
    print(f"  Energy rate:       ${cfg.energy_rate:.4f}/kWh")
    print(f"  Daily supply:      ${cfg.daily_supply_charge:.4f}/day")
    print(f"  Feed-in tariff:    ${cfg.feed_in_tariff:.2f}/kWh")
    print(f"  Energy inflation:  {cfg.energy_inflation * 100:.1f}%/yr")
    print(f"  Usage growth:      {cfg.usage_growth * 100:.1f}%")
    print(f"  Cost per kWh:      ${cfg.cost_per_kwh:,.0f}/kWh")
    print(f"  Reserve:           {cfg.battery_reserve * 100:.0f}%")
    print(f"  Efficiency:        {cfg.battery_efficiency * 100:.0f}%")
    print(f"  Payback target:    {cfg.payback_years} years")

    # Binary search: find largest battery_kwh where
    #   savings(battery_kwh, payback_years) >= cost_per_kwh * battery_kwh
    lo = 0.0
    hi = cfg.max_search_kwh
    tolerance = 0.1  # kWh

    # Check that a tiny battery pays back (sanity check)
    tiny_savings = ten_year_savings_for_size(data, dates, cfg, 0.1, cfg.payback_years)
    tiny_cost = cfg.cost_per_kwh * 0.1
    if tiny_savings < tiny_cost:
        print(f"\n  Even a 0.1 kWh battery does not pay back in "
              f"{cfg.payback_years} years at ${cfg.cost_per_kwh}/kWh.")
        sys.exit(0)

    # Check upper bound
    hi_savings = ten_year_savings_for_size(data, dates, cfg, hi, cfg.payback_years)
    hi_cost = cfg.cost_per_kwh * hi
    if hi_savings >= hi_cost:
        print(f"\n  Even a {hi} kWh battery pays back in {cfg.payback_years} years.")
        print(f"  Try increasing --max-search-kwh beyond {hi}.")
        sys.exit(0)

    print(f"\n  Searching between {lo:.1f} and {hi:.1f} kWh ...")

    while hi - lo > tolerance:
        mid = (lo + hi) / 2
        savings = ten_year_savings_for_size(data, dates, cfg, mid, cfg.payback_years)
        cost = cfg.cost_per_kwh * mid
        if savings >= cost:
            lo = mid
        else:
            hi = mid

    best_kwh = lo
    best_cost = cfg.cost_per_kwh * best_kwh
    best_savings = ten_year_savings_for_size(data, dates, cfg, best_kwh, cfg.payback_years)

    print(f"\n{'─' * 60}")
    print(f"Result")
    print(f"{'─' * 60}")
    print(f"\n  Largest battery with {cfg.payback_years}-year payback:")
    print(f"    Battery size:        {best_kwh:>8.1f} kWh")
    print(f"    Battery cost:        ${best_cost:>10,.0f}")
    print(f"    {cfg.payback_years}-year savings:    ${best_savings:>10,.0f}")


if __name__ == "__main__":
    main()
