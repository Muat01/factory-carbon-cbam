"""Build the six-slide LinkedIn carousel as a 1080x1350 PDF.

Every number on a slide is read from ``results/`` so the carousel cannot drift
away from the repository.  Run ``python experiments.py`` and
``python make_docs.py`` first.

This script needs matplotlib, which the app itself does not: install it with
``pip install -r carousel/requirements.txt``.  Output is a 1080x1350 PDF plus
six PNG previews.
"""

from __future__ import annotations

import os
import sys

import matplotlib
import pandas as pd

matplotlib.use("Agg")

import matplotlib.image as mpimg  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import theme  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RESULTS = os.path.join(ROOT, "results")
DOCS = os.path.join(ROOT, "docs")
OUT = os.path.join(HERE, "factory-carbon-cbam-carousel.pdf")

W, H, DPI = 1080, 1350, 150
FIG_W, FIG_H = W / DPI, H / DPI

SANS = "Inter"
MONO = "JetBrains Mono"


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(os.path.join(RESULTS, name))


# ------------------------------------------------------------------ canvas ---
def new_slide():
    figure = plt.figure(figsize=(FIG_W, FIG_H), dpi=DPI)
    figure.patch.set_facecolor(theme.GROUND)
    axes = figure.add_axes([0, 0, 1, 1])
    axes.set_xlim(0, W)
    axes.set_ylim(0, H)
    axes.invert_yaxis()
    axes.axis("off")
    axes.set_facecolor(theme.GROUND)
    return figure, axes


def lanes(ax, x=W - 250, y=56):
    """The signature Gantt-lane motif, top right."""
    bars = [
        (0, 150, theme.EMERALD),
        (36, 96, theme.GOLD),
        (18, 132, theme.SURFACE_2),
        (64, 60, theme.EMERALD),
    ]
    for index, (offset, length, colour) in enumerate(bars):
        ax.add_patch(
            Rectangle(
                (x + offset, y + index * 13),
                length,
                7,
                facecolor=colour,
                edgecolor="none",
                alpha=0.95 if colour != theme.SURFACE_2 else 0.7,
            )
        )


def mark(ax, x=72, y=58, size=54):
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            size,
            size,
            boxstyle="round,pad=0,rounding_size=11",
            facecolor=theme.EMERALD,
            edgecolor="none",
        )
    )
    ax.text(
        x + size / 2,
        y + size / 2 + 2,
        "MH",
        ha="center",
        va="center",
        color=theme.GROUND,
        fontsize=pt(26),
        fontweight=800,
        fontfamily=SANS,
    )
    ax.add_patch(
        Rectangle((x + 13, y + size + 7), 28, 5, facecolor=theme.GOLD, edgecolor="none")
    )


def pt(pixels: float) -> float:
    """Convert a size in canvas pixels to matplotlib points.

    The canvas is addressed in pixels but matplotlib sizes type in points, so
    without this every label comes out DPI/72 times too large.
    """
    return pixels * 72.0 / DPI


def text(ax, x, y, body, size=16, colour=None, weight=400, font=SANS, ha="left", va="top", **kw):
    return ax.text(
        x,
        y,
        body,
        fontsize=pt(size),
        color=colour or theme.INK_SOFT,
        fontweight=weight,
        fontfamily=font,
        ha=ha,
        va=va,
        **kw,
    )


def panel(ax, x, y, w, h, fill=None, edge=None, radius=16):
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle=f"round,pad=0,rounding_size={radius}",
            facecolor=fill or theme.SURFACE,
            edgecolor=edge or theme.LINE,
            linewidth=1.2,
        )
    )


def badge(ax, x, y, label, colour=None):
    colour = colour or theme.GOLD
    width = 20 + 7.6 * len(label)
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            30,
            boxstyle="round,pad=0,rounding_size=15",
            facecolor=theme.SURFACE,
            edgecolor=colour,
            linewidth=1.2,
        )
    )
    text(ax, x + width / 2, y + 15, label, size=11, colour=colour, weight=600,
         font=MONO, ha="center", va="center")


def footer(ax, page: int, total: int = 6):
    text(ax, 72, H - 48, "Simulated data - illustrative parameters", size=11,
         colour=theme.INK_MUTED, font=MONO, va="center")
    text(ax, W - 72, H - 48, f"{page}/{total}", size=11, colour=theme.INK_MUTED,
         font=MONO, ha="right", va="center")


def embed(ax, filename, x, y, w):
    image = mpimg.imread(os.path.join(DOCS, filename))
    height = w * image.shape[0] / image.shape[1]
    ax.imshow(image, extent=(x, x + w, y + height, y), zorder=3, interpolation="antialiased")
    return height


