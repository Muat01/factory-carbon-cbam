"""The experiment runner must produce every file the README and figures read."""

from __future__ import annotations

import os

import pandas as pd
import pytest

import experiments
from config import load_scenario

EXPECTED = {
    "baseline.csv",
    "loss_attribution.csv",
    "monte_carlo.csv",
    "basis_comparison.csv",
    "phase_in.csv",
    "trajectory.csv",
    "de_minimis.csv",
    "origin_price.csv",
    "levers.csv",
    "macc.csv",
    "interaction.csv",
    "eaf_trajectory.csv",
}


@pytest.fixture()
def tables(tmp_path, monkeypatch):
    monkeypatch.setattr(experiments, "RESULTS_DIR", str(tmp_path))
    monkeypatch.setattr(experiments, "SEEDS", [1, 2, 3, 4, 5])
    return experiments.run_all(load_scenario()), tmp_path


def test_every_csv_is_written(tables):
    _, directory = tables
    assert set(os.listdir(directory)) == EXPECTED


def test_no_table_is_empty(tables):
    frames, _ = tables
    for name, frame in frames.items():
        assert len(frame) > 0, name
        assert not frame.isna().all().any(), name


def test_baseline_reports_the_headline_metrics(tables):
    frames, _ = tables
    metrics = set(frames["baseline"]["metric"])
    assert {"see_total", "kg_co2e_per_part", "oee", "total_emissions"} <= metrics


def test_loss_shares_add_up_to_one(tables):
    frames, _ = tables
    assert frames["loss_attribution"]["share_of_total"].sum() == pytest.approx(1.0)


def test_phase_in_starts_at_the_published_share(tables):
    frames, _ = tables
    first = frames["phase_in"].sort_values("year").iloc[0]
    assert first["headline_payable_share"] == pytest.approx(0.025)
    assert first["liable_share_at_benchmark"] == pytest.approx(0.025)


def test_trajectory_holds_three_price_paths(tables):
    frames, _ = tables
    assert set(frames["trajectory"]["ets_path"]) == {
        "flat_90",
        "growth_6pc",
        "growth_10pc",
    }


def test_de_minimis_sweep_crosses_the_threshold(tables):
    frames, _ = tables
    frame = frames["de_minimis"]
    assert frame["exempt"].any()
    assert (~frame["exempt"]).any()
    last_exempt = frame[frame["exempt"]]["eu_mass_t"].max()
    assert last_exempt <= 50.0


def test_macc_has_both_views_in_the_same_order_by_cost(tables):
    frames, _ = tables
    frame = frames["macc"]
    assert set(frame["view"]) == {"engineering_only", "with_cbam"}
    for view in frame["view"].unique():
        costs = list(frame[frame["view"] == view]["cost_per_t_co2_eur"])
        assert costs == sorted(costs)


def test_eaf_trajectory_shows_a_zero_bill_then_a_bill(tables):
    frames, _ = tables
    frame = frames["eaf_trajectory"]
    assert frame["eaf_bill_is_zero"].any()
    assert (~frame["eaf_bill_is_zero"]).any()
    assert (frame["saving_eur"] > 0).all()


def test_monte_carlo_reports_a_confidence_interval(tables):
    frames, _ = tables
    frame = frames["monte_carlo"]
    assert (frame["ci95_half_width"] >= 0).all()
    assert (frame["min"] <= frame["mean"]).all()
    assert (frame["max"] >= frame["mean"]).all()


def test_main_runs_end_to_end(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(experiments, "RESULTS_DIR", str(tmp_path))
    monkeypatch.setattr(experiments, "SEEDS", [1, 2, 3])
    experiments.main()
    printed = capsys.readouterr().out
    assert "Simulated data" in printed
    assert "CBAM" in printed
    assert len(os.listdir(tmp_path)) == len(EXPECTED)


def test_shipped_results_match_a_fresh_run():
    """The CSVs committed to the repo must come from the committed code."""
    shipped = os.path.join(os.path.dirname(experiments.__file__), "results", "baseline.csv")
    if not os.path.exists(shipped):
        pytest.skip("results/ has not been generated in this checkout")
    from plant import run_plant

    stored = pd.read_csv(shipped).set_index("metric")["value"]
    result = run_plant(load_scenario())
    assert float(stored["see_total"]) == pytest.approx(result.see_total, rel=1e-6)
    assert float(stored["output"]) == pytest.approx(result.output_t, rel=1e-6)
