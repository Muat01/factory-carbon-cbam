"""Plotly figure builders.

Every figure the app shows and every PNG in ``docs/`` comes from this module,
so the Streamlit pages, the README and the LinkedIn carousel cannot drift apart.

Conventions, applied to all of them: one y-axis per figure, categorical hues
taken in the fixed brand order and never cycled, a 2px surface-coloured gap
between adjacent fills so stacked segments stay countable, thin marks over a
recessive grid, and a legend whenever there is more than one series.  The
five-hue categorical set passes the lightness-band, chroma, colour-vision
separation and contrast checks on both the dark and the light surface.
"""

from __future__ import annotations

from typing import Mapping, Sequence

import pandas as pd
import plotly.graph_objects as go

import theme

BUCKET_LABELS = {
    "value_adding": "Value adding",
    "performance": "Speed loss",
    "scrap": "Scrap",
    "offcut": "Offcut",
    "downtime": "Breakdowns",
    "idle": "Idle and changeover",
    "baseload": "Site services",
}

SCOPE_LABELS = {
    "direct": "Direct (fuel on site)",
    "indirect": "Indirect (electricity)",
    "precursor": "Precursor (steel in)",
}

_GAP = {"line": {"color": theme.SURFACE, "width": 2}}


def _fig(layout: Mapping | None = None) -> go.Figure:
    return go.Figure(layout=theme.plotly_layout(**(layout or {})))


# ------------------------------------------------------------- 1 shop floor ---
def carbon_waterfall(buckets: Mapping[str, float], good_parts: float) -> go.Figure:
    """Where the kilograms in one part come from.

    Starts at the value-adding floor and adds each loss until it reaches the
    footprint actually declared, so the gap between the first bar and the last
    is the part of the footprint that better operations could remove.
    """
    order = [b for b in BUCKET_LABELS if b in buckets]
    per_part = {b: buckets[b] * 1000.0 / good_parts for b in order}
    losses = [b for b in order if b != "value_adding"]

    labels = ["Value adding"] + [BUCKET_LABELS[b] for b in losses] + ["Declared footprint"]
    values = [per_part["value_adding"]] + [per_part[b] for b in losses] + [0.0]
    measures = ["absolute"] + ["relative"] * len(losses) + ["total"]

    fig = _fig(
        {
            "title": {"text": "Carbon footprint of one part, kg CO2e"},
            "yaxis": {"title": {"text": "kg CO2e per part"}},
            "xaxis": {"tickangle": -25},
            "showlegend": False,
            "margin": {"b": 96},
        }
    )
    fig.add_trace(
        go.Waterfall(
            orientation="v",
            measure=measures,
            x=labels,
            y=values,
            text=[f"{v:.2f}" if m != "total" else "" for v, m in zip(values, measures)],
            textposition="outside",
            textfont={"color": theme.INK_SOFT, "size": 11},
            connector={"line": {"color": theme.LINE, "width": 1}},
            increasing={"marker": {"color": theme.GOLD, **_GAP}},
            decreasing={"marker": {"color": theme.EMERALD, **_GAP}},
            totals={"marker": {"color": theme.STEEL, **_GAP}},
            hovertemplate="%{x}<br>%{y:.3f} kg CO2e per part<extra></extra>",
        )
    )
    return fig


def station_time(stations: Sequence) -> go.Figure:
    """Where each station's planned hours go.

    The bottleneck shows almost no idle time; everything upstream of it does,
    and that idle time is what the standby-shutdown lever attacks.
    """
    names = [s.name for s in stations]
    fig = _fig(
        {
            "title": {"text": "Planned time by station and machine state, hours per year"},
            "yaxis": {"title": {"text": "hours per year"}},
            "xaxis": {"tickangle": -20},
            "barmode": "stack",
            "margin": {"b": 110},
        }
    )
    run = [s.run_h for s in stations]
    idle = [s.idle_h + s.changeover_h for s in stations]
    down = [s.down_h for s in stations]
    for label, hours, colour in [
        ("Running", run, theme.CATEGORICAL[0]),
        ("Idle and changeover", idle, theme.CATEGORICAL[1]),
        ("Breakdown", down, theme.CATEGORICAL[2]),
    ]:
        fig.add_trace(
            go.Bar(
                name=label,
                x=names,
                y=hours,
                marker={"color": colour, **_GAP},
                hovertemplate="%{x}<br>" + label + ": %{y:,.0f} h<extra></extra>",
            )
        )
    return fig