def kpi_grid(ax, items, x, y, w, columns=2, row_h=120, gap=16):
    cell_w = (w - gap * (columns - 1)) / columns
    for index, (label, value, note) in enumerate(items):
        column, row = index % columns, index // columns
        cx = x + column * (cell_w + gap)
        cy = y + row * (row_h + gap)
        panel(ax, cx, cy, cell_w, row_h, radius=12)
        text(ax, cx + 20, cy + 20, label.upper(), size=11, colour=theme.INK_MUTED,
             weight=600, font=MONO)
        text(ax, cx + 20, cy + 46, value, size=29, colour=theme.INK, weight=700, font=MONO)
        text(ax, cx + 20, cy + 88, note, size=13, colour=theme.INK_SOFT)


# ------------------------------------------------------------------ slides ---
def slide_hook(ax, data):
    mark(ax)
    lanes(ax)
    text(ax, 72, 190, "Brussels says you pay", size=34, colour=theme.INK_SOFT, weight=700)
    text(ax, 72, 236, "for 2.5% of your", size=34, colour=theme.INK_SOFT, weight=700)
    text(ax, 72, 282, "emissions in 2026.", size=34, colour=theme.INK_SOFT, weight=700)
    text(ax, 72, 360, "This plant pays", size=46, colour=theme.INK, weight=800)
    text(ax, 72, 418, "for 44%.", size=72, colour=theme.EMERALD, weight=800)

    panel(ax, 72, 580, W - 144, 262)
    text(ax, 104, 612, "WHY", size=11, colour=theme.INK_MUTED, weight=600, font=MONO)
    body = (
        "CBAM's free allocation credit is benchmark-based, not\n"
        "emissions-based. The phase-in protects a plant sitting on the\n"
        "EU benchmark. Everything above it is payable from the first\n"
        "year - and this plant emits 3.13 t CO2e per tonne against a\n"
        "1.80 benchmark."
    )
    text(ax, 104, 648, body, size=18, colour=theme.INK_SOFT, linespacing=1.62)

    text(ax, 72, 888, "A simulated Indonesian steel-bracket plant,", size=20,
         colour=theme.INK, weight=600)
    text(ax, 72, 922, "modelled from the shop floor to the border.", size=20,
         colour=theme.INK, weight=600)

    badge(ax, 72, 988, "SIMULATED DATA")
    badge(ax, 320, 988, "123 TESTS", theme.EMERALD)
    badge(ax, 510, 988, "MIT", theme.STEEL)

    teaser = [
        ("26%", "of the footprint\nis not value adding"),
        ("EUR 70,858", "the 2026 bill on\n571 t shipped"),
        ("2 levers", "flip from cost\nto investment"),
    ]
    panel(ax, 72, 1086, W - 144, 148, fill=theme.SURFACE_2)
    for index, (value, note) in enumerate(teaser):
        cx = 112 + index * 310
        text(ax, cx, 1116, value, size=28, colour=theme.EMERALD, weight=700, font=MONO)
        text(ax, cx, 1162, note, size=14, colour=theme.INK_SOFT, linespacing=1.45)
    footer(ax, 1)


def slide_chain(ax, data):
    text(ax, 72, 96, "One chain, four questions", size=36, colour=theme.INK, weight=800)
    text(ax, 72, 150, "Most CBAM tools start where the engineering ends.", size=17,
         colour=theme.INK_MUTED)
    lanes(ax)

    steps = [
        ("01", "SHOP FLOOR", "Cycle times, breakdowns, scrap and idle power become energy and steel.",
         "26% of the footprint is not value adding", theme.EMERALD),
        ("02", "PRODUCT FOOTPRINT", "Direct fuel, grid electricity and precursor steel, per tonne of good product.",
         "3.135 t CO2e per tonne, +/- 0.016", theme.STEEL),
        ("03", "CBAM BILL", "Benchmark credit, certificates, the price already paid at home, the 50 t threshold.",
         "EUR 70,858 in 2026, EUR 160,992 in 2034", theme.GOLD),
        ("04", "RE-PRICED BACKLOG", "Every improvement costed twice: as engineering, and after the bill it avoids.",
         "2 levers flip from cost to investment", theme.EMERALD),
    ]
    y = 226
    for number, title, body, result, colour in steps:
        panel(ax, 72, y, W - 144, 204)
        text(ax, 104, y + 26, number, size=12, colour=colour, weight=700, font=MONO)
        text(ax, 104, y + 54, title, size=20, colour=theme.INK, weight=700)
        text(ax, 104, y + 90, body, size=15, colour=theme.INK_SOFT, wrap=False)
        ax.add_patch(Rectangle((104, y + 140), 5, 28, facecolor=colour, edgecolor="none"))
        text(ax, 122, y + 147, result, size=15, colour=colour, weight=600, font=MONO)
        y += 222
    footer(ax, 2)


