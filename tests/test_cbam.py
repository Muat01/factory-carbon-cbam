"""Tests for the CBAM liability chain."""

from __future__ import annotations

from dataclasses import replace

import pytest

import cbam as cbam_mod
from cbam import ACTUAL, DEFAULT, QUARTERLY_HOLDING_SHARE, declare
from config import load_scenario
from plant import run_plant


@pytest.fixture()
def scenario():
    return load_scenario()


@pytest.fixture()
def result(scenario):
    return run_plant(scenario)


@pytest.fixture()
def declaration(result, scenario):
    return declare(result, scenario, recognise_actual_electricity=True)


# ------------------------------------------------------ regulatory dials ---
def test_payable_share_follows_the_free_allocation_phase_out(scenario):
    expected = {
        2026: 0.025,
        2027: 0.05,
        2028: 0.10,
        2029: 0.225,
        2030: 0.485,
        2031: 0.61,
        2032: 0.735,
        2033: 0.86,
        2034: 1.0,
    }
    for year, share in expected.items():
        assert scenario.cbam.payable_share(year) == pytest.approx(share)


def test_cbam_factor_clamps_outside_the_published_years(scenario):
    assert scenario.cbam.cbam_factor(2000) == scenario.cbam.cbam_factor(2026)
    assert scenario.cbam.cbam_factor(2099) == scenario.cbam.cbam_factor(2034)


def test_default_value_markup_schedule(scenario):
    assert scenario.cbam.default_value_markup(2026) == pytest.approx(0.10)
    assert scenario.cbam.default_value_markup(2027) == pytest.approx(0.20)
    assert scenario.cbam.default_value_markup(2028) == pytest.approx(0.30)
    assert scenario.cbam.default_value_markup(2034) == pytest.approx(0.30)


def test_unknown_route_raises(scenario):
    with pytest.raises(KeyError):
        scenario.cbam.benchmark("unobtanium")
    with pytest.raises(KeyError):
        scenario.cbam.default_value("unobtanium")


# -------------------------------------------------------------- the chain ---
def test_components_sum_to_the_declared_value(declaration):
    assert (
        declaration.see_direct + declaration.see_indirect + declaration.see_precursor
        == pytest.approx(declaration.see_declared)
    )


def test_free_allocation_follows_the_sefa_formula(scenario, declaration):
    expected_sefa = (
        declaration.cbam_factor
        * scenario.cbam.cross_sectoral_correction_factor
        * declaration.benchmark
    )
    assert declaration.sefa == pytest.approx(expected_sefa)
    assert declaration.free_allocation_t == pytest.approx(
        declaration.mass_t * expected_sefa
    )


def test_liable_emissions_are_gross_less_free_allocation(declaration):
    assert declaration.liable_emissions_t == pytest.approx(
        declaration.gross_emissions_t - declaration.free_allocation_t
    )


def test_cost_is_certificates_times_the_ets_price(declaration):
    assert declaration.gross_cost_eur == pytest.approx(
        declaration.certificates * declaration.ets_price_eur_per_t
    )


def test_clean_plant_owes_nothing_and_is_never_negative(scenario, result):
    clean = replace(
        scenario,
        factors=replace(scenario.factors, ef_precursor_t_co2_per_t=0.01),
    )
    item = declare(run_plant(clean), clean, recognise_actual_electricity=True)
    assert item.see_declared < item.sefa
    assert item.liable_emissions_t == pytest.approx(0.0)
    assert item.net_cost_eur == pytest.approx(0.0)


def test_free_allocation_never_exceeds_gross_emissions(scenario):
    clean = replace(
        scenario, factors=replace(scenario.factors, ef_precursor_t_co2_per_t=0.01)
    )
    item = declare(run_plant(clean), clean, recognise_actual_electricity=True)
    assert item.free_allocation_t <= item.gross_emissions_t + 1e-9


def test_quarterly_holding_is_half_the_liability(declaration):
    assert declaration.quarterly_holding_t == pytest.approx(
        declaration.liable_emissions_t * QUARTERLY_HOLDING_SHARE
    )
    assert QUARTERLY_HOLDING_SHARE == 0.50


def test_invalid_basis_is_rejected(result, scenario):
    with pytest.raises(ValueError, match="basis"):
        declare(result, scenario, basis="guesswork")


# ------------------------------------------------------------- de minimis ---
def test_small_importer_is_exempt(result, scenario):
    item = declare(result, scenario, mass_t=40.0)
    assert item.exempt
    assert item.gross_emissions_t == 0.0
    assert item.net_cost_eur == 0.0
    assert item.de_minimis_headroom_t == pytest.approx(10.0)


def test_one_tonne_over_the_threshold_owes_the_full_bill(result, scenario):
    threshold = scenario.cbam.de_minimis_tonnes_per_year
    under = declare(result, scenario, mass_t=threshold)
    over = declare(result, scenario, mass_t=threshold + 1.0)
    assert under.exempt and under.net_cost_eur == 0.0
    assert not over.exempt
    assert over.net_cost_eur > 0.0
    # The bill applies to everything imported, not only the excess tonne.
    assert over.gross_emissions_t == pytest.approx(
        (threshold + 1.0) * over.see_declared
    )