# ------------------------------------------------------------------ 2 cbam ---
def scope_split(declaration) -> go.Figure:
    """The three SEE components against the benchmark credit and the default value."""
    fig = _fig(
        {
            "title": {
                "text": "Specific embedded emissions vs the benchmark, t CO2e per tonne"
            },
            "xaxis": {"title": {"text": "t CO2e per tonne of goods"}},
            "yaxis": {"showticklabels": False},
            "barmode": "stack",
            "height": 340,
            "margin": {"t": 72, "b": 118, "l": 24},
            "legend": {"y": -0.55},
        }
    )
    for key, value in [
        ("precursor", declaration.see_precursor),
        ("indirect", declaration.see_indirect),
        ("direct", declaration.see_direct),
    ]:
        fig.add_trace(
            go.Bar(
                name=SCOPE_LABELS[key],
                x=[value],
                y=["Declared"],
                orientation="h",
                width=0.42,
                marker={"color": theme.SCOPE_COLORS[key], **_GAP},
                hovertemplate=SCOPE_LABELS[key]
                + ": %{x:.3f} t CO2e/t<extra></extra>",
            )
        )
    for value, label, colour in [
        (declaration.sefa, f"Free allocation credit {declaration.sefa:.2f}", theme.EMERALD),
        (
            declaration.see_declared,
            f"This plant {declaration.see_declared:.2f}",
            theme.INK,
        ),
    ]:
        fig.add_vline(
            x=value,
            line={"color": colour, "width": 2, "dash": "dot"},
            annotation={"text": label, "font": {"color": colour, "size": 11}},
            annotation_position="top",
        )
    return fig


def phase_in(
    rows: Sequence[Mapping[str, float]],
    see: float | None = None,
    benchmark: float | None = None,
) -> go.Figure:
    """Headline phase-in against what this installation is actually liable for.

    Only two lines are drawn, because a plant sitting exactly on the benchmark
    is liable for ``(B - f*B) / B = 1 - f``, which *is* the headline payable
    share.  Plotting it as a third series would just redraw the second one.
    """
    years = [r["year"] for r in rows]
    plant_share = [r["liable_share_of_own_emissions"] for r in rows]
    benchmark_share = [r["headline_payable_share"] for r in rows]

    plant_label = "This plant"
    benchmark_label = "A plant at the benchmark"
    if see is not None:
        plant_label += f", {see:.2f} t CO2e/t"
    if benchmark is not None:
        benchmark_label += f", {benchmark:.2f} t CO2e/t"

    fig = _fig(
        {
            "title": {
                "text": "The phase-in applies to the benchmark, not to your emissions"
            },
            "yaxis": {
                "title": {"text": "share of own gross embedded emissions that is liable"},
                "tickformat": ".0%",
                "range": [0, 1.08],
            },
            "xaxis": {"title": {"text": "year"}, "dtick": 1},
            "hovermode": "x unified",
        }
    )
    for name, values, colour in [
        (plant_label, plant_share, theme.CATEGORICAL[3]),
        (benchmark_label + " (the headline share)", benchmark_share, theme.CATEGORICAL[0]),
    ]:
        fig.add_trace(
            go.Scatter(
                name=name,
                x=years,
                y=values,
                mode="lines+markers",
                line={"color": colour, "width": 2},
                marker={"size": 8, "line": {"color": theme.GROUND, "width": 2}},
                hovertemplate=name + ": %{y:.1%}<extra></extra>",
            )
        )
    if years:
        fig.add_annotation(
            x=years[0],
            y=plant_share[0],
            text=(
                f"{int(years[0])}: {plant_share[0]:.0%} of this plant's emissions are liable,"
                f"<br>against a headline payable share of {benchmark_share[0]:.1%}"
            ),
            showarrow=True,
            arrowcolor=theme.GOLD,
            arrowhead=0,
            ax=30,
            ay=-58,
            xanchor="left",
            align="left",
            font={"color": theme.GOLD, "size": 11},
        )
    return fig


