"""Reproducible experiment runner.

``python experiments.py`` writes every CSV under ``results/`` and prints the
numbers quoted in the README.  Nothing in the app is hand-typed: the README
tables and the figures are both generated from these files.
"""

from __future__ import annotations

import os
from dataclasses import replace

import pandas as pd

import cbam as cbam_mod
import levers as levers_mod
from config import SIMULATED_DATA_NOTICE, load_scenario
from plant import mean_ci, monte_carlo, run_plant

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
SEEDS = list(range(1, 21))
MC_CV = 0.25


def _write(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    frame.to_csv(os.path.join(RESULTS_DIR, name), index=False)
    return frame


# ------------------------------------------------------------------- 1 plant ---
def baseline_table(scenario) -> pd.DataFrame:
    r = run_plant(scenario)
    rows = [
        ("good_parts_per_year", r.good_parts, "parts"),
        ("output", r.output_t, "t"),
        ("eu_shipped", r.eu_output_t, "t"),
        ("bottleneck_station", r.bottleneck, ""),
        ("oee_availability", r.availability, "share"),
        ("oee_performance", r.performance, "share"),
        ("oee_quality", r.quality, "share"),
        ("oee", r.oee, "share"),
        ("electricity", r.electricity_mwh, "MWh"),
        ("fuel", r.gas_mwh_th, "MWh thermal"),
        ("steel_input", r.input_steel_t, "t"),
        ("material_yield", r.meta["material_yield"], "share"),
        ("direct_emissions", r.direct_t_co2, "t CO2e"),
        ("indirect_emissions", r.indirect_t_co2, "t CO2e"),
        ("precursor_emissions", r.precursor_t_co2, "t CO2e"),
        ("total_emissions", r.total_t_co2, "t CO2e"),
        ("see_total", r.see_total, "t CO2e per t"),
        ("kg_co2e_per_part", r.kg_co2e_per_part, "kg"),
        ("avoidable_share", r.avoidable_share(scenario.factors), "share"),
        ("energy_cost", r.energy_cost_eur, "EUR"),
        ("conversion_cost", r.conversion_cost_eur, "EUR"),
    ]
    return _write(
        pd.DataFrame(rows, columns=["metric", "value", "unit"]), "baseline.csv"
    )


def loss_attribution_table(scenario) -> pd.DataFrame:
    r = run_plant(scenario)
    carbon = r.carbon_loss_t_co2(scenario.factors)
    rows = []
    for bucket, t_co2 in carbon.items():
        rows.append(
            {
                "bucket": bucket,
                "electricity_mwh": r.electricity_loss_mwh.get(bucket, 0.0),
                "fuel_mwh_th": r.gas_loss_mwh.get(bucket, 0.0),
                "steel_t": r.material_loss_t.get(bucket, 0.0),
                "t_co2e": t_co2,
                "share_of_total": t_co2 / r.total_t_co2,
                "kg_co2e_per_part": t_co2 * 1000.0 / r.good_parts,
            }
        )
    return _write(pd.DataFrame(rows), "loss_attribution.csv")


def monte_carlo_table(scenario) -> pd.DataFrame:
    results = monte_carlo(scenario, SEEDS, cv=MC_CV)
    rows = []
    for name, getter in [
        ("output_t", lambda x: x.output_t),
        ("see_total", lambda x: x.see_total),
        ("kg_co2e_per_part", lambda x: x.kg_co2e_per_part),
        ("total_emissions_t", lambda x: x.total_t_co2),
        ("oee", lambda x: x.oee),
    ]:
        values = [getter(x) for x in results]
        mean, half = mean_ci(values)
        rows.append(
            {
                "metric": name,
                "mean": mean,
                "ci95_half_width": half,
                "min": min(values),
                "max": max(values),
                "seeds": len(values),
                "cv_applied": MC_CV,
            }
        )
    return _write(pd.DataFrame(rows), "monte_carlo.csv")


# -------------------------------------------------------------------- 2 cbam ---
def basis_table(scenario) -> pd.DataFrame:
    r = run_plant(scenario)
    rows = []
    for year in scenario.cbam.years:
        comparison = cbam_mod.basis_comparison(
            r, scenario, year=year, recognise_actual_electricity=True
        )
        comparison["year"] = year
        rows.append(comparison)
    frame = pd.DataFrame(rows)[
        [
            "year",
            "see_actual",
            "see_default",
            "cost_actual_eur",
            "cost_default_eur",
            "saving_eur",
            "saving_share",
        ]
    ]
    return _write(frame, "basis_comparison.csv")


def phase_in_table(scenario) -> pd.DataFrame:
    r = run_plant(scenario)
    declaration = cbam_mod.declare(r, scenario, recognise_actual_electricity=True)
    rows = cbam_mod.phase_in_exposure(
        declaration.see_declared, declaration.benchmark, scenario.cbam
    )
    at_benchmark = cbam_mod.phase_in_exposure(
        declaration.benchmark, declaration.benchmark, scenario.cbam
    )
    for row, bench_row in zip(rows, at_benchmark):
        row["liable_share_at_benchmark"] = bench_row["liable_share_of_own_emissions"]
    return _write(pd.DataFrame(rows), "phase_in.csv")


def trajectory_table(scenario) -> pd.DataFrame:
    r = run_plant(scenario)
    years = scenario.cbam.years
    paths = {
        "flat_90": {y: scenario.prices.ets_price_eur_per_t for y in years},
        "growth_6pc": cbam_mod.ets_price_path(
            scenario.prices.ets_price_eur_per_t, years, 0.06
        ),
        "growth_10pc": cbam_mod.ets_price_path(
            scenario.prices.ets_price_eur_per_t, years, 0.10
        ),
    }
    rows = []
    for label, path in paths.items():
        for declaration in cbam_mod.trajectory(
            r, scenario, years, path, recognise_actual_electricity=True
        ):
            rows.append(
                {
                    "ets_path": label,
                    "year": declaration.year,
                    "ets_price_eur_per_t": declaration.ets_price_eur_per_t,
                    "cbam_factor": declaration.cbam_factor,
                    "headline_payable_share": declaration.payable_share,
                    "gross_emissions_t": declaration.gross_emissions_t,
                    "free_allocation_t": declaration.free_allocation_t,
                    "liable_emissions_t": declaration.liable_emissions_t,
                    "net_cost_eur": declaration.net_cost_eur,
                    "cost_per_t_goods_eur": declaration.cost_per_t_goods,
                }
            )
    return _write(pd.DataFrame(rows), "trajectory.csv")


def de_minimis_table(scenario) -> pd.DataFrame:
    r = run_plant(scenario)
    rows = []
    for share in [i / 100 for i in range(1, 101, 1)]:
        mass = r.output_t * share
        declaration = cbam_mod.declare(
            r, scenario, mass_t=mass, recognise_actual_electricity=True
        )
        rows.append(
            {
                "eu_export_share": share,
                "eu_mass_t": mass,
                "exempt": declaration.exempt,
                "net_cost_eur": declaration.net_cost_eur,
                "cost_per_t_goods_eur": declaration.cost_per_t_goods,
            }
        )
    return _write(pd.DataFrame(rows), "de_minimis.csv")


def origin_price_table(scenario) -> pd.DataFrame:
    r = run_plant(scenario)
    rows = []
    for price_label, price in [
        ("idx_carbon_3.9", scenario.prices.origin_carbon_price_eur_per_t),
        ("target_40", 40.0),
        ("eu_parity_90", scenario.prices.ets_price_eur_per_t),
    ]:
        for coverage in [0.0, 0.25, 0.50, 0.75, 1.0]:
            scen = replace(
                scenario,
                prices=replace(
                    scenario.prices,
                    origin_carbon_price_eur_per_t=price,
                    origin_carbon_price_coverage=coverage,
                ),
            )
            for year in (2026, 2030, 2034):
                declaration = cbam_mod.declare(
                    r, scen, year=year, recognise_actual_electricity=True
                )
                rows.append(
                    {
                        "origin_price_label": price_label,
                        "origin_price_eur_per_t": price,
                        "coverage": coverage,
                        "year": year,
                        "net_cost_eur": declaration.net_cost_eur,
                        "origin_credit_eur": declaration.origin_credit_eur,
                    }
                )
    return _write(pd.DataFrame(rows), "origin_price.csv")


# ------------------------------------------------------------------ 3 levers ---
def levers_table(scenario) -> pd.DataFrame:
    results = levers_mod.evaluate_all(scenario)
    rows = []
    for item in results:
        rows.append(
            {
                "key": item.lever.key,
                "name": item.lever.name,
                "category": item.lever.category,
                "physical": item.lever.physical,
                "cbam_recognised": item.lever.cbam_recognised,
                "abatement_t_co2": item.abatement_t_co2,
                "see_after": item.see_total,
                "annualised_capex_eur": item.annualised_capex_eur,
                "delta_operating_eur": item.delta_operating_eur,
                "net_cost_eur": item.net_cost_eur,
                "cost_per_t_co2_eur": item.cost_per_t_co2_eur,
                "cbam_saving_eur": item.cbam_saving_eur,
                "net_cost_with_cbam_eur": item.net_cost_with_cbam_eur,
                "cost_per_t_co2_with_cbam_eur": item.cost_per_t_co2_with_cbam_eur,
                "payback_years": item.payback_years,
                "spare_capacity_t": item.spare_capacity_t,
                "flipped_by_cbam": item.flipped_by_cbam,
            }
        )
    return _write(pd.DataFrame(rows), "levers.csv")


def macc_table(scenario) -> pd.DataFrame:
    results = levers_mod.evaluate_all(scenario)
    rows = []
    for with_cbam in (False, True):
        curve = levers_mod.marginal_abatement_curve(results, with_cbam=with_cbam)
        cumulative = 0.0
        for item in curve:
            cost = (
                item.cost_per_t_co2_with_cbam_eur
                if with_cbam
                else item.cost_per_t_co2_eur
            )
            rows.append(
                {
                    "view": "with_cbam" if with_cbam else "engineering_only",
                    "key": item.lever.key,
                    "name": item.lever.name,
                    "abatement_t_co2": item.abatement_t_co2,
                    "cumulative_abatement_t_co2": cumulative + item.abatement_t_co2,
                    "cumulative_start_t_co2": cumulative,
                    "cost_per_t_co2_eur": cost,
                }
            )
            cumulative += item.abatement_t_co2
    return _write(pd.DataFrame(rows), "macc.csv")


def interaction_table(scenario) -> pd.DataFrame:
    shopfloor = [
        lever
        for lever in levers_mod.default_levers()
        if lever.key in ("spc", "pdm", "standby", "air", "nesting")
    ]
    gap = levers_mod.interaction_gap(scenario, shopfloor)
    gap["levers"] = "+".join(lever.key for lever in shopfloor)
    return _write(pd.DataFrame([gap]), "interaction.csv")


def eaf_trajectory_table(scenario) -> pd.DataFrame:
    """When does the scrap-route advantage stop zeroing the bill?"""
    baseline = run_plant(scenario)
    eaf_lever = next(
        lever for lever in levers_mod.default_levers() if lever.key == "eaf_coil"
    )
    eaf_scenario = levers_mod.match_output(
        eaf_lever.apply(scenario), baseline.output_t
    )
    eaf_result = run_plant(eaf_scenario)
    rows = []
    for year in scenario.cbam.years:
        base = cbam_mod.declare(
            baseline, scenario, year=year, recognise_actual_electricity=True
        )
        eaf = cbam_mod.declare(
            eaf_result,
            eaf_scenario,
            year=year,
            mass_t=baseline.eu_output_t,
            recognise_actual_electricity=True,
        )
        rows.append(
            {
                "year": year,
                "sefa": base.sefa,
                "see_bf_bof": base.see_declared,
                "see_scrap_eaf": eaf.see_declared,
                "cost_bf_bof_eur": base.net_cost_eur,
                "cost_scrap_eaf_eur": eaf.net_cost_eur,
                "saving_eur": base.net_cost_eur - eaf.net_cost_eur,
                "eaf_bill_is_zero": eaf.net_cost_eur <= 0.0,
            }
        )
    return _write(pd.DataFrame(rows), "eaf_trajectory.csv")


# --------------------------------------------------------------------- main ---
def run_all(scenario=None) -> dict[str, pd.DataFrame]:
    scenario = load_scenario() if scenario is None else scenario
    return {
        "baseline": baseline_table(scenario),
        "loss_attribution": loss_attribution_table(scenario),
        "monte_carlo": monte_carlo_table(scenario),
        "basis_comparison": basis_table(scenario),
        "phase_in": phase_in_table(scenario),
        "trajectory": trajectory_table(scenario),
        "de_minimis": de_minimis_table(scenario),
        "origin_price": origin_price_table(scenario),
        "levers": levers_table(scenario),
        "macc": macc_table(scenario),
        "interaction": interaction_table(scenario),
        "eaf_trajectory": eaf_trajectory_table(scenario),
    }


def main() -> None:
    scenario = load_scenario()
    tables = run_all(scenario)
    result = run_plant(scenario)
    declaration = cbam_mod.declare(result, scenario, recognise_actual_electricity=True)

    print(SIMULATED_DATA_NOTICE)
    print()
    print("PLANT")
    print(f"  output                {result.output_t:,.0f} t/yr ({result.good_parts:,.0f} parts)")
    print(f"  bottleneck            {result.bottleneck}, OEE {result.oee:.1%}")
    print(f"  footprint             {result.see_total:.3f} t CO2e/t  ({result.kg_co2e_per_part:.1f} kg/part)")
    print(f"  not value-adding      {result.avoidable_share(scenario.factors):.1%} of emissions")

    print("CBAM")
    print(f"  shipped to the EU     {declaration.mass_t:,.0f} t, above the {declaration.de_minimis_t:,.0f} t de minimis")
    print(f"  2026 liable share     {declaration.liable_emissions_t / declaration.gross_emissions_t:.1%} of own emissions, headline payable share {declaration.payable_share:.1%}")
    print(f"  2026 bill             EUR {declaration.net_cost_eur:,.0f} ({declaration.cost_per_t_goods:,.2f}/t)")
    final = tables["trajectory"].query("ets_path == 'flat_90' and year == 2034").iloc[0]
    print(f"  2034 bill, flat price EUR {final['net_cost_eur']:,.0f}")

    basis = tables["basis_comparison"].query("year == 2026").iloc[0]
    print(f"  verified vs default   EUR {basis['saving_eur']:,.0f}/yr saved ({basis['saving_share']:.0%})")

    print("LEVERS")
    flipped = tables["levers"].query("flipped_by_cbam")
    for _, row in tables["levers"].iterrows():
        marker = " <- flipped by CBAM" if row["flipped_by_cbam"] else ""
        print(
            f"  {row['name'][:38]:40s} {row['abatement_t_co2']:7.1f} t  "
            f"EUR {row['cost_per_t_co2_eur']:8.1f}/t -> {row['cost_per_t_co2_with_cbam_eur']:8.1f}/t{marker}"
        )
    print(f"  flipped by CBAM       {', '.join(flipped['key']) if len(flipped) else 'none'}")
    gap = tables["interaction"].iloc[0]
    print(
        f"  interaction           individual {gap['sum_of_individual_t']:.0f} t vs combined "
        f"{gap['combined_t']:.0f} t ({gap['gap_share']:.1%} overlap)"
    )
    print()
    print(f"Wrote {len(tables)} CSV files to results/")


if __name__ == "__main__":
    main()
