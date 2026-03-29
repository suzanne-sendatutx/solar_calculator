#!/usr/bin/env python3
"""Plot opportunity cost of buying a battery vs investing upfront capital."""

import argparse
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from solar_calculator import (
    DEFAULT_BATTERY_COST,
    DEFAULT_BATTERY_EFFICIENCY,
    DEFAULT_BATTERY_RESERVE_PCT,
    DEFAULT_BATTERY_SIZE_KWH,
    DEFAULT_DAILY_SUPPLY_CHARGE,
    DEFAULT_ENERGY_INFLATION,
    DEFAULT_ENERGY_RATE,
    DEFAULT_FEED_IN_TARIFF,
    DEFAULT_HW_END_INTERVAL,
    DEFAULT_HW_START_INTERVAL,
    DEFAULT_NEM12_FILE,
    DEFAULT_USAGE_GROWTH,
    calc_no_battery,
    calc_with_battery,
    compute_payback_year,
    get_sorted_dates,
    parse_nem12,
)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Plot battery opportunity cost vs investing upfront capital",
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

    p.add_argument("--battery-size", type=float, default=DEFAULT_BATTERY_SIZE_KWH,
                   help="Battery capacity (kWh)")
    p.add_argument("--battery-cost", type=float, default=DEFAULT_BATTERY_COST,
                   help="Battery purchase + installation cost ($)")
    p.add_argument("--battery-reserve", type=float, default=DEFAULT_BATTERY_RESERVE_PCT,
                   help="Battery reserve fraction (0-1)")
    p.add_argument("--battery-efficiency", type=float, default=DEFAULT_BATTERY_EFFICIENCY,
                   help="Battery round-trip efficiency (0-1)")
    p.add_argument("--hw-start", type=int, default=DEFAULT_HW_START_INTERVAL,
                   help="Hot water start interval (5-min index, 120=10am)")
    p.add_argument("--hw-end", type=int, default=DEFAULT_HW_END_INTERVAL,
                   help="Hot water end interval (5-min index, 168=2pm, exclusive)")

    p.add_argument("--years", type=int, default=15,
                   help="Number of years to model")
    p.add_argument("--investment-return", type=float, default=0.10,
                   help="Annual investment return (e.g. 0.10 = 10%%)")
    p.add_argument("--output", default="opportunity_cost_vs_battery.png",
                   help="Output PNG path")
    return p.parse_args(argv)


def annual_bill_series(data, dates, cfg, years):
    """Return annual no-battery and with-battery bill series."""
    no_battery_bills = []
    with_battery_bills = []

    for year in range(1, years + 1):
        growth = 1 + cfg.usage_growth
        rate = (1 + cfg.energy_inflation) ** (year - 1)

        _, _, nb_cost = calc_no_battery(data, dates, cfg, growth, rate)
        _, _, bt_cost, _ = calc_with_battery(data, dates, cfg, growth, rate)

        no_battery_bills.append(nb_cost)
        with_battery_bills.append(bt_cost)

    return no_battery_bills, with_battery_bills


def model_paths_and_tables(no_battery_bills, with_battery_bills, battery_cost,
                           annual_return):
    """Model both opportunity-cost paths and produce yearly cashflow tables.

    Returns:
    - years: [0..N]
    - battery_path: buy battery now, invest annual bill savings from year 1
    - invest_path: invest battery cost now, no annual withdrawals
    - battery_rows: yearly table rows for battery-first scenario
    - invest_rows: yearly table rows for invest-first scenario
    """
    years = [0]
    battery_path = [0.0]
    invest_path = [battery_cost]

    battery_rows = [{
        "year": 0,
        "money_invested": 0.0,
        "interest_earned": 0.0,
        "power_bills_paid": 0.0,
        "savings": 0.0,
        "portfolio_end": 0.0,
    }]
    invest_rows = [{
        "year": 0,
        "money_invested": battery_cost,
        "interest_earned": 0.0,
        "power_bills_paid": 0.0,
        "portfolio_end": battery_cost,
    }]

    battery_balance = 0.0
    invest_balance = battery_cost

    for i, (nb_bill, bt_bill) in enumerate(zip(no_battery_bills, with_battery_bills), start=1):
        annual_savings = nb_bill - bt_bill

        # Apply annual investment growth to existing balances
        battery_interest = battery_balance * annual_return
        invest_interest = invest_balance * annual_return
        battery_balance += battery_interest
        invest_balance += invest_interest

        # Scenario A: invest annual bill savings immediately from year 1
        battery_money_invested = annual_savings
        battery_balance += battery_money_invested

        # Scenario B: keep the upfront investment growing with no annual cashflow
        invest_money_invested = 0.0

        years.append(i)
        battery_path.append(battery_balance)
        invest_path.append(invest_balance)

        battery_rows.append({
            "year": i,
            "money_invested": battery_money_invested,
            "interest_earned": battery_interest,
            "power_bills_paid": bt_bill,
            "savings": annual_savings,
            "portfolio_end": battery_balance,
        })
        invest_rows.append({
            "year": i,
            "money_invested": invest_money_invested,
            "interest_earned": invest_interest,
            "power_bills_paid": nb_bill,
            "portfolio_end": invest_balance,
        })

    return years, battery_path, invest_path, battery_rows, invest_rows


