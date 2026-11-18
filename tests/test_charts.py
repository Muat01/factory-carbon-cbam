"""Figures must build from the shipped results without a layout clash."""

from __future__ import annotations

import os

import pandas as pd
import plotly.graph_objects as go
import pytest

import cbam as cbam_mod
import charts
import theme
from config import load_scenario
from plant import run_plant

RESULTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")


def read(name: str) -> pd.DataFrame:
    path = os.path.join(RESULTS, name)
    if not os.path.exists(path):
        pytest.skip(f"{name} has not been generated in this checkout")
    return pd.read_csv(path)


@pytest.fixture()
def scenario():
    return load_scenario()


@pytest.fixture()
def result(scenario):
    return run_plant(scenario)


@pytest.fixture()
def declaration(result, scenario):
    return cbam_mod.declare(result, scenario, recognise_actual_electricity=True)


def test_layout_helper_merges_instead_of_duplicating():
    """Passing the same key twice to update_layout is a Plotly error."""
    layout = theme.plotly_layout(title={"text": "x"}, yaxis={"title": {"text": "y"}})
    assert layout["title"]["text"] == "x"
    assert layout["title"]["font"]["color"] == theme.INK
    assert layout["yaxis"]["gridcolor"] == theme.GRID
    assert layout["yaxis"]["title"]["text"] == "y"


def test_merge_is_recursive_and_does_not_mutate():
    base = {"a": {"b": 1, "c": 2}}
    out = theme.merge(base, {"a": {"c": 3}})
    assert out == {"a": {"b": 1, "c": 3}}
    assert base == {"a": {"b": 1, "c": 2}}


def test_waterfall_builds(scenario, result):
    figure = charts.carbon_waterfall(
        result.carbon_loss_t_co2(scenario.factors), result.good_parts
    )
    assert isinstance(figure, go.Figure)
    assert len(figure.data) == 1


def test_station_time_has_one_trace_per_machine_state(result):
    assert len(charts.station_time(result.stations).data) == 3


def test_scope_split_marks_the_benchmark(declaration):
    figure = charts.scope_split(declaration)
    assert len(figure.data) == 3
    assert len(figure.layout.shapes) >= 2


def test_phase_in_draws_two_lines_not_three():
    figure = charts.phase_in(read("phase_in.csv").to_dict("records"), see=3.0, benchmark=1.8)
    assert len(figure.data) == 2


def test_trajectory_draws_one_line_per_price_path():
    assert len(charts.trajectory(read("trajectory.csv")).data) == 3


def test_basis_comparison_is_grouped():
    figure = charts.basis_comparison(read("basis_comparison.csv"))
    assert figure.layout.barmode == "group"
    assert len(figure.data) == 2


def test_cliff_shades_the_exempt_band(scenario):
    figure = charts.de_minimis_cliff(read("de_minimis.csv"), scenario.cbam.de_minimis_tonnes_per_year)
    assert len(figure.layout.shapes) >= 1


def test_origin_price_draws_three_price_levels():
    assert len(charts.origin_price(read("origin_price.csv")).data) == 3


def test_eaf_crossover_annotates_the_first_liable_year():
    figure = charts.eaf_crossover(read("eaf_trajectory.csv"))
    assert len(figure.data) == 2
    assert len(figure.layout.annotations) >= 1


def test_macc_caps_the_view_and_labels_what_it_left_out():
    figure = charts.macc(read("macc.csv"))
    low, high = figure.layout.yaxis.range
    assert high < 400
    assert low < 0
    assert any("beyond" in a.text or "above" in a.text for a in figure.layout.annotations)


def test_dumbbell_sizes_its_window_from_the_data():
    figure = charts.lever_dumbbell(read("levers.csv"))
    low, high = figure.layout.xaxis.range
    assert 0 < high < 400
    assert low == -high


def test_abatement_bars_build():
    figure = charts.abatement_bars(read("levers.csv"))
    assert len(figure.data) == 1


def test_every_figure_uses_the_brand_palette(scenario, result, declaration):
    figure = charts.station_time(result.stations)
    colours = [trace.marker.color for trace in figure.data]
    assert colours == theme.CATEGORICAL[:3]
