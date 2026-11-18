"""Layer 2 -- from a product carbon footprint to a CBAM bill.

The chain the regulation defines, in the order this module applies it:

1. **Specific embedded emissions (SEE)**, in t CO2e per tonne of goods, split
   into direct emissions, indirect emissions from purchased electricity and the
   emissions embedded in precursor materials.
2. **Basis of declaration.**  Verified actual values, or the published default
   values for the production route.  Default values carry a regulatory mark-up
   of 10% in 2026, 20% in 2027 and 30% from 2028, which is what makes measuring
   your own emissions worth money.
3. **Free allocation adjustment (FAA).**  Imports get a credit for the EU ETS
   free allocation that EU producers still receive.  It is benchmark-based, not
   emissions-based: ``SEFA = CBAM factor x CSCF x benchmark``, and the FAA is
   ``SEFA x mass``.  The CBAM factor is the share of free allocation still
   granted -- 0.975 in 2026 -- so the payable share starts at 2.5% and reaches
   100% in 2034.
4. **Certificates.**  ``max(0, gross embedded emissions - FAA)``, priced at the
   EU ETS average.
5. **Carbon price already paid** in the country of origin reduces the bill.
6. **De minimis.**  An importer at or below 50 t of CBAM goods per calendar
   year is outside the mechanism entirely (hydrogen and electricity aside).

Two deliberate simplifications are flagged in the README: the carbon-price
deduction is modelled as a monetary credit rather than through the full
implementing-act procedure, and the benchmark and default values shipped in
``data/parameters.json`` are illustrative placeholders.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from config import CbamParams, Factors, Prices, Scenario
from plant import PlantResult

ACTUAL = "actual"
DEFAULT = "default"

#: Share of the running year's embedded emissions an authorised declarant must
#: already hold in certificates at the end of each quarter.  The Omnibus I
#: simplification lowered this from 80% to 50%.
QUARTERLY_HOLDING_SHARE = 0.50


@dataclass(frozen=True)
class Declaration:
    """One year of CBAM exposure for one good from one installation."""

    year: int
    good: str
    cn_code: str
    route: str
    basis: str
    mass_t: float

    see_direct: float
    see_indirect: float
    see_precursor: float
    see_declared: float

    benchmark: float
    cbam_factor: float
    cscf: float
    sefa: float

    gross_emissions_t: float
    free_allocation_t: float
    liable_emissions_t: float

    ets_price_eur_per_t: float
    gross_cost_eur: float
    origin_credit_eur: float
    net_cost_eur: float

    de_minimis_t: float
    exempt: bool
    electricity_basis: str

    # --- derived ------------------------------------------------------------
    @property
    def payable_share(self) -> float:
        return 1.0 - self.cbam_factor

    @property
    def certificates(self) -> float:
        """Certificates to surrender: one per tonne of liable CO2e."""
        return self.liable_emissions_t

    @property
    def cost_per_t_goods(self) -> float:
        return self.net_cost_eur / self.mass_t if self.mass_t > 0 else 0.0

    @property
    def quarterly_holding_t(self) -> float:
        """Certificates that must sit in the registry account each quarter."""
        return self.liable_emissions_t * QUARTERLY_HOLDING_SHARE

    @property
    def de_minimis_headroom_t(self) -> float:
        return self.de_minimis_t - self.mass_t

    @property
    def effective_rate_eur_per_t_co2(self) -> float:
        """What the importer actually pays per tonne of embedded CO2e."""
        if self.gross_emissions_t <= 0:
            return 0.0
        return self.net_cost_eur / self.gross_emissions_t


def specific_embedded_emissions(
    result: PlantResult,
    factors: Factors,
    recognise_actual_electricity: bool = False,
) -> tuple[float, float, float, str]:
    """Return the three SEE components and the electricity basis used.

    CBAM only accepts an electricity emission factor below the country default
    when the installation can prove a direct technical link or a qualifying
    power purchase agreement.  Rooftop generation behind the meter therefore
    lowers the declared footprint; an unbundled certificate purchase does not.
    """
    see_direct = result.see_direct
    see_precursor = result.see_precursor
    if recognise_actual_electricity:
        return see_direct, result.see_indirect, see_precursor, "actual"
    regulatory_indirect = (
        result.electricity_mwh
        * factors.ef_grid_country_default_t_co2_per_mwh
        / result.output_t
    )
    return see_direct, regulatory_indirect, see_precursor, "country_default"


def declare(
    result: PlantResult,
    scenario: Scenario,
    *,
    basis: str = ACTUAL,
    year: int | None = None,
    ets_price_eur_per_t: float | None = None,
    recognise_actual_electricity: bool = False,
    mass_t: float | None = None,
) -> Declaration:
    """Build the CBAM declaration implied by a plant result."""
    if basis not in (ACTUAL, DEFAULT):
        raise ValueError(f"basis must be {ACTUAL!r} or {DEFAULT!r}, got {basis!r}")

    cbam: CbamParams = scenario.cbam
    prices: Prices = scenario.prices
    year = cbam.year if year is None else year
    ets_price = prices.ets_price_eur_per_t if ets_price_eur_per_t is None else ets_price_eur_per_t
    mass = result.eu_output_t if mass_t is None else mass_t
    route = scenario.plant.production_route

    see_direct, see_indirect, see_precursor, electricity_basis = (
        specific_embedded_emissions(
            result, scenario.factors, recognise_actual_electricity
        )
    )
    see_actual = see_direct + see_indirect + see_precursor

    if basis == ACTUAL:
        see_declared = see_actual
    else:
        see_declared = cbam.default_value(route) * (
            1.0 + cbam.default_value_markup(year)
        )
        electricity_basis = "included in default value"

    cbam_factor = cbam.cbam_factor(year)
    benchmark = cbam.benchmark(route)
    sefa = cbam_factor * cbam.cross_sectoral_correction_factor * benchmark

    exempt = mass <= cbam.de_minimis_tonnes_per_year
    gross_emissions = 0.0 if exempt else mass * see_declared
    free_allocation = 0.0 if exempt else min(gross_emissions, mass * sefa)
    liable = max(0.0, gross_emissions - free_allocation)

    gross_cost = liable * ets_price
    origin_credit = min(
        gross_cost,
        mass
        * see_declared
        * prices.origin_carbon_price_coverage
        * prices.origin_carbon_price_eur_per_t,
    ) if not exempt else 0.0
    net_cost = max(0.0, gross_cost - origin_credit)

    return Declaration(
        year=year,
        good=scenario.plant.good,
        cn_code=scenario.plant.cn_code,
        route=route,
        basis=basis,
        mass_t=mass,
        see_direct=see_direct,
        see_indirect=see_indirect,
        see_precursor=see_precursor,
        see_declared=see_declared,
        benchmark=benchmark,
        cbam_factor=cbam_factor,
        cscf=cbam.cross_sectoral_correction_factor,
        sefa=sefa,
        gross_emissions_t=gross_emissions,
        free_allocation_t=free_allocation,
        liable_emissions_t=liable,
        ets_price_eur_per_t=ets_price,
        gross_cost_eur=gross_cost,
        origin_credit_eur=origin_credit,
        net_cost_eur=net_cost,
        de_minimis_t=cbam.de_minimis_tonnes_per_year,
        exempt=exempt,
        electricity_basis=electricity_basis,
    )


def trajectory(
    result: PlantResult,
    scenario: Scenario,
    years: Sequence[int] | None = None,
    ets_path: Mapping[int, float] | None = None,
    *,
    basis: str = ACTUAL,
    recognise_actual_electricity: bool = False,
    mass_t: float | None = None,
) -> list[Declaration]:
    """Project the bill across the phase-in, optionally with an ETS price path."""
    years = scenario.cbam.years if years is None else list(years)
    out = []
    for year in years:
        price = None if ets_path is None else ets_path.get(year)
        out.append(
            declare(
                result,
                scenario,
                basis=basis,
                year=year,
                ets_price_eur_per_t=price,
                recognise_actual_electricity=recognise_actual_electricity,
                mass_t=mass_t,
            )
        )
    return out


def ets_price_path(
    start_price: float,
    years: Sequence[int],
    annual_growth: float = 0.06,
    base_year: int | None = None,
) -> dict[int, float]:
    """A simple geometric ETS price path, used only for scenario work."""
    base = min(years) if base_year is None else base_year
    return {y: start_price * (1.0 + annual_growth) ** (y - base) for y in years}


def basis_comparison(
    result: PlantResult,
    scenario: Scenario,
    *,
    year: int | None = None,
    recognise_actual_electricity: bool = False,
) -> dict[str, float]:
    """What verified actual values are worth against the default values.

    Returns the two bills and the saving, which is the business case for
    building an emissions monitoring system at all.
    """
    actual = declare(
        result,
        scenario,
        basis=ACTUAL,
        year=year,
        recognise_actual_electricity=recognise_actual_electricity,
    )
    default = declare(result, scenario, basis=DEFAULT, year=year)
    saving = default.net_cost_eur - actual.net_cost_eur
    return {
        "see_actual": actual.see_declared,
        "see_default": default.see_declared,
        "cost_actual_eur": actual.net_cost_eur,
        "cost_default_eur": default.net_cost_eur,
        "saving_eur": saving,
        "saving_share": (
            saving / default.net_cost_eur if default.net_cost_eur > 0 else 0.0
        ),
    }


def phase_in_exposure(
    see_declared: float,
    benchmark: float,
    cbam: CbamParams,
    years: Sequence[int] | None = None,
) -> list[dict[str, float]]:
    """Why "2.5% in 2026" is not what a high-carbon exporter actually pays.

    The headline phase-in applies to the *benchmark*, not to a shipment's own
    emissions.  The free allocation adjustment deducts
    ``CBAM factor x CSCF x benchmark`` per tonne, so an installation emitting
    more than the benchmark is liable for the excess from the very first year.
    An installation at or below the benchmark really does start near 2.5%.

    Returns, per year, the headline payable share and the share of this
    installation's own gross embedded emissions that is actually liable.
    """
    years = cbam.years if years is None else list(years)
    rows = []
    for year in years:
        factor = cbam.cbam_factor(year)
        sefa = factor * cbam.cross_sectoral_correction_factor * benchmark
        liable = max(0.0, see_declared - sefa)
        rows.append(
            {
                "year": year,
                "headline_payable_share": 1.0 - factor,
                "liable_share_of_own_emissions": (
                    liable / see_declared if see_declared > 0 else 0.0
                ),
                "sefa": sefa,
                "liable_see": liable,
            }
        )
    return rows