def print_cashflow_table(title, rows, include_savings=False):
    """Print a simple yearly cashflow table."""
    print(f"\n{title}")
    if include_savings:
        print("-" * 119)
        print(f"{'Year':>4} | {'Money Invested ($)':>18} | {'Interest Earned ($)':>19} | {'Power Bills Paid ($)':>20} | {'Savings ($)':>11} | {'Portfolio End ($)':>17}")
        print("-" * 119)
    else:
        print("-" * 105)
        print(f"{'Year':>4} | {'Money Invested ($)':>18} | {'Interest Earned ($)':>19} | {'Power Bills Paid ($)':>20} | {'Portfolio End ($)':>17}")
        print("-" * 105)

    for r in rows:
        if include_savings:
            print(
                f"{r['year']:>4} | "
                f"{r['money_invested']:>18,.2f} | "
                f"{r['interest_earned']:>19,.2f} | "
                f"{r['power_bills_paid']:>20,.2f} | "
                f"{r['savings']:>11,.2f} | "
                f"{r['portfolio_end']:>17,.2f}"
            )
        else:
            print(
                f"{r['year']:>4} | "
                f"{r['money_invested']:>18,.2f} | "
                f"{r['interest_earned']:>19,.2f} | "
                f"{r['power_bills_paid']:>20,.2f} | "
                f"{r['portfolio_end']:>17,.2f}"
            )

    if include_savings:
        print("-" * 119)
    else:
        print("-" * 105)


def main():
    cfg = parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(script_dir, cfg.nem12_file)

    data = parse_nem12(filepath)
    dates = get_sorted_dates(data)
    if not dates:
        raise SystemExit("No valid NEM12 data found")

    no_battery_bills, with_battery_bills = annual_bill_series(data, dates, cfg, cfg.years)
    savings = [nb - bt for nb, bt in zip(no_battery_bills, with_battery_bills)]
    payback_year = compute_payback_year(savings, cfg.battery_cost)

    years, battery_path, invest_path, battery_rows, invest_rows = model_paths_and_tables(
        no_battery_bills,
        with_battery_bills,
        battery_cost=cfg.battery_cost,
        annual_return=cfg.investment_return,
    )

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(years, battery_path, linewidth=2.5,
            label="Buy battery now, invest annual bill savings")
    ax.plot(years, invest_path, linewidth=2.5,
            label="Invest battery cost now")

    ax.set_xlabel("Year")
    ax.set_ylabel("Portfolio Value ($)")
    ax.set_title("Battery Opportunity Cost vs Investing Upfront")
    ax.grid(True, alpha=0.3)
    ax.legend()

    if payback_year is not None:
        ax.axvline(payback_year, color="gray", linestyle="--", linewidth=1)
        ax.text(payback_year + 0.1, ax.get_ylim()[0] + 0.05 * (ax.get_ylim()[1] - ax.get_ylim()[0]),
                f"Payback year {payback_year}", color="gray")

    out_path = cfg.output
    if not os.path.isabs(out_path):
        out_path = os.path.join(script_dir, out_path)

    fig.savefig(out_path, dpi=150, bbox_inches="tight")

    print(f"Saved plot to {out_path}")
    if payback_year is not None:
        print(f"Battery payback year (bill savings only): {payback_year}")
    else:
        print("Battery does not pay back within model horizon")
    print(f"Year {cfg.years} portfolio (battery scenario): ${battery_path[-1]:,.2f}")
    print(f"Year {cfg.years} portfolio (invest-first scenario): ${invest_path[-1]:,.2f}")

    print_cashflow_table(
        "Scenario A: Buy Battery, Invest Annual Bill Savings",
        battery_rows,
        include_savings=True,
    )
    print_cashflow_table(
        "Scenario B: Invest Upfront Battery Cost",
        invest_rows,
        include_savings=False,
    )


if __name__ == "__main__":
    main()
