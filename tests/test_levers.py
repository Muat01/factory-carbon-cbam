"""Tests for the abatement levers and the marginal abatement cost curve."""

from __future__ import annotations

from dataclasses import replace

import pytest

import levers as levers_mod
from config import load_scenario
from levers import (
    Lever,
    capital_recovery_factor,
    default_levers,
    evaluate_all,
    evaluate_lever,
    interaction_gap,
    marginal_abatement_curve,
    match_output,
)
from plant import run_plant


@pytest.fixture()
def scenario():
    return load_scenario()


@pytest.fixture()
def baseline(scenario):
    return run_plant(scenario)


@pytest.fixture()
def lever_results(scenario):
    return evaluate_all(scenario)


def by_key(results, key):
    return next(r for r in results if r.lever.key == key)


# ----------------------------------------------------------------- finance ---
def test_capital_recovery_factor_matches_the_annuity_formula():
    assert capital_recovery_factor(0.10, 10) == pytest.approx(0.1627454, rel=1e-6)
    assert capital_recovery_factor(0.0, 5) == pytest.approx(0.2)


def test_capital_recovery_factor_rejects_a_zero_lifetime():
    with pytest.raises(ValueError, match="lifetime"):
        capital_recovery_factor(0.1, 0)


def test_annualised_capex_is_capex_times_the_recovery_factor(scenario, lever_results):
    item = by_key(lever_results, "solar_linked")
    expected = item.lever.capex_eur * capital_recovery_factor(
        scenario.prices.discount_rate, item.lever.lifetime_years
    )
    assert item.annualised_capex_eur == pytest.approx(expected)


# ------------------------------------------------------- constant order book ---
def test_match_output_hits_the_target_exactly(scenario, baseline):
    target = baseline.output_t * 0.8
    matched = run_plant(match_output(scenario, target))
    assert matched.output_t == pytest.approx(target, rel=1e-9)


def test_every_lever_is_judged_at_the_same_output(lever_results, baseline):
    for item in lever_results:
        assert item.output_t == pytest.approx(baseline.output_t, rel=1e-9)


def test_a_capacity_lever_reports_spare_capacity(lever_results):
    assert by_key(lever_results, "pdm").spare_capacity_t > 0


def test_a_lever_that_changes_nothing_abates_nothing(scenario, baseline):
    null = Lever(
        key="null",
        name="No change",
        category="Test",
        description="",
        apply=lambda s: s,
        capex_eur=0.0,
        lifetime_years=1,
        opex_eur_per_year=0.0,
    )
    item = evaluate_lever(null, scenario, baseline)
    assert item.abatement_t_co2 == pytest.approx(0.0, abs=1e-9)
    assert item.cbam_saving_eur == pytest.approx(0.0, abs=1e-6)
    assert item.cost_per_t_co2_eur == float("inf")
    assert item.payback_years == float("inf")


# -------------------------------------------------------------- behaviour ---
def test_cutting_scrap_abates_and_pays(lever_results):
    item = by_key(lever_results, "spc")
    assert item.abatement_t_co2 > 0
    assert item.profitable_without_cbam
    assert item.payback_years < 3


def test_switching_precursor_is_the_biggest_lever(lever_results):
    biggest = max(lever_results, key=lambda r: r.abatement_t_co2)
    assert biggest.lever.key == "eaf_coil"


def test_a_physical_array_cuts_the_bill_but_certificates_do_not(lever_results):
    solar = by_key(lever_results, "solar_linked")
    paper = by_key(lever_results, "solar_unbundled")
    assert solar.abatement_t_co2 == pytest.approx(paper.abatement_t_co2, rel=1e-9)
    assert solar.cbam_saving_eur > 0
    assert paper.cbam_saving_eur == pytest.approx(0.0, abs=1e-6)


def test_only_the_physical_array_saves_electricity(lever_results):
    solar = by_key(lever_results, "solar_linked")
    paper = by_key(lever_results, "solar_unbundled")
    assert solar.delta_operating_eur < paper.delta_operating_eur


def test_the_carbon_price_flips_at_least_one_lever(lever_results):
    flipped = [r for r in lever_results if r.flipped_by_cbam]
    assert flipped
    for item in flipped:
        assert item.net_cost_eur > 0 > item.net_cost_with_cbam_eur


def test_a_higher_carbon_price_never_makes_a_lever_worse(scenario):
    cheap = evaluate_all(replace(scenario, prices=replace(scenario.prices, ets_price_eur_per_t=40.0)))
    dear = evaluate_all(replace(scenario, prices=replace(scenario.prices, ets_price_eur_per_t=160.0)))
    for low, high in zip(cheap, dear):
        assert high.cbam_saving_eur >= low.cbam_saving_eur - 1e-6
        assert high.net_cost_with_cbam_eur <= low.net_cost_with_cbam_eur + 1e-6


def test_cbam_never_makes_the_business_case_worse(lever_results):
    for item in lever_results:
        assert item.net_cost_with_cbam_eur <= item.net_cost_eur + 1e-6


# ------------------------------------------------------------------ curve ---
def test_the_curve_is_sorted_cheapest_first(lever_results):
    costs = [r.cost_per_t_co2_eur for r in marginal_abatement_curve(lever_results)]
    assert costs == sorted(costs)


def test_the_curve_leaves_out_paper_instruments(lever_results):
    keys = [r.lever.key for r in marginal_abatement_curve(lever_results)]
    assert "solar_unbundled" not in keys
    assert "solar_unbundled" in [
        r.lever.key
        for r in marginal_abatement_curve(lever_results, physical_only=False)
    ]


def test_the_curve_only_holds_levers_that_abate(lever_results):
    assert all(r.abatement_t_co2 > 0 for r in marginal_abatement_curve(lever_results))


def test_adding_the_cbam_saving_lowers_the_whole_curve(lever_results):
    engineering = {
        r.lever.key: r.cost_per_t_co2_eur for r in marginal_abatement_curve(lever_results)
    }
    with_cbam = {
        r.lever.key: r.cost_per_t_co2_with_cbam_eur
        for r in marginal_abatement_curve(lever_results, with_cbam=True)
    }
    assert set(engineering) == set(with_cbam)
    for key in engineering:
        assert with_cbam[key] <= engineering[key] + 1e-9


# ------------------------------------------------------------ interaction ---
def test_levers_overlap_rather_than_add(scenario):
    shopfloor = [l for l in default_levers() if l.key in ("spc", "standby", "air", "nesting")]
    gap = interaction_gap(scenario, shopfloor)
    assert gap["combined_t"] > 0
    assert gap["gap_t"] >= -1e-6
    assert gap["combined_t"] <= gap["sum_of_individual_t"] + 1e-6
    assert gap["combined_see"] < gap["baseline_see"]


def test_stacking_levers_applies_all_of_them(scenario):
    shopfloor = [l for l in default_levers() if l.key in ("spc", "air")]
    stacked = levers_mod.stacked_scenario(scenario, shopfloor)
    assert stacked.plant.compressed_air_leak_kw < scenario.plant.compressed_air_leak_kw
    assert stacked.plant.stations[1].scrap_rate < scenario.plant.stations[1].scrap_rate


def test_the_lever_book_is_well_formed():
    levers = default_levers()
    assert len({l.key for l in levers}) == len(levers)
    for lever in levers:
        assert lever.name and lever.description and lever.category
        assert lever.capex_eur >= 0
        assert lever.lifetime_years >= 1
