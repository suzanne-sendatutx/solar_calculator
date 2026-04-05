#!/usr/bin/env python3
"""Solar Battery Payback Calculator

Reads NEM12 interval data and calculates energy costs with and without
a battery, payback period, and maximum battery cost for 10-year payback.
"""

import argparse
import os
import sys

# ── Default Configuration ─────────────────────────────────────────────────────

DEFAULT_NEM12_FILE = "QB04868277_20250326_20260326_20260327083826_ENERGEXP_DETAILED.csv"

DEFAULT_ENERGY_RATE = 0.3524
DEFAULT_CONTROLLED_LOAD_RATE = 0.3524
DEFAULT_DAILY_SUPPLY_CHARGE = 1.4287
DEFAULT_FEED_IN_TARIFF = 0.03
DEFAULT_ENERGY_INFLATION = 0.03
DEFAULT_USAGE_GROWTH = 0.0

DEFAULT_BATTERY_SIZE_KWH = 25
DEFAULT_BATTERY_COST = 14000
DEFAULT_BATTERY_RESERVE_PCT = 0.20
DEFAULT_BATTERY_EFFICIENCY = 0.90

DEFAULT_HW_START_INTERVAL = 120
DEFAULT_HW_END_INTERVAL = 168


def parse_args(argv=None):
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(
        description="Solar Battery Payback Calculator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--nem12-file", default=DEFAULT_NEM12_FILE,
                   help="Path to NEM12 CSV file")
    p.add_argument("--energy-rate", type=float, default=DEFAULT_ENERGY_RATE,
                   help="Energy import rate ($/kWh)")
    p.add_argument("--controlled-load-rate", type=float, default=DEFAULT_CONTROLLED_LOAD_RATE,
                   help="Controlled load import rate ($/kWh) for E2")
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
    return p.parse_args(argv)


# ── NEM12 Parsing ─────────────────────────────────────────────────────────────

def parse_nem12(filepath):
    """Parse NEM12 CSV file and return interval data by date and channel.

    Returns dict: {date_str: {'B1': [288 floats], 'E1': [...], 'E2': [...]}}
    """
    data = {}
    current_channel = None

    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            record_type = parts[0]

            if record_type == "200":
                current_channel = parts[3]  # B1, E1, or E2

            elif record_type == "300" and current_channel in ("B1", "E1", "E2"):
                date_str = parts[1]
                values = [float(v) for v in parts[2:290]]

                if date_str not in data:
                    data[date_str] = {}

                if current_channel == "E2" and "E2" in data[date_str]:
                    # Merge second E2 segment (non-overlapping dates, but be safe)
                    existing = data[date_str]["E2"]
                    data[date_str]["E2"] = [
                        existing[i] + values[i] for i in range(288)
                    ]
                else:
                    data[date_str][current_channel] = values

    return data


def get_sorted_dates(data):
    """Return sorted list of dates that have at least B1 and E1 channels."""
    return sorted(d for d in data if "B1" in data[d] and "E1" in data[d])


# ── Cost Calculations ─────────────────────────────────────────────────────────

ZERO_288 = [0.0] * 288


def calc_no_battery(data, dates, cfg, growth_factor=1.0, rate_factor=1.0):
    """Calculate annual cost without battery (current setup).

    Controlled load (E2) stays on grid as-is. B1 export unchanged.
    E1 and E2 consumption scaled by growth_factor.
    Inflation is applied to import and supply charges only.
    Feed-in tariff remains fixed in nominal terms.
    """
    total_e1_import_kwh = 0.0
    total_e2_import_kwh = 0.0
    total_export_kwh = 0.0

    for date in dates:
        b1 = data[date].get("B1", ZERO_288)
        e1 = data[date].get("E1", ZERO_288)
        e2 = data[date].get("E2", ZERO_288)

        for i in range(288):
            total_e1_import_kwh += e1[i] * growth_factor
            total_e2_import_kwh += e2[i] * growth_factor
            total_export_kwh += b1[i]

    num_days = len(dates)
    inflated_import_and_supply = (
        total_e1_import_kwh * cfg.energy_rate
        + total_e2_import_kwh * cfg.controlled_load_rate
        + num_days * cfg.daily_supply_charge
    ) * rate_factor
    fixed_feed_in_credit = total_export_kwh * cfg.feed_in_tariff
    cost = inflated_import_and_supply - fixed_feed_in_credit

    total_import_kwh = total_e1_import_kwh + total_e2_import_kwh

    return total_import_kwh, total_export_kwh, cost