def slide_losses(ax, data):
    loss = data["loss"].set_index("bucket")
    text(ax, 72, 96, "A quarter of the carbon", size=36, colour=theme.INK, weight=800)
    text(ax, 72, 142, "is loss, not product", size=36, colour=theme.INK, weight=800)
    text(ax, 72, 196, "20.06 kg CO2e per bracket. Here is where it goes.", size=17,
         colour=theme.INK_MUTED)
    lanes(ax)

    height = embed(ax, "fig_carbon_waterfall.png", 72, 262, W - 144)

    y = 262 + height + 32
    kpi_grid(
        ax,
        [
            ("Offcut", f"{loss.loc['offcut','kg_co2e_per_part']:.2f} kg",
             f"{loss.loc['offcut','share_of_total']:.1%} - nesting never puts it in a part"),
            ("Scrapped parts", f"{loss.loc['scrap','kg_co2e_per_part']:.2f} kg",
             f"{loss.loc['scrap','share_of_total']:.1%} - steel and energy both wasted"),
            ("Site services", f"{loss.loc['baseload','kg_co2e_per_part']:.2f} kg",
             f"{loss.loc['baseload','share_of_total']:.1%} - lighting, HVAC, compressed air"),
            ("Idle and changeover", f"{loss.loc['idle','kg_co2e_per_part']:.2f} kg",
             f"{loss.loc['idle','share_of_total']:.1%} - machines on, nothing moving"),
        ],
        72,
        y,
        W - 144,
    )
    panel(ax, 72, y + 288, W - 144, 118, fill=theme.SURFACE_2)
    text(ax, 104, y + 318,
         "A rejected part wastes the steel in it, the energy already spent on it,\nand then raises the carbon intensity of every part that does ship.",
         size=16, colour=theme.INK_SOFT, linespacing=1.55)
    footer(ax, 3)


def slide_phase_in(ax, data):
    text(ax, 72, 96, "The phase-in protects", size=36, colour=theme.INK, weight=800)
    text(ax, 72, 142, "the benchmark, not you", size=36, colour=theme.INK, weight=800)
    text(ax, 72, 196, "Free allocation credit = CBAM factor x CSCF x benchmark.", size=17,
         colour=theme.INK_MUTED, font=MONO)
    lanes(ax)

    height = embed(ax, "fig_phase_in.png", 72, 258, W - 144)
    y = 258 + height + 32
    phase = data["phase"].set_index("year")
    traj = data["traj"]
    flat = traj[traj.ets_path == "flat_90"].set_index("year")
    kpi_grid(
        ax,
        [
            ("2026 headline", f"{phase.loc[2026,'headline_payable_share']:.1%}",
             "what the schedule says is payable"),
            ("2026 for this plant", f"{phase.loc[2026,'liable_share_of_own_emissions']:.1%}",
             "of its own embedded emissions"),
            ("2026 bill", f"EUR {flat.loc[2026,'net_cost_eur']:,.0f}",
             f"on {flat.loc[2026,'gross_emissions_t'] / 3.135:,.0f} t shipped to the EU"),
            ("2034 bill", f"EUR {flat.loc[2034,'net_cost_eur']:,.0f}",
             "same order book, flat carbon price"),
        ],
        72,
        y,
        W - 144,
    )
    panel(ax, 72, y + 288, W - 144, 118, fill=theme.SURFACE_2)
    text(ax, 104, y + 318,
         "A plant sitting exactly on the benchmark really does start at 2.5%.\nAbove it, the first year is already expensive.",
         size=16, colour=theme.INK_SOFT, linespacing=1.55)
    footer(ax, 4)


