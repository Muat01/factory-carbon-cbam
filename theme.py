"""MH Emerald & Gold design tokens.

Single source of truth for colours, fonts and spacing used by the Streamlit
app (``ui.py``) and every Plotly figure (``charts.py``).  Keeping the tokens in
one module is what makes the app, the README figures and the LinkedIn carousel
look like one system.
"""

from __future__ import annotations

# --- surfaces -------------------------------------------------------------
GROUND = "#0E1311"
SURFACE = "#171E1B"
SURFACE_2 = "#1F2824"
LINE = "#2A3530"
GRID = "#232D29"

# --- ink ------------------------------------------------------------------
INK = "#EEF2EF"
INK_SOFT = "#B7C2BC"
INK_MUTED = "#7E8C85"

# --- brand ----------------------------------------------------------------
EMERALD = "#22C98A"   # brand, "better", active
GOLD = "#E6B94A"      # value / cost, highlights, simulated-data badge
STEEL = "#6FA8FF"     # support

# --- status ---------------------------------------------------------------
GOOD = EMERALD
WARN = GOLD
CRITICAL = "#F0616D"  # always used together with a text label

# --- categorical series (fixed order, CVD-checked) ------------------------
CATEGORICAL = [
    "#16A673",  # emerald
    "#4F86E0",  # steel
    "#B88A26",  # gold
    "#D05A74",  # rose
    "#9479E6",  # lilac
]

# --- light theme (print / report figures) ---------------------------------
LIGHT = {
    "ground": "#F6F8F6",
    "surface": "#FFFFFF",
    "ink": "#0E1311",
    "ink_soft": "#4A5751",
    "emerald": "#0C7F54",
    "gold": "#8A6610",
    "steel": "#2F65C2",
    "grid": "#DCE4E0",
    "categorical": ["#0F8A5C", "#2F65C2", "#9A7212", "#B23E5A", "#6E54C9"],
}

# --- type -----------------------------------------------------------------
FONT_SANS = "Inter, 'Segoe UI', system-ui, sans-serif"
FONT_MONO = "'JetBrains Mono', 'Cascadia Mono', ui-monospace, monospace"

TYPE = {
    "display": (48, 800),
    "h1": (32, 800),
    "h2": (22, 700),
    "body": (15, 400),
    "kpi": (30, 700),
    "label": (11, 600),
}

# --- shape ----------------------------------------------------------------
SPACE = [4, 8, 12, 16, 24, 32]
RADIUS = {"sm": 6, "md": 10, "lg": 16, "pill": 999}


# --- semantic helpers -----------------------------------------------------
# Emissions scopes keep the same colour everywhere in the project.
SCOPE_COLORS = {
    "direct": "#B88A26",      # gold  - fuel burnt on site
    "indirect": "#4F86E0",    # steel - purchased electricity
    "precursor": "#16A673",   # emerald - embedded in input material
}

# Loss categories in the energy waterfall.
LOSS_COLORS = {
    "value_adding": EMERALD,
    "scrap": CRITICAL,
    "downtime": GOLD,
    "idle": STEEL,
    "baseload": "#9479E6",
}


def plotly_layout(**overrides) -> dict:
    """Return the shared dark Plotly layout.

    All figure builders merge their own keys through this helper instead of
    calling ``update_layout`` twice, which would raise a duplicate-keyword
    error in Plotly.
    """
    base = {
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"family": FONT_SANS, "size": 13, "color": INK_SOFT},
        "title": {"font": {"family": FONT_SANS, "size": 16, "color": INK}, "x": 0.0},
        "margin": {"l": 64, "r": 24, "t": 56, "b": 56},
        "xaxis": {"gridcolor": GRID, "zerolinecolor": LINE, "linecolor": LINE},
        "yaxis": {"gridcolor": GRID, "zerolinecolor": LINE, "linecolor": LINE},
        "legend": {"orientation": "h", "y": -0.18, "x": 0.0, "font": {"size": 12}},
        "hoverlabel": {"bgcolor": SURFACE_2, "bordercolor": LINE,
                       "font": {"family": FONT_SANS, "color": INK}},
    }
    return merge(base, overrides)


def merge(base: dict, extra: dict) -> dict:
    """Recursively merge ``extra`` into a copy of ``base``.

    Plotly raises if the same keyword reaches ``update_layout`` twice, so every
    figure merges dictionaries here first and passes the result once.
    """
    out = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = value
    return out
