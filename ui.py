"""HTML components for the Streamlit app, in the MH Emerald & Gold identity.

Every HTML snippet is built as a single line.  Streamlit sends markdown
through a parser that turns four-space indentation into a code block, so a
prettily indented f-string renders as source text instead of a card.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence

import streamlit as st

import theme

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&family=JetBrains+Mono:wght@400;600;700&display=swap');
html, body, [class*="css"], .stApp {{ font-family: {theme.FONT_SANS}; }}
.stApp {{ background: {theme.GROUND}; }}
section[data-testid="stSidebar"] {{ background: {theme.SURFACE}; border-right: 1px solid {theme.LINE}; }}
#MainMenu, footer {{ visibility: hidden; }}
.mh-hero {{ display: flex; align-items: center; gap: 16px; margin: 4px 0 18px 0; }}
.mh-mark {{ width: 46px; height: 46px; border-radius: 10px; background: {theme.EMERALD}; color: {theme.GROUND}; font-weight: 800; font-size: 19px; display: flex; align-items: center; justify-content: center; letter-spacing: -0.5px; }}
.mh-mark-bar {{ width: 26px; height: 4px; border-radius: 2px; background: {theme.GOLD}; margin: 5px auto 0 auto; }}
.mh-hero-title {{ font-size: 30px; font-weight: 800; color: {theme.INK}; line-height: 1.15; margin: 0; }}
.mh-hero-sub {{ font-size: 14px; color: {theme.INK_MUTED}; margin: 3px 0 0 0; }}
.mh-badge {{ display: inline-block; padding: 4px 11px; border-radius: 999px; background: rgba(230,185,74,0.14); color: {theme.GOLD}; border: 1px solid rgba(230,185,74,0.34); font-family: {theme.FONT_MONO}; font-size: 11px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; }}
.mh-kpi-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(168px, 1fr)); gap: 12px; margin: 14px 0 20px 0; }}
.mh-kpi {{ background: {theme.SURFACE}; border: 1px solid {theme.LINE}; border-radius: 12px; padding: 14px 16px; }}
.mh-kpi-label {{ font-family: {theme.FONT_MONO}; font-size: 10px; font-weight: 600; letter-spacing: 0.16em; text-transform: uppercase; color: {theme.INK_MUTED}; }}
.mh-kpi-value {{ font-family: {theme.FONT_MONO}; font-size: 27px; font-weight: 700; color: {theme.INK}; margin-top: 6px; line-height: 1.1; }}
.mh-kpi-note {{ font-size: 12px; color: {theme.INK_SOFT}; margin-top: 5px; }}
.mh-card {{ background: {theme.SURFACE}; border: 1px solid {theme.LINE}; border-radius: 14px; padding: 18px 20px; margin-bottom: 16px; }}
.mh-card-title {{ font-size: 15px; font-weight: 700; color: {theme.INK}; margin: 0 0 7px 0; }}
.mh-card-body {{ font-size: 14px; line-height: 1.6; color: {theme.INK_SOFT}; margin: 0; }}
.mh-insight {{ background: {theme.SURFACE_2}; border-left: 3px solid {theme.EMERALD}; border-radius: 0 10px 10px 0; padding: 13px 16px; margin: 6px 0 16px 0; font-size: 14px; line-height: 1.6; color: {theme.INK_SOFT}; }}
.mh-insight.warn {{ border-left-color: {theme.GOLD}; }}
.mh-insight b {{ color: {theme.INK}; font-weight: 700; }}
.mh-section {{ font-size: 11px; font-family: {theme.FONT_MONO}; font-weight: 600; letter-spacing: 0.16em; text-transform: uppercase; color: {theme.INK_MUTED}; border-bottom: 1px solid {theme.LINE}; padding-bottom: 7px; margin: 26px 0 14px 0; }}
.mh-foot {{ color: {theme.INK_MUTED}; font-size: 12px; border-top: 1px solid {theme.LINE}; padding-top: 12px; margin-top: 30px; }}
.stDataFrame {{ border: 1px solid {theme.LINE}; border-radius: 10px; }}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str) -> None:
    mark = '<div><div class="mh-mark">MH</div><div class="mh-mark-bar"></div></div>'
    text = f'<div><p class="mh-hero-title">{title}</p><p class="mh-hero-sub">{subtitle}</p></div>'
    st.markdown(f'<div class="mh-hero">{mark}{text}</div>', unsafe_allow_html=True)


def badge(text: str) -> None:
    st.markdown(f'<span class="mh-badge">{text}</span>', unsafe_allow_html=True)


def section(label: str) -> None:
    st.markdown(f'<div class="mh-section">{label}</div>', unsafe_allow_html=True)


def kpi_row(items: Sequence[Mapping[str, str]]) -> None:
    """Render a row of KPI tiles. Each item needs ``label`` and ``value``."""
    cells = []
    for item in items:
        note = item.get("note", "")
        note_html = f'<div class="mh-kpi-note">{note}</div>' if note else ""
        cells.append(
            f'<div class="mh-kpi"><div class="mh-kpi-label">{item["label"]}</div><div class="mh-kpi-value">{item["value"]}</div>{note_html}</div>'
        )
    st.markdown(
        f'<div class="mh-kpi-row">{"".join(cells)}</div>', unsafe_allow_html=True
    )


def card(title: str, body: str) -> None:
    st.markdown(
        f'<div class="mh-card"><p class="mh-card-title">{title}</p><p class="mh-card-body">{body}</p></div>',
        unsafe_allow_html=True,
    )


def insight(text: str, tone: str = "good") -> None:
    css_class = "mh-insight warn" if tone == "warn" else "mh-insight"
    st.markdown(f'<div class="{css_class}">{text}</div>', unsafe_allow_html=True)


def footer(text: str) -> None:
    st.markdown(f'<div class="mh-foot">{text}</div>', unsafe_allow_html=True)


def bullets(title: str, items: Iterable[str]) -> None:
    lis = "".join(f"<li>{item}</li>" for item in items)
    st.markdown(
        f'<div class="mh-card"><p class="mh-card-title">{title}</p><ul class="mh-card-body" style="margin:0;padding-left:18px;">{lis}</ul></div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------- insights ---
def money(value: float) -> str:
    return f"EUR {value:,.0f}"


def plant_insight(result, factors) -> str:
    losses = result.carbon_loss_t_co2(factors)
    worst = max(
        ((k, v) for k, v in losses.items() if k != "value_adding"),
        key=lambda item: item[1],
    )
    names = {
        "scrap": "rejected parts",
        "offcut": "offcut that nesting never puts into a part",
        "idle": "idle and changeover time",
        "baseload": "site services",
        "downtime": "breakdowns",
        "performance": "running below nameplate speed",
    }
    share = result.avoidable_share(factors)
    return (
        f"<b>{share:.0%} of this plant's footprint is not value adding.</b> "
        f"The largest single loss is {names.get(worst[0], worst[0])} at "
        f"{worst[1]:,.0f} t CO2e a year, which is "
        f"{worst[1] * 1000 / result.good_parts:.2f} kg on every good part shipped. "
        f"The bottleneck is {result.bottleneck} and OEE is {result.oee:.1%}."
    )


def cbam_insight(declaration) -> str:
    if declaration.exempt:
        return (
            f"<b>Outside CBAM.</b> At {declaration.mass_t:,.0f} t a year this importer "
            f"stays under the {declaration.de_minimis_t:,.0f} t de minimis threshold, so no "
            "authorisation, no declaration and no certificates. One more pallet over the "
            "line and the full obligation applies to everything imported, not just the excess."
        )
    liable_share = (
        declaration.liable_emissions_t / declaration.gross_emissions_t
        if declaration.gross_emissions_t
        else 0.0
    )
    return (
        f"<b>{liable_share:.0%} of this plant's embedded emissions are liable in "
        f"{declaration.year}, not the headline {declaration.payable_share:.1%}.</b> "
        f"The free allocation credit is benchmark-based at {declaration.sefa:.2f} t CO2e per "
        f"tonne, and this plant declares {declaration.see_declared:.2f}. Everything above the "
        f"benchmark is payable from the first year: {money(declaration.net_cost_eur)} on "
        f"{declaration.mass_t:,.0f} t shipped, or {declaration.cost_per_t_goods:,.2f} per tonne of product."
    )


def lever_insight(results) -> str:
    flipped = [r for r in results if r.flipped_by_cbam]
    already = [r for r in results if r.profitable_without_cbam]
    if not flipped:
        return (
            f"<b>{len(already)} levers already pay for themselves</b> before CBAM is counted. "
            "At this carbon price nothing else crosses from cost into profit."
        )
    names = " and ".join(r.lever.name.lower() for r in flipped)
    best = min(flipped, key=lambda r: r.cost_per_t_co2_with_cbam_eur)
    return (
        f"<b>The CBAM bill turns {len(flipped)} lever(s) from a cost into an investment:</b> "
        f"{names}. {best.lever.name} moves from "
        f"EUR {best.cost_per_t_co2_eur:,.0f} to EUR {best.cost_per_t_co2_with_cbam_eur:,.0f} per tonne "
        f"abated once the avoided bill is counted, with a payback of "
        f"{best.payback_years:.1f} years. A further {len(already)} were worth doing anyway."
    )
