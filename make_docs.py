"""Render every README figure to ``docs/`` as a PNG.

Run after ``experiments.py``: the figures read the CSV files so a number can
never differ between the README, the app and the carousel.

Plotly 6 needs a Chrome install to export images; this project pins
``plotly==5.24.1`` with ``kaleido==0.2.1``, which writes PNGs directly.
"""

from __future__ import annotations

import os

import pandas as pd

import cbam as cbam_mod
import charts
import theme
from config import load_scenario
from plant import run_plant

DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

WIDTH, HEIGHT, SCALE = 1120, 620, 2


def _read(name: str) -> pd.DataFrame:
    return pd.read_csv(os.path.join(RESULTS_DIR, name))


def build_figures():
    scenario = load_scenario()
    result = run_plant(scenario)
    declaration = cbam_mod.declare(
        result, scenario, recognise_actual_electricity=True
    )
    return {
        "fig_carbon_waterfall": charts.carbon_waterfall(
            result.carbon_loss_t_co2(scenario.factors), result.good_parts
        ),
        "fig_station_time": charts.station_time(result.stations),
        "fig_scope_split": charts.scope_split(declaration),
        "fig_phase_in": charts.phase_in(
            _read("phase_in.csv").to_dict("records"),
            see=declaration.see_declared,
            benchmark=declaration.benchmark,
        ),
        "fig_trajectory": charts.trajectory(_read("trajectory.csv")),
        "fig_basis_comparison": charts.basis_comparison(_read("basis_comparison.csv")),
        "fig_de_minimis": charts.de_minimis_cliff(
            _read("de_minimis.csv"), scenario.cbam.de_minimis_tonnes_per_year
        ),
        "fig_origin_price": charts.origin_price(_read("origin_price.csv")),
        "fig_eaf_crossover": charts.eaf_crossover(_read("eaf_trajectory.csv")),
        "fig_macc": charts.macc(_read("macc.csv")),
        "fig_lever_dumbbell": charts.lever_dumbbell(_read("levers.csv")),
        "fig_abatement": charts.abatement_bars(_read("levers.csv")),
    }


def main() -> None:
    os.makedirs(DOCS_DIR, exist_ok=True)
    figures = build_figures()
    for name, figure in figures.items():
        path = os.path.join(DOCS_DIR, f"{name}.png")
        height = figure.layout.height or HEIGHT
        # In the app the figures sit on the page background, which is why they
        # are transparent there.  A PNG has to carry its own surface or the
        # light ink disappears against a light README background.
        figure.update_layout(
            paper_bgcolor=theme.GROUND, plot_bgcolor=theme.GROUND
        )
        figure.write_image(path, width=WIDTH, height=int(height), scale=SCALE)
        print(f"  wrote docs/{name}.png")
    print(f"{len(figures)} figures written to docs/")


if __name__ == "__main__":
    main()