# ------------------------------------------------- actual vs default basis ---
def test_default_values_carry_the_mark_up(result, scenario):
    item = declare(result, scenario, basis=DEFAULT, year=2027)
    raw = scenario.cbam.default_value(scenario.plant.production_route)
    assert item.see_declared == pytest.approx(raw * 1.20)


def test_verified_values_beat_default_values_here(result, scenario):
    comparison = cbam_mod.basis_comparison(
        result, scenario, recognise_actual_electricity=True
    )
    assert comparison["see_actual"] < comparison["see_default"]
    assert comparison["saving_eur"] > 0
    assert 0.0 < comparison["saving_share"] < 1.0


# ----------------------------------------------------------- electricity ---
def test_without_a_direct_link_the_country_factor_applies(scenario, result):
    greener = replace(
        scenario, factors=replace(scenario.factors, ef_grid_t_co2_per_mwh=0.1)
    )
    greener_result = run_plant(greener)
    recognised = declare(
        greener_result, greener, recognise_actual_electricity=True
    )
    fallback = declare(
        greener_result, greener, recognise_actual_electricity=False
    )
    assert recognised.see_indirect < fallback.see_indirect
    assert fallback.electricity_basis == "country_default"
    assert recognised.electricity_basis == "actual"
    assert fallback.net_cost_eur > recognised.net_cost_eur


def test_country_default_matches_the_published_factor(scenario, result):
    item = declare(result, scenario, recognise_actual_electricity=False)
    expected = (
        result.electricity_mwh
        * scenario.factors.ef_grid_country_default_t_co2_per_mwh
        / result.output_t
    )
    assert item.see_indirect == pytest.approx(expected)


# --------------------------------------------------------- origin pricing ---
def test_no_coverage_means_no_credit(declaration):
    assert declaration.origin_credit_eur == pytest.approx(0.0)


def test_origin_credit_scales_with_coverage_and_price(scenario, result):
    priced = replace(
        scenario,
        prices=replace(
            scenario.prices,
            origin_carbon_price_eur_per_t=20.0,
            origin_carbon_price_coverage=0.5,
        ),
    )
    item = declare(result, priced, recognise_actual_electricity=True)
    expected = item.mass_t * item.see_declared * 0.5 * 20.0
    assert item.origin_credit_eur == pytest.approx(expected)
    assert item.net_cost_eur == pytest.approx(item.gross_cost_eur - expected)


def test_origin_credit_cannot_make_the_bill_negative(scenario, result):
    priced = replace(
        scenario,
        prices=replace(
            scenario.prices,
            origin_carbon_price_eur_per_t=5_000.0,
            origin_carbon_price_coverage=1.0,
        ),
    )
    item = declare(result, priced, recognise_actual_electricity=True)
    assert item.net_cost_eur == pytest.approx(0.0)
    assert item.origin_credit_eur == pytest.approx(item.gross_cost_eur)


# -------------------------------------------------------------- phase in ---
def test_a_plant_at_the_benchmark_pays_the_headline_share(scenario):
    benchmark = scenario.cbam.benchmark(scenario.plant.production_route)
    rows = cbam_mod.phase_in_exposure(benchmark, benchmark, scenario.cbam)
    for row in rows:
        assert row["liable_share_of_own_emissions"] == pytest.approx(
            row["headline_payable_share"]
        )


def test_a_dirty_plant_pays_more_than_the_headline_share(scenario, declaration):
    rows = cbam_mod.phase_in_exposure(
        declaration.see_declared, declaration.benchmark, scenario.cbam
    )
    first = rows[0]
    assert declaration.see_declared > declaration.benchmark
    assert first["liable_share_of_own_emissions"] > first["headline_payable_share"]
    assert rows[-1]["liable_share_of_own_emissions"] == pytest.approx(1.0)


def test_a_clean_plant_owes_nothing_early_on(scenario):
    benchmark = scenario.cbam.benchmark(scenario.plant.production_route)
    rows = cbam_mod.phase_in_exposure(benchmark * 0.5, benchmark, scenario.cbam)
    assert rows[0]["liable_see"] == pytest.approx(0.0)


# ------------------------------------------------------------ trajectory ---
def test_trajectory_covers_every_published_year(result, scenario):
    items = cbam_mod.trajectory(result, scenario, recognise_actual_electricity=True)
    assert [d.year for d in items] == scenario.cbam.years


def test_the_bill_rises_across_the_phase_out(result, scenario):
    items = cbam_mod.trajectory(result, scenario, recognise_actual_electricity=True)
    costs = [d.net_cost_eur for d in items]
    assert costs == sorted(costs)
    assert costs[-1] > costs[0]


def test_ets_price_path_compounds_from_the_base_year():
    path = cbam_mod.ets_price_path(100.0, [2026, 2027, 2028], 0.10)
    assert path[2026] == pytest.approx(100.0)
    assert path[2027] == pytest.approx(110.0)
    assert path[2028] == pytest.approx(121.0)


def test_effective_rate_is_below_the_ets_price_while_free_allocation_lasts(
    declaration,
):
    assert 0 < declaration.effective_rate_eur_per_t_co2 < declaration.ets_price_eur_per_t