def calc_with_battery(data, dates, cfg, growth_factor=1.0, rate_factor=1.0,
                      battery_size_override=None):
    """Calculate annual cost with battery.

    E2 (controlled load) is removed from grid and redistributed to
    a fixed daytime timer window (10am-2pm). Battery charges from solar
    surplus and discharges to power the house only (no VPP / no night export).
    """
    battery_size = battery_size_override if battery_size_override is not None else cfg.battery_size
    min_level = battery_size * cfg.battery_reserve
    max_level = battery_size
    battery_level = min_level  # Start at reserve level

    total_import_kwh = 0.0
    total_export_kwh = 0.0
    grid_import_days = 0

    hw_intervals = cfg.hw_end - cfg.hw_start

    for date in dates:
        b1 = data[date].get("B1", ZERO_288)
        e1 = data[date].get("E1", ZERO_288)
        e2 = data[date].get("E2", ZERO_288)
        day_had_grid_import = False

        # Redistribute daily E2 total evenly across hot water window
        daily_e2 = sum(e2) * growth_factor
        hw_per_interval = daily_e2 / hw_intervals

        for i in range(288):
            hw = hw_per_interval if cfg.hw_start <= i < cfg.hw_end else 0.0
            surplus = b1[i]
            demand = e1[i] * growth_factor + hw

            net = surplus - demand

            if net > 0:
                # Solar surplus after house + hot water → charge battery, export rest
                charge_room = max_level - battery_level
                max_charge_input = charge_room / cfg.battery_efficiency
                charge_input = min(net, max_charge_input)
                battery_level += charge_input * cfg.battery_efficiency

                total_export_kwh += net - charge_input
            else:
                # Shortfall → discharge battery, import remainder from grid
                shortfall = -net
                available = battery_level - min_level
                discharge = min(shortfall, available)
                battery_level -= discharge

                grid_import = shortfall - discharge
                total_import_kwh += grid_import
                if grid_import > 0:
                    day_had_grid_import = True

        if day_had_grid_import:
            grid_import_days += 1

    num_days = len(dates)
    inflated_import_and_supply = (
        total_import_kwh * cfg.energy_rate
        + num_days * cfg.daily_supply_charge
    ) * rate_factor
    fixed_feed_in_credit = total_export_kwh * cfg.feed_in_tariff
    cost = inflated_import_and_supply - fixed_feed_in_credit

    return (
        total_import_kwh,
        total_export_kwh,
        cost,
        grid_import_days,
    )


def calc_no_solar(data, dates, cfg, growth_factor=1.0, rate_factor=1.0):
    """Calculate annual cost with NO solar input (grid-only baseline).

    All consumption (E1 + E2) must come from grid.
    We estimate additional missing grid import from on-site solar as B1,
    i.e. if solar did not exist, that energy would also be imported.
    No export, no solar generation.
    Inflation is applied to import and supply charges only.
    """
    total_e1_import_kwh = 0.0
    total_e2_import_kwh = 0.0
    estimated_missing_import_kwh = 0.0

    for date in dates:
        b1 = data[date].get("B1", ZERO_288)
        e1 = data[date].get("E1", ZERO_288)
        e2 = data[date].get("E2", ZERO_288)

        for i in range(288):
            estimated_missing_import_kwh += b1[i]
            total_e1_import_kwh += e1[i] * growth_factor
            total_e2_import_kwh += e2[i] * growth_factor

    num_days = len(dates)
    total_import_kwh = (
        total_e1_import_kwh
        + total_e2_import_kwh
        + estimated_missing_import_kwh
    )
    inflated_import_and_supply = (
        (total_e1_import_kwh + estimated_missing_import_kwh) * cfg.energy_rate
        + total_e2_import_kwh * cfg.controlled_load_rate
        + num_days * cfg.daily_supply_charge
    ) * rate_factor
    cost = inflated_import_and_supply

    return total_import_kwh, estimated_missing_import_kwh, cost


def annual_savings_series(data, dates, cfg, years):
    """Return annual bill savings series (no battery cost - with battery cost)."""
    savings = []
    for year in range(1, years + 1):
        growth = 1 + cfg.usage_growth
        rate = (1 + cfg.energy_inflation) ** (year - 1)

        _, _, nb_yr_cost = calc_no_battery(data, dates, cfg, growth, rate)
        _, _, bt_yr_cost, _ = calc_with_battery(data, dates, cfg, growth, rate)
        savings.append(nb_yr_cost - bt_yr_cost)
    return savings