def trajectory(frame: pd.DataFrame) -> go.Figure:
    """The annual bill across the phase-in under three ETS price paths."""
    label_map = {
        "flat_90": "ETS price flat",
        "growth_6pc": "ETS price +6% a year",
        "growth_10pc": "ETS price +10% a year",
    }
    fig = _fig(
        {
            "title": {"text": "CBAM bill on the same order book, EUR per year"},
            "yaxis": {"title": {"text": "EUR per year"}, "tickformat": ",.0f"},
            "xaxis": {"title": {"text": "year"}, "dtick": 1},
            "hovermode": "x unified",
        }
    )
    for index, (path, label) in enumerate(label_map.items()):
        subset = frame[frame["ets_path"] == path].sort_values("year")
        if subset.empty:
            continue
        colour = theme.CATEGORICAL[index]
        fig.add_trace(
            go.Scatter(
                name=label,
                x=subset["year"],
                y=subset["net_cost_eur"],
                mode="lines+markers",
                line={"color": colour, "width": 2},
                marker={"size": 8, "line": {"color": theme.GROUND, "width": 2}},
                hovertemplate=label + ": EUR %{y:,.0f}<extra></extra>",
            )
        )
    return fig


def basis_comparison(frame: pd.DataFrame) -> go.Figure:
    """What verified emissions data is worth against the default values."""
    fig = _fig(
        {
            "title": {"text": "Verified actual values vs default values, EUR per year"},
            "yaxis": {"title": {"text": "EUR per year"}, "tickformat": ",.0f"},
            "xaxis": {"title": {"text": "year"}, "dtick": 1},
            "barmode": "group",
            "bargap": 0.28,
            "hovermode": "x unified",
        }
    )
    for name, column, colour in [
        ("Default values plus mark-up", "cost_default_eur", theme.GOLD),
        ("Verified actual values", "cost_actual_eur", theme.EMERALD),
    ]:
        fig.add_trace(
            go.Bar(
                name=name,
                x=frame["year"],
                y=frame[column],
                marker={"color": colour, **_GAP},
                hovertemplate=name + ": EUR %{y:,.0f}<extra></extra>",
            )
        )
    return fig


def de_minimis_cliff(frame: pd.DataFrame, threshold_t: float) -> go.Figure:
    """The 50-tonne step: one extra pallet turns a zero bill into a full one."""
    fig = _fig(
        {
            "title": {
                "text": f"The {threshold_t:,.0f} t de minimis step, EUR per year"
            },
            "yaxis": {"title": {"text": "EUR per year"}, "tickformat": ",.0f"},
            "xaxis": {"title": {"text": "tonnes shipped to the EU per year"}},
        }
    )
    fig.add_vrect(
        x0=0,
        x1=threshold_t,
        fillcolor=theme.EMERALD,
        opacity=0.12,
        line_width=0,
        annotation={"text": "outside CBAM", "font": {"color": theme.EMERALD, "size": 11}},
        annotation_position="top left",
    )
    fig.add_trace(
        go.Scatter(
            name="Net CBAM cost",
            x=frame["eu_mass_t"],
            y=frame["net_cost_eur"],
            mode="lines",
            line={"color": theme.CATEGORICAL[0], "width": 2, "shape": "hv"},
            hovertemplate="%{x:,.0f} t shipped<br>EUR %{y:,.0f}<extra></extra>",
            showlegend=False,
        )
    )
    first_liable = frame[~frame["exempt"]].head(1)
    if not first_liable.empty:
        row = first_liable.iloc[0]
        fig.add_annotation(
            x=row["eu_mass_t"],
            y=row["net_cost_eur"],
            text=(
                f"{row['eu_mass_t']:,.0f} t shipped"
                f"<br>EUR {row['net_cost_eur']:,.0f} due"
            ),
            showarrow=True,
            arrowcolor=theme.GOLD,
            arrowhead=0,
            ax=70,
            ay=-40,
            font={"color": theme.GOLD, "size": 11},
        )
    return fig


