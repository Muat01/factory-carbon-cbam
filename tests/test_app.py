"""Headless tests for the Streamlit app.

``AppTest`` runs the script the way Streamlit would, so these catch the kind of
breakage unit tests never see: a widget key that moved, a dataframe column that
no longer exists, a figure that raises while rendering.
"""

from __future__ import annotations

import os

import pytest
from streamlit.testing.v1 import AppTest

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
PAGES = [
    "Overview",
    "Shop floor",
    "Product footprint",
    "CBAM bill",
    "Abatement",
    "Method and sources",
]
TIMEOUT = 90


def run(**state) -> AppTest:
    app = AppTest.from_file(APP, default_timeout=TIMEOUT)
    for key, value in state.items():
        app.session_state[key] = value
    app.run()
    return app


def test_the_app_starts_without_an_exception():
    app = run()
    assert not app.exception


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders(page):
    app = run(page=page)
    assert not app.exception, f"{page} raised"
    assert len(app.markdown) > 0


def test_the_sidebar_exposes_every_control():
    app = run()
    keys = set(app.session_state.keys())
    for key in (
        "page",
        "year",
        "basis",
        "ppa",
        "ets",
        "grid",
        "precursor",
        "export_share",
        "scrap_scale",
        "idle_scale",
        "leak",
    ):
        assert key in keys, key


def test_the_simulated_data_notice_is_always_on_screen():
    for page in PAGES:
        app = run(page=page)
        body = " ".join(m.value for m in app.markdown)
        assert "Simulated data" in body or "simulated" in body.lower()


def test_a_higher_carbon_price_shows_a_bigger_bill():
    cheap = run(page="Overview", ets=40.0)
    dear = run(page="Overview", ets=180.0)
    assert not cheap.exception and not dear.exception
    assert _overview_bill(dear) > _overview_bill(cheap)


def _overview_bill(app) -> float:
    """Pull the CBAM bill out of the rendered KPI row."""
    import re

    body = " ".join(m.value for m in app.markdown)
    matches = re.findall(r"CBAM bill</div><div class=\"mh-kpi-value\">EUR ([\d,]+)", body)
    assert matches, "no CBAM bill tile found"
    return float(matches[0].replace(",", ""))


def test_cutting_scrap_lowers_the_footprint_on_screen():
    import re

    def footprint(app) -> float:
        body = " ".join(m.value for m in app.markdown)
        found = re.findall(r"Footprint</div><div class=\"mh-kpi-value\">([\d.]+)", body)
        assert found
        return float(found[0])

    base = run(page="Overview", scrap_scale=1.0)
    clean = run(page="Overview", scrap_scale=0.0)
    assert footprint(clean) < footprint(base)


def test_a_small_exporter_is_told_it_is_exempt():
    app = run(page="CBAM bill", export_share=0.01)
    assert not app.exception
    body = " ".join(m.value for m in app.markdown)
    assert "Outside CBAM" in body


def test_dropping_the_ppa_claim_warns_about_the_country_factor():
    app = run(page="Product footprint", ppa=False, grid=0.2)
    assert not app.exception
    body = " ".join(m.value for m in app.markdown)
    assert "country grid factor" in body


def test_the_abatement_page_draws_its_table_and_charts():
    app = run(page="Abatement")
    assert not app.exception
    assert len(app.dataframe) >= 1
    frame = app.dataframe[0].value
    assert "Lever" in frame.columns
    assert len(frame) >= 5