def compute_payback_year(savings_by_year, battery_cost):
    """Return payback year from annual savings list, or None if not reached."""
    cumulative = 0.0
    for year, annual_savings in enumerate(savings_by_year, start=1):
        cumulative += annual_savings
        if cumulative >= battery_cost:
            return year
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    cfg = parse_args()

    print("Solar Battery Payback Calculator")
    print("=" * 60)

    # Resolve file path relative to script location
    script_dir = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(script_dir, cfg.nem12_file)

    data = parse_nem12(filepath)
    dates = get_sorted_dates(data)

    if not dates:
        print("Error: No valid data found in NEM12 file.")
        sys.exit(1)

    num_days = len(dates)
    print(f"\nData: {num_days} days ({dates[0]} to {dates[-1]})")

    # ── Configuration summary ─────────────────────────────────────────────
    print(f"\nConfiguration:")
    print(f"  Energy rate:       ${cfg.energy_rate:.4f}/kWh")
    print(f"  Controlled load:   ${cfg.controlled_load_rate:.4f}/kWh")
    print(f"  Daily supply:      ${cfg.daily_supply_charge:.4f}/day")
    print(f"  Feed-in tariff:    ${cfg.feed_in_tariff:.2f}/kWh")
    print(f"  Energy inflation:  {cfg.energy_inflation * 100:.1f}%/yr")
    print(f"  Usage growth:      {cfg.usage_growth * 100:.1f}%")
    print(f"  Battery:           {cfg.battery_size} kWh, "
          f"{cfg.battery_reserve * 100:.0f}% reserve, "
          f"{cfg.battery_efficiency * 100:.0f}% efficiency")
    print(f"  Battery cost:      ${cfg.battery_cost:,.0f}")

    # ── Year 1 results ────────────────────────────────────────────────────
    ns_import, ns_extra_import, ns_cost = calc_no_solar(data, dates, cfg)
    nb_import, nb_export, nb_cost = calc_no_battery(data, dates, cfg)
    bt_import, bt_export, bt_cost, bt_grid_import_days = calc_with_battery(
        data, dates, cfg
    )
    year1_savings_vs_solar = nb_cost - bt_cost
    solar_savings = ns_cost - nb_cost
    battery_savings = ns_cost - bt_cost

    print(f"\n{'─' * 60}")
    print(f"Year 1 (current rates)")
    print(f"{'─' * 60}")

    print(f"\n  Baseline (no solar, grid-only):")
    print(f"    Grid import:  {ns_import:>10,.1f} kWh")
    print(f"    Extra import if no solar (est): {ns_extra_import:>10,.1f} kWh")
    print(f"    Annual cost:  {ns_cost:>10,.2f}")

    print(f"\n  Without battery (current setup with solar):")
    print(f"    Grid import:  {nb_import:>10,.1f} kWh")
    print(f"    Solar export: {nb_export:>10,.1f} kWh")
    print(f"    Annual cost:  {nb_cost:>10,.2f}")
    print(f"    Savings vs baseline: ${solar_savings:>10,.2f}")

    print(f"\n  With battery:")
    print(f"    Grid import:  {bt_import:>10,.1f} kWh")
    print(f"    Solar export: {bt_export:>10,.1f} kWh")
    print(f"    Annual cost:  {bt_cost:>10,.2f}")
    print(f"    Days with any grid import:          {bt_grid_import_days:>5}")
    print(f"    Savings vs baseline: ${battery_savings:>10,.2f}")

    print(f"\n  Battery additional savings: ${year1_savings_vs_solar:,.2f}")

    # ── Multi-year payback analysis ───────────────────────────────────────
    print(f"\n{'─' * 60}")
    print(f"Payback Analysis")
    print(f"{'─' * 60}")

    max_years = 30
    savings_30y = annual_savings_series(data, dates, cfg, max_years)
    payback_year = compute_payback_year(savings_30y, cfg.battery_cost)
    ten_year_savings = sum(savings_30y[:10])

    if payback_year is not None:
        print(f"\n  Payback period:  {payback_year} years")
    else:
        print(f"\n  Payback period:  >{max_years} years (not reached)")

    print(f"\n  Max battery cost for 10-year payback: ${ten_year_savings:,.0f}")
    if cfg.battery_cost <= ten_year_savings:
        print(f"  → At ${cfg.battery_cost:,.0f}, battery WILL pay back within 10 years")
    else:
        print(f"  → At ${cfg.battery_cost:,.0f}, battery will NOT pay back within 10 years")


if __name__ == "__main__":
    main()