def origin_price(frame: pd.DataFrame, year: int = 2030) -> go.Figure:
    """How much a carbon price at home takes off the bill abroad."""
    subset = frame[frame["year"] == year]
    labels = {
        "idx_carbon_3.9": "Today, about EUR 4/t",
        "target_40": "Ministry target, EUR 40/t",
        "eu_parity_90": "EU parity, EUR 90/t",
    }
    fig = _fig(
        {
            "title": {
                "text": f"Carbon price paid at origin against the {year} bill, EUR per year"
            },
            "yaxis": {"title": {"text": "EUR per year"}, "tickformat": ",.0f"},
            "xaxis": {
                "title": {"text": "share of embedded emissions priced at origin"},
                "tickformat": ".0%",
            },
            "hovermode": "x unified",
        }
    )
    for index, (key, label) in enumerate(labels.items()):
        rows = subset[subset["origin_price_label"] == key].sort_values("coverage")
        if rows.empty:
            continue
        colour = theme.CATEGORICAL[index]
        fig.add_trace(
            go.Scatter(
                name=label,
                x=rows["coverage"],
                y=rows["net_cost_eur"],
                mode="lines+markers",
                line={"color": colour, "width": 2},
                marker={"size": 8, "line": {"color": theme.GROUND, "width": 2}},
                hovertemplate=label + ": EUR %{y:,.0f}<extra></extra>",
            )
        )
    return fig


def eaf_crossover(frame: pd.DataFrame) -> go.Figure:
    """The scrap route buys years of zero bill, then the bill starts."""
    fig = _fig(
        {
            "title": {"text": "Blast-furnace coil vs scrap-route coil, EUR per year"},
            "yaxis": {"title": {"text": "EUR per year"}, "tickformat": ",.0f"},
            "xaxis": {"title": {"text": "year"}, "dtick": 1},
            "hovermode": "x unified",
        }
    )
    for name, column, colour in [
        ("Blast-furnace coil", "cost_bf_bof_eur", theme.CATEGORICAL[3]),
        ("Scrap-route coil", "cost_scrap_eaf_eur", theme.CATEGORICAL[0]),
    ]:
        fig.add_trace(
            go.Scatter(
                name=name,
                x=frame["year"],
                y=frame[column],
                mode="lines+markers",
                line={"color": colour, "width": 2},
                marker={"size": 8, "line": {"color": theme.GROUND, "width": 2}},
                hovertemplate=name + ": EUR %{y:,.0f}<extra></extra>",
            )
        )
    liable = frame[~frame["eaf_bill_is_zero"]].head(1)
    if not liable.empty:
        row = liable.iloc[0]
        fig.add_annotation(
            x=row["year"],
            y=row["cost_scrap_eaf_eur"],
            text=(
                f"{int(row['year'])}: the benchmark credit falls below<br>"
                f"the scrap route's {row['see_scrap_eaf']:.2f} t CO2e/t"
            ),
            showarrow=True,
            arrowcolor=theme.GOLD,
            arrowhead=0,
            ax=-40,
            ay=-60,
            font={"color": theme.GOLD, "size": 11},
            align="left",
        )
    return fig


