"""Layer 3 -- abatement levers, their economics, and the CBAM twist.

Every lever is evaluated **at the baseline order book**.  A lever that speeds
the line up would otherwise look worse than it is: more output means more
tonnes of CO2e even when every tonne of product got cleaner.  Because output is
exactly linear in planned production time in this model, matching the order
book is done by trimming operating days -- which is also what a plant would
really do -- and the test suite checks that the trimmed run lands on the target.

Two cost-of-abatement figures come out of each lever:

* the engineering one, capital recovery plus operating cost minus energy and
  material savings, and
* the same figure after the CBAM bill it avoids.

The gap between them is the point of the project: a carbon border price turns
part of a plant's efficiency backlog from a cost into an investment.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Sequence

import cbam as cbam_mod
from config import Scenario
from plant import PlantResult, run_plant


# ------------------------------------------------------------------ helpers ---
def capital_recovery_factor(rate: float, years: int) -> float:
    """Annual payment that repays 1 unit of capital over ``years``."""
    if years <= 0:
        raise ValueError("lifetime must be at least one year")
    if rate <= 0:
        return 1.0 / years
    return rate * (1.0 + rate) ** years / ((1.0 + rate) ** years - 1.0)


def match_output(scenario: Scenario, target_output_t: float) -> Scenario:
    """Trim or extend operating days so the plant produces exactly the target.

    Output is linear in ``days_per_year`` here: planned hours, changeover hours
    and therefore every station's runnable hours all scale together.  One
    evaluation is enough to find the right number of days.
    """
    current = run_plant(scenario).output_t
    if current <= 0:
        raise ValueError("baseline plant produces nothing")
    factor = target_output_t / current
    plant = replace(scenario.plant, days_per_year=scenario.plant.days_per_year * factor)
    return replace(scenario, plant=plant)


# -------------------------------------------------------------------- lever ---
@dataclass(frozen=True)
class Lever:
    """One improvement, with what it changes and what it costs."""

    key: str
    name: str
    category: str
    description: str
    apply: Callable[[Scenario], Scenario]
    capex_eur: float
    lifetime_years: int
    opex_eur_per_year: float
    cbam_recognised: bool = True
    physical: bool = True
    note: str = ""


@dataclass(frozen=True)
class LeverResult:
    lever: Lever
    output_t: float
    see_total: float
    emissions_t_co2: float
    abatement_t_co2: float

    annualised_capex_eur: float
    delta_operating_eur: float
    net_cost_eur: float
    cost_per_t_co2_eur: float

    cbam_cost_eur: float
    cbam_saving_eur: float
    net_cost_with_cbam_eur: float
    cost_per_t_co2_with_cbam_eur: float
    payback_years: float

    spare_capacity_t: float

    @property
    def profitable_without_cbam(self) -> bool:
        return self.net_cost_eur < 0

    @property
    def profitable_with_cbam(self) -> bool:
        return self.net_cost_with_cbam_eur < 0

    @property
    def flipped_by_cbam(self) -> bool:
        """True when the CBAM bill is what makes the lever worth doing."""
        return (not self.profitable_without_cbam) and self.profitable_with_cbam


def _operating_cost(result: PlantResult) -> float:
    return result.conversion_cost_eur


def evaluate_lever(
    lever: Lever,
    scenario: Scenario,
    baseline: PlantResult | None = None,
    *,
    year: int | None = None,
    basis: str = cbam_mod.ACTUAL,
) -> LeverResult:
    """Price one lever against the baseline, at the baseline order book."""
    baseline = run_plant(scenario) if baseline is None else baseline
    target_output = baseline.output_t
    eu_mass = baseline.eu_output_t

    base_declaration = cbam_mod.declare(
        baseline, scenario, basis=basis, year=year, mass_t=eu_mass,
        recognise_actual_electricity=True,
    )

    improved_scenario = lever.apply(scenario)
    # Free capacity the lever creates, before trimming back to the order book.
    uncapped = run_plant(improved_scenario)
    matched_scenario = match_output(improved_scenario, target_output)
    matched = run_plant(matched_scenario)

    declaration = cbam_mod.declare(
        matched,
        matched_scenario,
        basis=basis,
        year=year,
        mass_t=eu_mass,
        recognise_actual_electricity=lever.cbam_recognised,
    )

    abatement = baseline.total_t_co2 - matched.total_t_co2
    annualised_capex = lever.capex_eur * capital_recovery_factor(
        scenario.prices.discount_rate, lever.lifetime_years
    )
    delta_operating = (
        _operating_cost(matched) - _operating_cost(baseline) + lever.opex_eur_per_year
    )
    net_cost = annualised_capex + delta_operating
    cbam_saving = base_declaration.net_cost_eur - declaration.net_cost_eur
    net_with_cbam = net_cost - cbam_saving

    annual_benefit = -delta_operating + cbam_saving
    payback = (
        lever.capex_eur / annual_benefit
        if annual_benefit > 0 and lever.capex_eur > 0
        else float("inf")
    )

    return LeverResult(
        lever=lever,
        output_t=matched.output_t,
        see_total=matched.see_total,
        emissions_t_co2=matched.total_t_co2,
        abatement_t_co2=abatement,
        annualised_capex_eur=annualised_capex,
        delta_operating_eur=delta_operating,
        net_cost_eur=net_cost,
        cost_per_t_co2_eur=net_cost / abatement if abatement > 0 else float("inf"),
        cbam_cost_eur=declaration.net_cost_eur,
        cbam_saving_eur=cbam_saving,
        net_cost_with_cbam_eur=net_with_cbam,
        cost_per_t_co2_with_cbam_eur=(
            net_with_cbam / abatement if abatement > 0 else float("inf")
        ),
        payback_years=payback,
        spare_capacity_t=uncapped.output_t - target_output,
    )


# --------------------------------------------------------------- lever book ---
def _scale_scrap(factor: float):
    def fn(scenario: Scenario) -> Scenario:
        return replace(
            scenario,
            plant=scenario.plant.map_stations(
                lambda s: replace(s, scrap_rate=s.scrap_rate * factor)
            ),
        )

    return fn


def _predictive_maintenance(mtbf_gain: float, mttr_cut: float):
    def fn(scenario: Scenario) -> Scenario:
        return replace(
            scenario,
            plant=scenario.plant.map_stations(
                lambda s: replace(
                    s,
                    mtbf_h=s.mtbf_h * (1.0 + mtbf_gain),
                    mttr_h=s.mttr_h * (1.0 - mttr_cut),
                )
            ),
        )

    return fn


def _standby_policy(idle_cut: float, gas_idle_cut: float):
    def fn(scenario: Scenario) -> Scenario:
        return replace(
            scenario,
            plant=scenario.plant.map_stations(
                lambda s: replace(
                    s,
                    power_idle_kw=s.power_idle_kw * (1.0 - idle_cut),
                    gas_idle_kw=s.gas_idle_kw * (1.0 - gas_idle_cut),
                )
            ),
        )

    return fn


def _fix_air_leaks(cut: float):
    def fn(scenario: Scenario) -> Scenario:
        return replace(
            scenario,
            plant=replace(
                scenario.plant,
                compressed_air_leak_kw=scenario.plant.compressed_air_leak_kw * (1.0 - cut),
            ),
        )

    return fn


def _better_nesting(new_input_mass_kg: float):
    def fn(scenario: Scenario) -> Scenario:
        return replace(
            scenario, plant=replace(scenario.plant, input_mass_kg=new_input_mass_kg)
        )

    return fn


def _onsite_solar(share_of_electricity: float):
    """Behind-the-meter generation.

    The share of consumption the array covers is both carbon-free and
    bill-free, so the effective grid factor and the effective electricity
    price both fall by the same share.  The array itself is paid for through
    the lever's capital cost.
    """

    def fn(scenario: Scenario) -> Scenario:
        factors = replace(
            scenario.factors,
            ef_grid_t_co2_per_mwh=scenario.factors.ef_grid_t_co2_per_mwh
            * (1.0 - share_of_electricity),
        )
        prices = replace(
            scenario.prices,
            electricity_eur_per_mwh=scenario.prices.electricity_eur_per_mwh
            * (1.0 - share_of_electricity),
        )
        return replace(scenario, factors=factors, prices=prices)

    return fn


def _market_based_claim(share_of_electricity: float):
    """Certificate purchase: the reported factor falls, nothing physical does.

    Grid electricity is still bought and still burnt somewhere, so the bill
    does not fall.  The lower factor is a market-based scope 2 claim only.
    """

    def fn(scenario: Scenario) -> Scenario:
        factors = replace(
            scenario.factors,
            ef_grid_t_co2_per_mwh=scenario.factors.ef_grid_t_co2_per_mwh
            * (1.0 - share_of_electricity),
        )
        return replace(scenario, factors=factors)

    return fn


def _switch_precursor():
    def fn(scenario: Scenario) -> Scenario:
        factors = replace(
            scenario.factors,
            ef_precursor_t_co2_per_t=scenario.factors.ef_precursor_scrap_eaf_t_co2_per_t,
        )
        prices = replace(
            scenario.prices,
            steel_eur_per_t=scenario.prices.steel_eur_per_t
            + scenario.prices.steel_scrap_eaf_premium_eur_per_t,
        )
        return replace(scenario, factors=factors, prices=prices)

    return fn


def default_levers() -> list[Lever]:
    """The improvement backlog of the simulated plant.

    Capital costs, lifetimes and effect sizes are illustrative and chosen to be
    plausible for a plant of this size; they are not quotations.
    """
    return [
        Lever(
            key="spc",
            name="SPC on Forming and Welding",
            category="Quality",
            description="Control charts, capability study and gauge calibration cut scrap by 35%.",
            apply=_scale_scrap(0.65),
            capex_eur=14_000,
            lifetime_years=5,
            opex_eur_per_year=6_000,
            note="Scrap wastes the steel blank and the energy already spent on it.",
        ),
        Lever(
            key="pdm",
            name="Predictive maintenance",
            category="Reliability",
            description="Vibration and current monitoring: MTBF +25%, MTTR -40%.",
            apply=_predictive_maintenance(0.25, 0.40),
            capex_eur=38_000,
            lifetime_years=7,
            opex_eur_per_year=9_000,
            note="Fewer breakdowns free capacity; at a fixed order book the line runs fewer hours.",
        ),
        Lever(
            key="standby",
            name="Automatic standby shutdown",
            category="Energy",
            description="Idle draw -60% and furnace standby fuel -35% through a shutdown policy.",
            apply=_standby_policy(0.60, 0.35),
            capex_eur=8_000,
            lifetime_years=5,
            opex_eur_per_year=0,
            note="Pure control-logic change, no process risk.",
        ),
        Lever(
            key="air",
            name="Compressed-air leak repair",
            category="Energy",
            description="Ultrasonic leak survey and repair removes 80% of the leak load.",
            apply=_fix_air_leaks(0.80),
            capex_eur=5_500,
            lifetime_years=4,
            opex_eur_per_year=1_200,
            note="The classic first move in any energy audit.",
        ),
        Lever(
            key="nesting",
            name="Nesting and blank optimisation",
            category="Material",
            description="CAM nesting cuts the blank from 7.6 kg to 7.15 kg per part.",
            apply=_better_nesting(7.15),
            capex_eur=12_000,
            lifetime_years=5,
            opex_eur_per_year=2_500,
            note="Material carries most of the footprint, so grams matter more than kilowatts.",
        ),
        Lever(
            key="solar_linked",
            name="Rooftop solar, direct technical link",
            category="Electricity",
            description="Behind-the-meter array covering 30% of consumption, with a provable link.",
            apply=_onsite_solar(0.30),
            capex_eur=82_000,
            lifetime_years=20,
            opex_eur_per_year=4_500,
            cbam_recognised=True,
            note=(
                "Sized from the model, not guessed: 30% of about 530 MWh is some "
                "160 MWh a year, which needs roughly 110 kWp at a tropical yield "
                "near 1,450 kWh/kWp, costed at about EUR 700/kWp installed."
            ),
        ),
        Lever(
            key="solar_unbundled",
            name="Unbundled renewable certificates",
            category="Electricity",
            description="The same 30% of consumption covered by buying certificates instead.",
            apply=_market_based_claim(0.30),
            capex_eur=0,
            lifetime_years=1,
            opex_eur_per_year=1_050,
            cbam_recognised=False,
            physical=False,
            note=(
                "Shown for contrast. It lowers a market-based scope 2 number and "
                "nothing else: the same grid electricity is still bought, so there "
                "is no energy saving, and CBAM falls back to the country grid "
                "factor, so the bill does not move either."
            ),
        ),
        Lever(
            key="eaf_coil",
            name="Scrap-based coil instead of blast-furnace coil",
            category="Supply chain",
            description="Switch the precursor to an electric-arc-furnace route at a price premium.",
            apply=_switch_precursor(),
            capex_eur=0,
            lifetime_years=1,
            opex_eur_per_year=0,
            note="Needs a verified precursor declaration from the supplier, which is the hard part.",
        ),
    ]


# ------------------------------------------------------------- curve & stack ---
def marginal_abatement_curve(
    results: Sequence[LeverResult],
    with_cbam: bool = False,
    physical_only: bool = True,
) -> list[LeverResult]:
    """Sort levers cheapest-first, which is what makes the curve a curve.

    Certificate purchases are left out by default: putting a reporting
    instrument on the same axis as a physical change would overstate what the
    plant has actually abated.
    """
    key = (
        (lambda r: r.cost_per_t_co2_with_cbam_eur)
        if with_cbam
        else (lambda r: r.cost_per_t_co2_eur)
    )
    kept = [
        r
        for r in results
        if r.abatement_t_co2 > 0 and (r.lever.physical or not physical_only)
    ]
    return sorted(kept, key=key)


def evaluate_all(
    scenario: Scenario,
    levers: Sequence[Lever] | None = None,
    *,
    year: int | None = None,
    basis: str = cbam_mod.ACTUAL,
) -> list[LeverResult]:
    baseline = run_plant(scenario)
    levers = default_levers() if levers is None else list(levers)
    return [
        evaluate_lever(lever, scenario, baseline, year=year, basis=basis)
        for lever in levers
    ]


def stacked_scenario(
    scenario: Scenario, levers: Sequence[Lever]
) -> Scenario:
    """Apply several levers one after another."""
    out = scenario
    for lever in levers:
        out = lever.apply(out)
    return out


def interaction_gap(
    scenario: Scenario, levers: Sequence[Lever]
) -> dict[str, float]:
    """How much the levers overlap when installed together.

    Adding single-lever abatements double-counts: cutting scrap and cutting
    idle power both reduce the same kilowatt-hours.  This reports the sum of
    the individual effects, the effect of installing all of them, and the gap.
    """
    baseline = run_plant(scenario)
    individual = sum(
        max(0.0, r.abatement_t_co2)
        for r in evaluate_all(scenario, levers)
        if r.lever.physical
    )
    combined_scenario = match_output(stacked_scenario(scenario, levers), baseline.output_t)
    combined = run_plant(combined_scenario)
    joint = baseline.total_t_co2 - combined.total_t_co2
    return {
        "sum_of_individual_t": individual,
        "combined_t": joint,
        "gap_t": individual - joint,
        "gap_share": (individual - joint) / individual if individual > 0 else 0.0,
        "combined_see": combined.see_total,
        "baseline_see": baseline.see_total,
    }
