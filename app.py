"""Factory Carbon to CBAM -- interactive what-if app.

Six pages: the story, the shop floor, the product footprint, the CBAM bill,
the abatement backlog, and the method behind all of it.  Every number is
recomputed live from the sidebar controls; nothing on screen is hard-coded.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import streamlit as st

import cbam as cbam_mod
import charts
import levers as levers_mod
import theme
import ui
from config import SIMULATED_DATA_NOTICE, load_scenario
from plant import mean_ci, monte_carlo, run_plant

st.set_page_config(
    page_title="Factory Carbon to CBAM",
    page_icon="•",
    layout="wide",
    initial_sidebar_state="expanded",
)

PAGES = [
    "Overview",
    "Shop floor",
    "Product footprint",
    "CBAM bill",
    "Abatement",
    "Method and sources",
]


# -------------------------------------------------------------- computation ---
# Nothing here is cached on purpose.  A full pass -- the plant, twenty Monte
# Carlo replications and every lever -- takes about 20 ms, while a Streamlit
# cache keyed on an unhashable scenario object would happily serve a stale
# answer after a slider moves.  Correct beats clever at this size.
def _monte_carlo(scenario, seeds: tuple[int, ...], cv: float):
    results = monte_carlo(scenario, list(seeds), cv=cv)
    return {
        "see": mean_ci([r.see_total for r in results]),
        "kg_per_part": mean_ci([r.kg_co2e_per_part for r in results]),
        "output": mean_ci([r.output_t for r in results]),
        "n": len(results),
    }


def _levers(scenario, year: int, basis: str):
    results = levers_mod.evaluate_all(scenario, year=year, basis=basis)
    frame = pd.DataFrame(
        [
            {
                "key": r.lever.key,
                "name": r.lever.name,
                "category": r.lever.category,
                "physical": r.lever.physical,
                "abatement_t_co2": r.abatement_t_co2,
                "cost_per_t_co2_eur": r.cost_per_t_co2_eur,
                "cbam_saving_eur": r.cbam_saving_eur,
                "cost_per_t_co2_with_cbam_eur": r.cost_per_t_co2_with_cbam_eur,
                "net_cost_eur": r.net_cost_eur,
                "net_cost_with_cbam_eur": r.net_cost_with_cbam_eur,
                "payback_years": r.payback_years,
                "spare_capacity_t": r.spare_capacity_t,
                "flipped_by_cbam": r.flipped_by_cbam,
            }
            for r in results
        ]
    )
    curves = []
    for with_cbam in (False, True):
        cumulative = 0.0
        for item in levers_mod.marginal_abatement_curve(results, with_cbam=with_cbam):
            cost = (
                item.cost_per_t_co2_with_cbam_eur
                if with_cbam
                else item.cost_per_t_co2_eur
            )
            curves.append(
                {
                    "view": "with_cbam" if with_cbam else "engineering_only",
                    "key": item.lever.key,
                    "name": item.lever.name,
                    "abatement_t_co2": item.abatement_t_co2,
                    "cumulative_start_t_co2": cumulative,
                    "cumulative_abatement_t_co2": cumulative + item.abatement_t_co2,
                    "cost_per_t_co2_eur": cost,
                }
            )
            cumulative += item.abatement_t_co2
    return frame, pd.DataFrame(curves), results


# ------------------------------------------------------------------ sidebar ---
def sidebar(base):
    st.sidebar.markdown("### Factory Carbon to CBAM")
    page = st.sidebar.radio(
        "Page", PAGES, label_visibility="collapsed", key="page"
    )
    st.sidebar.markdown("---")

    st.sidebar.markdown("**Regulatory year**")
    year = st.sidebar.select_slider(
        "Year",
        options=base.cbam.years,
        value=base.cbam.year,
        label_visibility="collapsed",
        key="year"
    )
    basis_label = st.sidebar.radio(
        "Basis of declaration",
        ["Verified actual values", "Published default values"],
        key="basis",
        help=(
            "Default values carry a regulatory mark-up of 10% in 2026, 20% in 2027 "
            "and 30% from 2028, which is what measuring your own emissions is worth."
        ),
    )
    basis = (
        cbam_mod.ACTUAL if basis_label.startswith("Verified") else cbam_mod.DEFAULT
    )
    ppa = st.sidebar.checkbox(
        "Electricity has a direct link or PPA",
        value=True,
        key="ppa",
        help=(
            "CBAM only accepts an electricity factor below the country default when a "
            "direct technical link or a qualifying power purchase agreement can be proven. "
            "Unticked, the declaration falls back to the country grid factor."
        ),
    )

    st.sidebar.markdown("**Prices and factors**")
    ets = st.sidebar.slider(
        "EU ETS price, EUR per t CO2",
        40.0,
        180.0,
        float(base.prices.ets_price_eur_per_t),
        5.0,
        key="ets",
    )
    grid = st.sidebar.slider(
        "Grid emission factor, t CO2 per MWh",
        0.05,
        1.20,
        float(base.factors.ef_grid_t_co2_per_mwh),
        0.05,
        key="grid",
    )
    precursor = st.sidebar.slider(
        "Precursor steel, t CO2 per t",
        0.3,
        3.0,
        float(base.factors.ef_precursor_t_co2_per_t),
        0.05,
        key="precursor",
    )
    export_share = st.sidebar.slider(
        "Share of output shipped to the EU",
        0.0,
        1.0,
        float(base.plant.eu_export_share),
        0.01,
        key="export_share",
    )

    st.sidebar.markdown("**Shop floor**")
    scrap_scale = st.sidebar.slider(
        "Scrap rates, relative to baseline", 0.0, 2.0, 1.0, 0.05, key="scrap_scale"
    )
    idle_scale = st.sidebar.slider(
        "Idle power, relative to baseline", 0.0, 2.0, 1.0, 0.05, key="idle_scale"
    )
    leak = st.sidebar.slider(
        "Compressed-air leak load, kW",
        0.0,
        25.0,
        float(base.plant.compressed_air_leak_kw),
        0.5,
        key="leak",
    )

    st.sidebar.markdown("---")
    st.sidebar.caption(SIMULATED_DATA_NOTICE)

    plant = replace(
        base.plant, eu_export_share=export_share, compressed_air_leak_kw=leak
    )
    plant = plant.map_stations(
        lambda s: replace(
            s,
            scrap_rate=min(0.95, s.scrap_rate * scrap_scale),
            power_idle_kw=s.power_idle_kw * idle_scale,
        )
    )
    scenario = replace(
        base,
        plant=plant,
        factors=replace(
            base.factors,
            ef_grid_t_co2_per_mwh=grid,
            ef_precursor_t_co2_per_t=precursor,
        ),
        prices=replace(base.prices, ets_price_eur_per_t=ets),
        cbam=replace(base.cbam, year=year),
    )
    return page, scenario, {"year": year, "basis": basis, "ppa": ppa}


# -------------------------------------------------------------------- pages ---
def page_overview(scenario, result, declaration, options) -> None:
    ui.badge("Simulated data")
    ui.kpi_row(
        [
            {"label": "Footprint", "value": f"{result.see_total:.2f}", "note": "t CO2e per tonne of product"},
            {"label": "Per part", "value": f"{result.kg_co2e_per_part:.1f} kg", "note": f"{result.good_parts:,.0f} parts a year"},
            {"label": "Not value adding", "value": f"{result.avoidable_share(scenario.factors):.0%}", "note": "scrap, offcut, idle, services"},
            {"label": f"{options['year']} CBAM bill", "value": ui.money(declaration.net_cost_eur), "note": f"on {declaration.mass_t:,.0f} t shipped to the EU"},
            {"label": "Per tonne shipped", "value": f"EUR {declaration.cost_per_t_goods:,.0f}", "note": f"ETS at EUR {declaration.ets_price_eur_per_t:,.0f}/t"},
        ]
    )
    ui.insight(ui.cbam_insight(declaration), tone="warn")

    left, right = st.columns([3, 2])
    with left:
        st.plotly_chart(
            charts.carbon_waterfall(
                result.carbon_loss_t_co2(scenario.factors), result.good_parts
            ),
            width="stretch",
        )
    with right:
        ui.card(
            "The chain this app models",
            "A simulated steel-bracket plant in Indonesia ships to the EU. The line model turns cycle times, breakdowns and scrap into energy and material; those become a product carbon footprint in the units CBAM uses; the footprint becomes a certificate bill; and the bill re-prices the plant's own improvement backlog.",
        )
        ui.card(
            "Why the losses matter twice",
            "A scrapped part wastes the steel in it and the energy already spent on it, and then it raises the carbon intensity of every part that does ship. Under a carbon border price the same loss is charged a third time, at the border.",
        )
    st.plotly_chart(charts.scope_split(declaration), width="stretch")
    ui.insight(ui.plant_insight(result, scenario.factors))


def page_shop_floor(scenario, result, declaration, options) -> None:
    ui.section("Where the planned hours go")
    ui.kpi_row(
        [
            {"label": "OEE", "value": f"{result.oee:.1%}", "note": f"A {result.availability:.1%} / P {result.performance:.1%} / Q {result.quality:.1%}"},
            {"label": "Bottleneck", "value": result.bottleneck, "note": "sets the line rate"},
            {"label": "Electricity", "value": f"{result.electricity_mwh:,.0f} MWh", "note": f"EUR {result.electricity_cost_eur:,.0f} a year"},
            {"label": "Fuel", "value": f"{result.gas_mwh_th:,.0f} MWh", "note": "thermal, stress-relief furnace"},
            {"label": "Material yield", "value": f"{result.meta['material_yield']:.1%}", "note": f"{result.input_steel_t:,.0f} t steel in"},
        ]
    )
    st.plotly_chart(charts.station_time(result.stations), width="stretch")

    ui.section("Carbon by loss category")
    losses = result.carbon_loss_t_co2(scenario.factors)
    frame = pd.DataFrame(
        [
            {
                "Loss": charts.BUCKET_LABELS[bucket],
                "Electricity, MWh": result.electricity_loss_mwh.get(bucket, 0.0),
                "Fuel, MWh th": result.gas_loss_mwh.get(bucket, 0.0),
                "Steel, t": result.material_loss_t.get(bucket, 0.0),
                "t CO2e": value,
                "Share": value / result.total_t_co2,
                "kg CO2e per part": value * 1000.0 / result.good_parts,
            }
            for bucket, value in losses.items()
        ]
    )
    st.dataframe(
        frame.style.format(
            {
                "Electricity, MWh": "{:,.1f}",
                "Fuel, MWh th": "{:,.1f}",
                "Steel, t": "{:,.1f}",
                "t CO2e": "{:,.1f}",
                "Share": "{:.1%}",
                "kg CO2e per part": "{:.2f}",
            }
        ),
        width="stretch",
        hide_index=True,
    )
    ui.insight(ui.plant_insight(result, scenario.factors))

    ui.section("Station detail")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Station": s.name,
                    "Processed parts": s.processed_parts,
                    "Running h": s.run_h,
                    "Idle and changeover h": s.idle_h + s.changeover_h,
                    "Breakdown h": s.down_h,
                    "Utilisation": s.utilisation,
                    "Electricity MWh": s.electricity_mwh,
                    "Fuel MWh th": s.gas_mwh_th,
                    "Bottleneck": "yes" if s.is_bottleneck else "",
                }
                for s in result.stations
            ]
        ).style.format(
            {
                "Processed parts": "{:,.0f}",
                "Running h": "{:,.0f}",
                "Idle and changeover h": "{:,.0f}",
                "Breakdown h": "{:,.0f}",
                "Utilisation": "{:.1%}",
                "Electricity MWh": "{:,.1f}",
                "Fuel MWh th": "{:,.1f}",
            }
        ),
        width="stretch",
        hide_index=True,
    )


def page_footprint(scenario, result, declaration, options) -> None:
    ui.section("Specific embedded emissions")
    ui.kpi_row(
        [
            {"label": "Direct", "value": f"{declaration.see_direct:.3f}", "note": "fuel burnt on site"},
            {"label": "Indirect", "value": f"{declaration.see_indirect:.3f}", "note": f"electricity, {declaration.electricity_basis.replace('_', ' ')}"},
            {"label": "Precursor", "value": f"{declaration.see_precursor:.3f}", "note": "steel coming in"},
            {"label": "Declared total", "value": f"{declaration.see_declared:.3f}", "note": "t CO2e per tonne of goods"},
            {"label": "Benchmark credit", "value": f"{declaration.sefa:.3f}", "note": f"CBAM factor {declaration.cbam_factor:.3f}"},
        ]
    )
    st.plotly_chart(charts.scope_split(declaration), width="stretch")

    if not options["ppa"]:
        ui.insight(
            "<b>No direct link or PPA, so the country grid factor applies.</b> Any on-site renewable generation still lowers the real footprint and the electricity bill, but the declared indirect emissions stay at the country default and the CBAM bill does not move.",
            tone="warn",
        )

    ui.section("How stable is the number")
    spread = _monte_carlo(scenario, tuple(range(1, 21)), 0.25)
    see_mean, see_half = spread["see"]
    part_mean, part_half = spread["kg_per_part"]
    ui.kpi_row(
        [
            {"label": "Footprint, mean", "value": f"{see_mean:.3f}", "note": f"95% CI +/- {see_half:.3f} t CO2e/t"},
            {"label": "Per part, mean", "value": f"{part_mean:.2f} kg", "note": f"95% CI +/- {part_half:.2f} kg"},
            {"label": "Replications", "value": f"{spread['n']}", "note": "seeds, 25% variation on MTBF, MTTR and scrap"},
        ]
    )
    ui.insight(
        f"Reliability and scrap vary from year to year, but the footprint does not move much: <b>{see_mean:.3f} +/- {see_half:.3f} t CO2e per tonne</b> across {spread['n']} replications. The footprint is dominated by the steel coming through the door, which no amount of good luck on the line can change."
    )

    ui.section("Verified values against default values")
    years = scenario.cbam.years
    rows = []
    for year in years:
        comparison = cbam_mod.basis_comparison(
            result, scenario, year=year, recognise_actual_electricity=options["ppa"]
        )
        comparison["year"] = year
        rows.append(comparison)
    frame = pd.DataFrame(rows)
    st.plotly_chart(charts.basis_comparison(frame), width="stretch")
    this_year = frame[frame["year"] == options["year"]].iloc[0]
    ui.insight(
        f"Measuring and verifying your own emissions is worth <b>{ui.money(this_year['saving_eur'])} in {options['year']}</b>, which is {this_year['saving_share']:.0%} of the bill a default-value declaration would carry. Default values are built from the highest available value across origins and then marked up, so they are designed to be worse than a well-run plant's reality."
    )


def page_cbam(scenario, result, declaration, options) -> None:
    ui.section(f"{options['year']} declaration")
    ui.kpi_row(
        [
            {"label": "Mass shipped", "value": f"{declaration.mass_t:,.0f} t", "note": f"de minimis {declaration.de_minimis_t:,.0f} t a year"},
            {"label": "Gross embedded", "value": f"{declaration.gross_emissions_t:,.0f} t", "note": "CO2e before any credit"},
            {"label": "Free allocation", "value": f"{declaration.free_allocation_t:,.0f} t", "note": f"SEFA {declaration.sefa:.2f} t/t"},
            {"label": "Certificates", "value": f"{declaration.certificates:,.0f}", "note": f"hold {declaration.quarterly_holding_t:,.0f} each quarter"},
            {"label": "Net cost", "value": ui.money(declaration.net_cost_eur), "note": f"EUR {declaration.effective_rate_eur_per_t_co2:,.0f} per t embedded"},
        ]
    )
    ui.insight(ui.cbam_insight(declaration), tone="warn")

    rows = cbam_mod.phase_in_exposure(
        declaration.see_declared, declaration.benchmark, scenario.cbam
    )
    st.plotly_chart(
        charts.phase_in(rows, see=declaration.see_declared, benchmark=declaration.benchmark),
        width="stretch",
    )

    ui.section("The bill over the phase-in")
    years = scenario.cbam.years
    paths = {
        "flat_90": {y: scenario.prices.ets_price_eur_per_t for y in years},
        "growth_6pc": cbam_mod.ets_price_path(scenario.prices.ets_price_eur_per_t, years, 0.06),
        "growth_10pc": cbam_mod.ets_price_path(scenario.prices.ets_price_eur_per_t, years, 0.10),
    }
    traj_rows = []
    for label, path in paths.items():
        for item in cbam_mod.trajectory(
            result,
            scenario,
            years,
            path,
            basis=options["basis"],
            recognise_actual_electricity=options["ppa"],
        ):
            traj_rows.append(
                {"ets_path": label, "year": item.year, "net_cost_eur": item.net_cost_eur}
            )
    st.plotly_chart(charts.trajectory(pd.DataFrame(traj_rows)), width="stretch")

    ui.section("The de minimis step")
    dm_rows = []
    for index in range(1, 101):
        share = index / 100
        mass = result.output_t * share
        item = cbam_mod.declare(
            result,
            scenario,
            basis=options["basis"],
            mass_t=mass,
            recognise_actual_electricity=options["ppa"],
        )
        dm_rows.append(
            {
                "eu_export_share": share,
                "eu_mass_t": mass,
                "exempt": item.exempt,
                "net_cost_eur": item.net_cost_eur,
            }
        )
    st.plotly_chart(
        charts.de_minimis_cliff(
            pd.DataFrame(dm_rows), scenario.cbam.de_minimis_tonnes_per_year
        ),
        width="stretch",
    )
    ui.insight(
        f"The threshold is a step, not a slope, and it belongs to the importer rather than to the exporter. Up to {scenario.cbam.de_minimis_tonnes_per_year:,.0f} t a year of CBAM goods there is no authorisation, no declaration and no certificate. Past it the obligation applies to everything, which is why a small exporter's route to market matters as much as its emissions."
    )


def page_abatement(scenario, result, declaration, options) -> None:
    frame, curve, results = _levers(scenario, options["year"], options["basis"])
    ui.section("The improvement backlog, priced twice")
    ui.insight(ui.lever_insight(results))
    st.plotly_chart(charts.lever_dumbbell(frame), width="stretch")
    st.plotly_chart(charts.macc(curve), width="stretch")
    st.plotly_chart(charts.abatement_bars(frame), width="stretch")

    display = frame.copy()
    display["payback_years"] = display["payback_years"].replace(float("inf"), pd.NA)
    display = display[
        [
            "name",
            "category",
            "abatement_t_co2",
            "cost_per_t_co2_eur",
            "cbam_saving_eur",
            "cost_per_t_co2_with_cbam_eur",
            "payback_years",
            "spare_capacity_t",
            "flipped_by_cbam",
        ]
    ].rename(
        columns={
            "name": "Lever",
            "category": "Category",
            "abatement_t_co2": "Abatement t CO2e",
            "cost_per_t_co2_eur": "EUR per t, engineering",
            "cbam_saving_eur": "CBAM saved EUR",
            "cost_per_t_co2_with_cbam_eur": "EUR per t, after CBAM",
            "payback_years": "Payback years",
            "spare_capacity_t": "Spare capacity t",
            "flipped_by_cbam": "Flipped by CBAM",
        }
    )
    st.dataframe(
        display.style.format(
            {
                "Abatement t CO2e": "{:,.1f}",
                "EUR per t, engineering": "{:,.1f}",
                "CBAM saved EUR": "{:,.0f}",
                "EUR per t, after CBAM": "{:,.1f}",
                "Payback years": "{:,.1f}",
                "Spare capacity t": "{:,.1f}",
            },
            na_rep="-",
        ),
        width="stretch",
        hide_index=True,
    )

    ui.section("Do they add up")
    shopfloor = [
        lever
        for lever in levers_mod.default_levers()
        if lever.key in ("spc", "pdm", "standby", "air", "nesting")
    ]
    gap = levers_mod.interaction_gap(scenario, shopfloor)
    ui.kpi_row(
        [
            {"label": "Sum of individual", "value": f"{gap['sum_of_individual_t']:,.0f} t", "note": "each lever against the baseline"},
            {"label": "All installed together", "value": f"{gap['combined_t']:,.0f} t", "note": "one run with every lever applied"},
            {"label": "Overlap", "value": f"{gap['gap_share']:.1%}", "note": "double counting if you just add them"},
            {"label": "Footprint after", "value": f"{gap['combined_see']:.3f}", "note": f"from {gap['baseline_see']:.3f} t CO2e/t"},
        ]
    )
    ui.insight(
        f"Adding single-lever savings overstates the result by <b>{gap['gap_share']:.1%}</b> here: cutting scrap and cutting idle draw partly chase the same kilowatt-hours. The overlap is small in this plant because most of the footprint sits in the steel, not in the line."
    )


def page_method(scenario, result, declaration, options) -> None:
    ui.section("What the model does")
    ui.bullets(
        "Layer 1, shop floor",
        [
            "Each station has an ideal cycle time, a performance factor for speed loss and minor stops, an availability from MTBF and MTTR, and a scrap rate.",
            "The yield cascade turns required good parts into the parts every upstream station must process; the station whose capacity yields the fewest good parts sets the line rate.",
            "Running hours split exactly into value-adding time, speed loss and scrap rework; the rest of the planned time splits into breakdown, idle and changeover. Each bucket carries its own power draw, so the energy attribution sums to the total with no residual.",
            "Buffers and blocking are deliberately out of scope. The discrete-event companion project covers those.",
        ],
    )
    ui.bullets(
        "Layer 2, product footprint and CBAM",
        [
            "Specific embedded emissions are direct fuel, indirect electricity and precursor steel, divided by tonnes of good product, which is the unit CBAM uses.",
            "Declarations use verified actual values or published default values; defaults carry a mark-up of 10% in 2026, 20% in 2027 and 30% from 2028.",
            "The free allocation adjustment is benchmark-based: SEFA = CBAM factor x cross-sectoral correction factor x benchmark. The CBAM factor is the share of free allocation still granted, 0.975 in 2026 falling to zero in 2034.",
            "Certificates are the gross embedded emissions less the free allocation, priced at the EU ETS average. A carbon price already paid at origin reduces the bill.",
            "An importer at or below 50 t of CBAM goods a year is outside the mechanism, hydrogen and electricity aside.",
        ],
    )
    ui.bullets(
        "Layer 3, abatement",
        [
            "Every lever is evaluated at the baseline order book. Output is linear in planned production time here, so a lever that frees capacity is compared after trimming operating days, which is what a plant would really do.",
            "Cost of abatement is capital recovery plus operating cost minus energy and material savings; the second figure subtracts the CBAM bill the lever avoids.",
            "Certificate purchases are kept off the abatement curve. They change a reported number, not a physical one.",
        ],
    )

    ui.section("Honest limitations")
    ui.bullets(
        "Read these before quoting any number",
        [
            "Every figure is simulated. The plant does not exist and no company data was used.",
            "The CBAM benchmarks and default values in data/parameters.json are illustrative placeholders derived from a stated rule, not the official values. Replace them with Commission Implementing Regulation (EU) 2025/2621 before any real use.",
            "The carbon-price-paid deduction is modelled as a monetary credit capped at the gross cost, which is simpler than the procedure in the implementing act.",
            "The line model is analytic. It has no buffers, no blocking and no queueing dynamics, so it will not reproduce a discrete-event simulation exactly.",
            "Lever effect sizes and capital costs are plausible engineering estimates, not quotations.",
            "Nothing here is legal or compliance advice.",
        ],
    )

    ui.section("Sources")
    ui.bullets(
        "Regulation and prices",
        [
            "Regulation (EU) 2023/956 establishing the Carbon Border Adjustment Mechanism, and the Omnibus I amendment that introduced the 50 t mass threshold and lowered the quarterly certificate holding requirement from 80% to 50%.",
            "Article 10a(1a) of Directive 2003/87/EC for the free allocation phase-out: 2.5% in 2026, 5% in 2027, 10% in 2028, 22.5% in 2029, 48.5% in 2030, 61% in 2031, 73.5% in 2032, 86% in 2033 and 100% in 2034.",
            "Commission Implementing Regulation (EU) 2025/2621 for default values and country grid factors, and the free allocation adjustment rules for SEFA and the FAA.",
            "Annex IV of the CBAM Regulation for when actual indirect emissions may be claimed: a direct technical link or a qualifying power purchase agreement.",
            "EUA December-2026 futures traded around EUR 90/t in November 2026; a Reuters analyst poll put the 2026 average at EUR 92.65/t and 2027 at EUR 107.29/t.",
            "IDXCarbon traded around IDR 67,000/t, roughly USD 4/t. Indonesia's carbon tax under Law 7/2021 is legislated but not yet enforced, so the origin-price deduction is modelled as a scenario.",
            "IPCC 2006 default emission factor for natural gas, 56.1 t CO2/TJ.",
        ],
    )

    ui.section("Origin carbon price, what it would be worth")
    rows = []
    for label, price in [
        ("Today, about EUR 4/t", scenario.prices.origin_carbon_price_eur_per_t),
        ("Ministry target, EUR 40/t", 40.0),
        ("EU parity, EUR 90/t", scenario.prices.ets_price_eur_per_t),
    ]:
        for coverage in (0.0, 0.25, 0.5, 0.75, 1.0):
            scen = replace(
                scenario,
                prices=replace(
                    scenario.prices,
                    origin_carbon_price_eur_per_t=price,
                    origin_carbon_price_coverage=coverage,
                ),
            )
            item = cbam_mod.declare(
                result,
                scen,
                basis=options["basis"],
                year=2030,
                recognise_actual_electricity=options["ppa"],
            )
            rows.append(
                {
                    "origin_price_label": {
                        "Today, about EUR 4/t": "idx_carbon_3.9",
                        "Ministry target, EUR 40/t": "target_40",
                        "EU parity, EUR 90/t": "eu_parity_90",
                    }[label],
                    "coverage": coverage,
                    "year": 2030,
                    "net_cost_eur": item.net_cost_eur,
                }
            )
    st.plotly_chart(charts.origin_price(pd.DataFrame(rows), year=2030), width="stretch")
    ui.insight(
        "A carbon price at home is deducted from the bill abroad, so the money can either be collected in Jakarta or paid in Brussels. At today's domestic price the deduction is close to noise; at the ministry's stated target it would take a large share of the bill off the table."
    )


# --------------------------------------------------------------------- main ---
def main() -> None:
    ui.inject_css()
    base = load_scenario()
    page, scenario, options = sidebar(base)

    result = run_plant(scenario)
    declaration = cbam_mod.declare(
        result,
        scenario,
        basis=options["basis"],
        year=options["year"],
        recognise_actual_electricity=options["ppa"],
    )

    ui.hero(
        "Factory Carbon to CBAM",
        f"{scenario.plant.name} - {scenario.plant.good}, CN {scenario.plant.cn_code}",
    )

    if page == "Overview":
        page_overview(scenario, result, declaration, options)
    elif page == "Shop floor":
        page_shop_floor(scenario, result, declaration, options)
    elif page == "Product footprint":
        page_footprint(scenario, result, declaration, options)
    elif page == "CBAM bill":
        page_cbam(scenario, result, declaration, options)
    elif page == "Abatement":
        page_abatement(scenario, result, declaration, options)
    else:
        page_method(scenario, result, declaration, options)

    ui.footer(
        SIMULATED_DATA_NOTICE
        + " Built by Muatasem Hadi. Not legal or compliance advice."
    )


if __name__ == "__main__":
    main()