# ---------------------------------------------------------------- 3 levers ---
def macc(frame: pd.DataFrame, clip_eur: float = 400.0) -> go.Figure:
    """Marginal abatement cost curve, before and after the CBAM bill.

    Bar width is the abatement a lever delivers and bar height its cost per
    tonne, so area is annual cost.  The dashed step shows the same levers in
    the same order once the avoided CBAM bill is counted; everything below zero
    pays for itself.

    One lever on this plant costs orders of magnitude more per tonne than the
    rest and would flatten every other bar into the axis.  The view is capped
    instead, and the capped lever is labelled with its real value rather than
    quietly dropped.
    """
    engineering = frame[frame["view"] == "engineering_only"].copy()
    with_cbam = frame[frame["view"] == "with_cbam"].copy()
    order = list(engineering["key"])
    with_cbam = with_cbam.set_index("key").loc[order].reset_index()

    inside = engineering[engineering["cost_per_t_co2_eur"].abs() <= clip_eur]
    low = min(
        0.0,
        float(inside["cost_per_t_co2_eur"].min()) if not inside.empty else 0.0,
        float(with_cbam["cost_per_t_co2_eur"].clip(-clip_eur, clip_eur).min()),
    )
    high = max(
        0.0,
        float(inside["cost_per_t_co2_eur"].max()) if not inside.empty else 0.0,
    )
    pad = max(20.0, 0.18 * (high - low))

    fig = _fig(
        {
            "title": {"text": "Marginal abatement cost curve, EUR per t CO2e"},
            "yaxis": {
                "title": {"text": "EUR per t CO2e abated"},
                "range": [low - pad, high + pad],
            },
            "xaxis": {"title": {"text": "cumulative abatement, t CO2e per year"}},
            "bargap": 0,
            "margin": {"b": 72},
        }
    )
    centres = (
        engineering["cumulative_start_t_co2"] + engineering["abatement_t_co2"] / 2.0
    )
    fig.add_trace(
        go.Bar(
            name="Engineering case",
            x=centres,
            y=engineering["cost_per_t_co2_eur"],
            width=engineering["abatement_t_co2"],
            marker={"color": theme.GOLD, **_GAP},
            customdata=engineering[["name", "abatement_t_co2"]].values,
            hovertemplate=(
                "%{customdata[0]}<br>%{customdata[1]:,.0f} t CO2e per year"
                "<br>EUR %{y:,.0f} per t<extra></extra>"
            ),
        )
    )
    step_x, step_y = [], []
    for _, row in with_cbam.iterrows():
        value = max(low - pad, min(high + pad, row["cost_per_t_co2_eur"]))
        step_x.extend([row["cumulative_start_t_co2"], row["cumulative_abatement_t_co2"]])
        step_y.extend([value, value])
    fig.add_trace(
        go.Scatter(
            name="After the CBAM bill it avoids",
            x=step_x,
            y=step_y,
            mode="lines",
            line={"color": theme.EMERALD, "width": 2, "dash": "dash"},
            hovertemplate="EUR %{y:,.0f} per t<extra></extra>",
        )
    )
    fig.add_hline(y=0, line={"color": theme.INK_MUTED, "width": 1})
    for _, row in engineering.iterrows():
        if abs(row["cost_per_t_co2_eur"]) > clip_eur:
            fig.add_annotation(
                x=row["cumulative_start_t_co2"] + row["abatement_t_co2"] / 2.0,
                y=high + pad,
                text=f"{row['name']}<br>EUR {row['cost_per_t_co2_eur']:,.0f}/t, above the view",
                showarrow=False,
                yanchor="top",
                xanchor="right",
                font={"color": theme.INK_MUTED, "size": 10},
                align="right",
            )
    return fig