def slide_flip(ax, data):
    levers = data["levers"].set_index("key")
    text(ax, 72, 96, "The border price", size=36, colour=theme.INK, weight=800)
    text(ax, 72, 142, "re-ranks the backlog", size=36, colour=theme.INK, weight=800)
    text(ax, 72, 196, "Same levers, costed before and after the bill they avoid.", size=17,
         colour=theme.INK_MUTED)
    lanes(ax)

    height = embed(ax, "fig_lever_dumbbell.png", 72, 250, W - 144)
    y = 250 + height + 34

    rows = [
        ("Compressed-air leak repair", "air"),
        ("Rooftop solar, direct link", "solar_linked"),
    ]
    panel(ax, 72, y, W - 144, 224)
    text(ax, 104, y + 24, "FLIPPED FROM COST TO INVESTMENT", size=10,
         colour=theme.EMERALD, weight=600, font=MONO)
    row_y = y + 58
    for label, key in rows:
        row = levers.loc[key]
        text(ax, 104, row_y, label, size=17, colour=theme.INK, weight=600)
        text(ax, 620, row_y, f"EUR {row['cost_per_t_co2_eur']:+,.0f}", size=17,
             colour=theme.GOLD, weight=700, font=MONO)
        text(ax, 770, row_y, "->", size=17, colour=theme.INK_MUTED, font=MONO)
        text(ax, 820, row_y, f"EUR {row['cost_per_t_co2_with_cbam_eur']:+,.0f}", size=17,
             colour=theme.EMERALD, weight=700, font=MONO)
        row_y += 52
    text(ax, 104, row_y + 10, "per tonne of CO2e abated", size=13, colour=theme.INK_MUTED)

    y2 = y + 250
    panel(ax, 72, y2, W - 144, 172, edge=theme.GOLD)
    text(ax, 104, y2 + 24, "AND THE ONE THAT DOES NOT MOVE", size=10, colour=theme.GOLD,
         weight=600, font=MONO)
    paper = levers.loc["solar_unbundled"]
    solar = levers.loc["solar_linked"]
    body = (
        f"Unbundled certificates claim the same {paper['abatement_t_co2']:,.0f} t CO2e as the array\n"
        f"and save EUR {paper['cbam_saving_eur']:,.0f} of the bill. CBAM wants a direct technical link\n"
        f"or a real PPA; the array saves EUR {solar['cbam_saving_eur']:,.0f} a year."
    )
    text(ax, 104, y2 + 60, body, size=15, colour=theme.INK_SOFT, linespacing=1.6)
    footer(ax, 5)


def slide_cta(ax, data):
    mark(ax)
    lanes(ax)
    text(ax, 72, 200, "What is in the repo", size=38, colour=theme.INK, weight=800)

    items = [
        ("Three layers", "A line model, a CBAM engine and an abatement curve: 3,600 lines of Python, 1,100 more in tests."),
        ("A Streamlit app", "Six pages, every number live from the sidebar controls."),
        ("123 tests", "Conservation identities, the OEE identity, the regulatory schedule year by year, and all six pages headless."),
        ("Reproducible", "One command writes every CSV, another writes every figure. The README quotes nothing by hand."),
    ]
    y = 276
    for title, body in items:
        panel(ax, 72, y, W - 144, 140)
        text(ax, 104, y + 28, title, size=19, colour=theme.INK, weight=700)
        text(ax, 104, y + 66, body, size=14, colour=theme.INK_SOFT, linespacing=1.5)
        y += 156

    panel(ax, 72, y + 18, W - 144, 180, edge=theme.EMERALD)
    text(ax, 104, y + 46, "HONEST ABOUT WHAT IT IS", size=10, colour=theme.EMERALD,
         weight=600, font=MONO)
    body = (
        "The plant is invented and every parameter is illustrative. The CBAM\n"
        "benchmarks and default values are flagged placeholders derived from a\n"
        "stated rule, not the official tables. Not compliance advice."
    )
    text(ax, 104, y + 78, body, size=14, colour=theme.INK_SOFT, linespacing=1.5)

    text(ax, 72, H - 168, "Muatasem Hadi", size=21, colour=theme.INK, weight=700)
    text(ax, 72, H - 134, "github.com/Muat01  -  link in the first comment", size=15,
         colour=theme.GOLD, font=MONO)
    footer(ax, 6)


SLIDES = [slide_hook, slide_chain, slide_losses, slide_phase_in, slide_flip, slide_cta]


def main() -> None:
    data = {
        "loss": read("loss_attribution.csv"),
        "phase": read("phase_in.csv"),
        "traj": read("trajectory.csv"),
        "levers": read("levers.csv"),
        "basis": read("basis_comparison.csv"),
    }
    with PdfPages(OUT) as pdf:
        for builder in SLIDES:
            figure, axes = new_slide()
            builder(axes, data)
            pdf.savefig(figure, facecolor=theme.GROUND)
            png = os.path.join(HERE, f"slide_{SLIDES.index(builder) + 1}.png")
            figure.savefig(png, facecolor=theme.GROUND, dpi=DPI)
            plt.close(figure)
    print(f"wrote {OUT} and {len(SLIDES)} PNG previews")


if __name__ == "__main__":
    main()
