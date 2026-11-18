"""Tests for the shop-floor carbon model.

The conservation identities are the important ones: if the loss attribution
did not sum exactly to the totals, every insight built on it would be wrong by
an unknown amount.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from config import Station, load_scenario
from plant import (
    LOSS_BUCKETS,
    _gamma_sample,
    mean_ci,
    monte_carlo,
    run_plant,
    sample_plant,
    yield_cascade,
)


@pytest.fixture()
def scenario():
    return load_scenario()


@pytest.fixture()
def result(scenario):
    return run_plant(scenario)


# ------------------------------------------------------------- conservation ---
def test_electricity_buckets_sum_to_total(result):
    assert sum(result.electricity_loss_mwh.values()) == pytest.approx(
        result.electricity_mwh, rel=1e-12
    )


def test_fuel_buckets_sum_to_total(result):
    assert sum(result.gas_loss_mwh.values()) == pytest.approx(
        result.gas_mwh_th, rel=1e-12
    )


def test_material_buckets_sum_to_steel_input(result):
    assert sum(result.material_loss_t.values()) == pytest.approx(
        result.input_steel_t, rel=1e-12
    )


def test_carbon_buckets_sum_to_total_emissions(scenario, result):
    buckets = result.carbon_loss_t_co2(scenario.factors)
    assert set(buckets) == set(LOSS_BUCKETS)
    assert sum(buckets.values()) == pytest.approx(result.total_t_co2, rel=1e-12)


def test_emissions_split_into_three_scopes(result):
    assert (
        result.direct_t_co2 + result.indirect_t_co2 + result.precursor_t_co2
        == pytest.approx(result.total_t_co2)
    )
    assert result.see_direct + result.see_indirect + result.see_precursor == (
        pytest.approx(result.see_total)
    )


def test_station_hours_fill_the_planned_time(result):
    planned = result.meta["planned_hours"]
    for station in result.stations:
        total = station.run_h + station.idle_h + station.down_h + station.changeover_h
        assert total == pytest.approx(planned, rel=1e-9)


# -------------------------------------------------------------------- OEE ---
def test_oee_identity_reproduces_output(scenario, result):
    """good parts == planned time x ideal rate x OEE, exactly."""
    bottleneck = next(
        s for s in scenario.plant.stations if s.name == result.bottleneck
    )
    ideal_rate = 3600.0 / bottleneck.cycle_time_s
    predicted = scenario.plant.planned_hours_per_year * ideal_rate * result.oee
    assert predicted == pytest.approx(result.good_parts, rel=1e-9)


def test_oee_components_are_shares(result):
    for value in (result.availability, result.performance, result.quality):
        assert 0.0 < value <= 1.0


# ------------------------------------------------------------------ yields ---
def test_yield_cascade_is_reverse_cumulative(scenario):
    survive = yield_cascade(scenario.plant)
    rates = [s.scrap_rate for s in scenario.plant.stations]
    assert survive[-1] == pytest.approx(1.0 - rates[-1])
    expected_first = np.prod([1.0 - r for r in rates])
    assert survive[0] == pytest.approx(expected_first)
    assert all(survive[i] <= survive[i + 1] for i in range(len(survive) - 1))


def test_starts_exceed_good_parts(result):
    assert result.starts > result.good_parts


def test_no_scrap_means_no_rejected_steel(scenario):
    clean = replace(
        scenario, plant=scenario.plant.map_stations(lambda s: replace(s, scrap_rate=0.0))
    )
    out = run_plant(clean)
    assert out.material_loss_t["scrap"] == pytest.approx(0.0)
    assert out.starts == pytest.approx(out.good_parts)
    assert out.quality == pytest.approx(1.0)


def test_more_scrap_raises_the_footprint(scenario, result):
    worse = replace(
        scenario,
        plant=scenario.plant.map_stations(
            lambda s: replace(s, scrap_rate=min(0.9, s.scrap_rate * 2.0))
        ),
    )
    assert run_plant(worse).see_total > result.see_total


# ------------------------------------------------------------- bottleneck ---
def test_slowest_station_becomes_the_bottleneck(scenario):
    slowed = scenario.plant.with_station(0, cycle_time_s=600.0)
    out = run_plant(replace(scenario, plant=slowed))
    assert out.bottleneck == slowed.stations[0].name
    assert out.stations[0].is_bottleneck


def test_bottleneck_has_the_least_idle_time(result):
    bottleneck = next(s for s in result.stations if s.is_bottleneck)
    assert bottleneck.idle_h == pytest.approx(0.0, abs=1e-6)


# ------------------------------------------------------- output linearity ---
def test_output_is_linear_in_operating_days(scenario, result):
    """match_output relies on this, so it is worth asserting directly."""
    halved = replace(
        scenario,
        plant=replace(scenario.plant, days_per_year=scenario.plant.days_per_year / 2),
    )
    assert run_plant(halved).output_t == pytest.approx(result.output_t / 2, rel=1e-9)


def test_changeovers_cannot_eat_the_whole_year(scenario):
    greedy = replace(scenario.plant, setup_time_min=10_000.0)
    with pytest.raises(ValueError, match="changeovers"):
        run_plant(replace(scenario, plant=greedy))


# ------------------------------------------------------------- validation ---
@pytest.mark.parametrize(
    "field, value",
    [
        ("cycle_time_s", 0.0),
        ("performance", 0.0),
        ("performance", 1.4),
        ("scrap_rate", 1.0),
        ("scrap_rate", -0.1),
        ("mtbf_h", 0.0),
        ("mttr_h", -1.0),
    ],
)
def test_station_rejects_impossible_parameters(scenario, field, value):
    station = scenario.plant.stations[0]
    with pytest.raises(ValueError):
        replace(station, **{field: value})


def test_plant_rejects_input_lighter_than_the_part(scenario):
    with pytest.raises(ValueError, match="input mass"):
        replace(scenario.plant, input_mass_kg=scenario.plant.part_mass_kg - 1.0)


def test_plant_rejects_impossible_export_share(scenario):
    with pytest.raises(ValueError, match="eu_export_share"):
        replace(scenario.plant, eu_export_share=1.4)


def test_station_derived_properties():
    station = Station(
        name="t",
        cycle_time_s=36.0,
        performance=0.5,
        mtbf_h=90.0,
        mttr_h=10.0,
        scrap_rate=0.0,
        power_run_kw=1.0,
        power_idle_kw=0.0,
        power_down_kw=0.0,
    )
    assert station.availability == pytest.approx(0.9)
    assert station.capacity_parts_per_hour == pytest.approx(50.0)


# --------------------------------------------------------------- sampling ---
def test_gamma_sampler_survives_zero_variability():
    """A coefficient of variation of zero used to crash the sampler."""
    rng = np.random.default_rng(0)
    assert _gamma_sample(rng, 120.0, 0.0) == 120.0
    assert _gamma_sample(rng, 120.0, -1.0) == 120.0
    assert _gamma_sample(rng, 0.0, 0.3) == 0.0


def test_gamma_sampler_has_the_requested_mean():
    rng = np.random.default_rng(7)
    draws = [_gamma_sample(rng, 50.0, 0.3) for _ in range(20_000)]
    assert np.mean(draws) == pytest.approx(50.0, rel=0.02)


def test_sampling_with_zero_cv_leaves_the_plant_alone(scenario):
    rng = np.random.default_rng(1)
    sampled = sample_plant(scenario, rng, cv=0.0)
    for before, after in zip(scenario.plant.stations, sampled.plant.stations):
        assert before.mtbf_h == pytest.approx(after.mtbf_h)
        assert before.scrap_rate == pytest.approx(after.scrap_rate)


def test_monte_carlo_is_reproducible(scenario):
    first = monte_carlo(scenario, [1, 2, 3])
    second = monte_carlo(scenario, [1, 2, 3])
    assert [r.see_total for r in first] == [r.see_total for r in second]


def test_monte_carlo_spread_is_small_relative_to_the_mean(scenario):
    results = monte_carlo(scenario, list(range(1, 21)))
    mean, half = mean_ci([r.see_total for r in results])
    assert half < 0.05 * mean


def test_mean_ci_handles_a_single_value():
    assert mean_ci([3.0]) == (3.0, 0.0)


def test_avoidable_share_is_a_fraction(scenario, result):
    share = result.avoidable_share(scenario.factors)
    assert 0.0 < share < 1.0