def lever_dumbbell(
    frame: pd.DataFrame, clip_eur: float | None = None, outlier_eur: float = 400.0
) -> go.Figure:
    """Cost of abatement per lever, before and after the CBAM bill.

    The window is sized from the levers that fit in it.  Anything beyond is
    held at the edge and labelled with its real value rather than silently
    dropped, so a reader can see that something was left out and what it was.
    """
    data = frame[frame["abatement_t_co2"] > 0].copy()
    data = data.sort_values("cost_per_t_co2_with_cbam_eur")
    if clip_eur is None:
        inside = [
            abs(v)
            for v in list(data["cost_per_t_co2_eur"])
            + list(data["cost_per_t_co2_with_cbam_eur"])
            if abs(v) <= outlier_eur
        ]
        clip_eur = max(50.0, 1.25 * max(inside)) if inside else outlier_eur
    fig = _fig(
        {
            "title": {"text": "What the CBAM bill does to the business case"},
            "xaxis": {"title": {"text": "EUR per t CO2e abated"}, "range": [-clip_eur, clip_eur]},
            "yaxis": {"title": {"text": ""}, "automargin": True},
            "height": 420,
            "margin": {"l": 220},
        }
    )
    fig.add_vline(x=0, line={"color": theme.INK_MUTED, "width": 1})
    for _, row in data.iterrows():
        start = max(-clip_eur, min(clip_eur, row["cost_per_t_co2_eur"]))
        end = max(-clip_eur, min(clip_eur, row["cost_per_t_co2_with_cbam_eur"]))
        fig.add_trace(
            go.Scatter(
                x=[start, end],
                y=[row["name"], row["name"]],
                mode="lines",
                line={"color": theme.LINE, "width": 3},
                showlegend=False,
                hoverinfo="skip",
            )
        )
        if abs(row["cost_per_t_co2_eur"]) > clip_eur:
            fig.add_annotation(
                x=start,
                y=row["name"],
                text=f"EUR {row['cost_per_t_co2_eur']:,.0f}/t, beyond the view  ",
                showarrow=False,
                xanchor="right" if start > 0 else "left",
                yshift=14,
                font={"color": theme.INK_MUTED, "size": 10},
            )
    fig.add_trace(
        go.Scatter(
            name="Engineering case",
            x=[max(-clip_eur, min(clip_eur, v)) for v in data["cost_per_t_co2_eur"]],
            y=data["name"],
            mode="markers",
            marker={
                "color": theme.GOLD,
                "size": 12,
                "line": {"color": theme.GROUND, "width": 2},
            },
            hovertemplate="%{y}<br>engineering case: EUR %{x:,.0f} per t<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            name="After the CBAM bill",
            x=[
                max(-clip_eur, min(clip_eur, v))
                for v in data["cost_per_t_co2_with_cbam_eur"]
            ],
            y=data["name"],
            mode="markers",
            marker={
                "color": theme.EMERALD,
                "size": 12,
                "line": {"color": theme.GROUND, "width": 2},
            },
            hovertemplate="%{y}<br>after CBAM: EUR %{x:,.0f} per t<extra></extra>",
        )
    )
    return fig


def abatement_bars(frame: pd.DataFrame) -> go.Figure:
    """How much CO2e each lever removes, with the paper claim marked."""
    data = frame[frame["abatement_t_co2"] > 0].sort_values("abatement_t_co2")
    colours = [
        theme.CATEGORICAL[0] if physical else theme.CATEGORICAL[2]
        for physical in data["physical"]
    ]
    fig = _fig(
        {
            "title": {"text": "Abatement at the same order book, t CO2e per year"},
            "xaxis": {"title": {"text": "t CO2e per year"}},
            "yaxis": {"automargin": True},
            "height": 400,
            "margin": {"l": 220},
            "showlegend": False,
        }
    )
    labels = [
        f"{value:,.0f}" if physical else f"{value:,.0f}   reported only, nothing physical changes"
        for value, physical in zip(data["abatement_t_co2"], data["physical"])
    ]
    fig.add_trace(
        go.Bar(
            x=data["abatement_t_co2"],
            y=data["name"],
            orientation="h",
            marker={"color": colours, **_GAP},
            text=labels,
            textposition="outside",
            textfont={"color": theme.INK_SOFT, "size": 11},
            cliponaxis=False,
            hovertemplate="%{y}<br>%{x:,.0f} t CO2e per year<extra></extra>",
        )
    )
    return fig
