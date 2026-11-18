"""Typed configuration objects and the default (simulated) scenario loader.

Every number used by the model lives in ``data/parameters.json`` so that the
code carries no hidden constants.  All of it is simulated and illustrative --
see the ``_README`` key of that file.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from typing import Mapping

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PARAMETERS_PATH = os.path.join(DATA_DIR, "parameters.json")

SECONDS_PER_HOUR = 3600.0


# ---------------------------------------------------------------- station ---
@dataclass(frozen=True)
class Station:
    """One workstation of the fabrication line.

    ``performance`` folds minor stops and speed loss into a single OEE-style
    factor: the effective cycle time is ``cycle_time_s / performance``.
    ``scrap_rate`` is the share of the parts *processed at this station* that
    are rejected there.
    """

    name: str
    cycle_time_s: float
    performance: float
    mtbf_h: float
    mttr_h: float
    scrap_rate: float
    power_run_kw: float
    power_idle_kw: float
    power_down_kw: float
    gas_run_kw: float = 0.0
    gas_idle_kw: float = 0.0

    def __post_init__(self) -> None:
        if self.cycle_time_s <= 0:
            raise ValueError(f"{self.name}: cycle_time_s must be positive")
        if not 0.0 < self.performance <= 1.0:
            raise ValueError(f"{self.name}: performance must be in (0, 1]")
        if not 0.0 <= self.scrap_rate < 1.0:
            raise ValueError(f"{self.name}: scrap_rate must be in [0, 1)")
        if self.mtbf_h <= 0 or self.mttr_h < 0:
            raise ValueError(f"{self.name}: MTBF must be positive, MTTR non-negative")

    @property
    def availability(self) -> float:
        """Uptime share from breakdowns only, ``MTBF / (MTBF + MTTR)``."""
        return self.mtbf_h / (self.mtbf_h + self.mttr_h)

    @property
    def capacity_parts_per_hour(self) -> float:
        """Parts the station can process per *running* hour."""
        return SECONDS_PER_HOUR / self.cycle_time_s * self.performance


# ------------------------------------------------------------------ plant ---
@dataclass(frozen=True)
class Plant:
    """The fabrication line plus the site services that surround it."""

    name: str
    good: str
    cn_code: str
    cbam_sector: str
    production_route: str
    stations: tuple[Station, ...]
    shifts_per_day: float
    hours_per_shift: float
    days_per_year: float
    changeovers_per_day: float
    setup_time_min: float
    baseload_kw: float
    compressed_air_leak_kw: float
    part_mass_kg: float
    input_mass_kg: float
    eu_export_share: float

    def __post_init__(self) -> None:
        if not self.stations:
            raise ValueError("a plant needs at least one station")
        if self.input_mass_kg < self.part_mass_kg:
            raise ValueError("input mass per part cannot be below finished part mass")
        if not 0.0 <= self.eu_export_share <= 1.0:
            raise ValueError("eu_export_share must be in [0, 1]")

    @property
    def planned_hours_per_year(self) -> float:
        """Planned production time: the OEE denominator."""
        return self.shifts_per_day * self.hours_per_shift * self.days_per_year

    @property
    def changeover_hours_per_year(self) -> float:
        return self.changeovers_per_day * self.days_per_year * self.setup_time_min / 60.0

    def with_station(self, index: int, **changes) -> "Plant":
        """Return a copy of the plant with one station field changed."""
        stations = list(self.stations)
        stations[index] = replace(stations[index], **changes)
        return replace(self, stations=tuple(stations))

    def map_stations(self, fn) -> "Plant":
        """Return a copy where ``fn(station)`` replaced every station."""
        return replace(self, stations=tuple(fn(s) for s in self.stations))


# ---------------------------------------------------------------- factors ---
@dataclass(frozen=True)
class Factors:
    """Emission factors, in tonnes of CO2e per unit of energy or material."""

    ef_grid_t_co2_per_mwh: float
    ef_grid_country_default_t_co2_per_mwh: float
    ef_gas_t_co2_per_mwh_th: float
    ef_precursor_t_co2_per_t: float
    ef_precursor_scrap_eaf_t_co2_per_t: float
    sources: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Prices:
    electricity_eur_per_mwh: float
    gas_eur_per_mwh_th: float
    steel_eur_per_t: float
    steel_scrap_eaf_premium_eur_per_t: float
    scrap_sale_eur_per_t: float
    ets_price_eur_per_t: float
    origin_carbon_price_eur_per_t: float
    origin_carbon_price_coverage: float
    discount_rate: float
    sources: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CbamParams:
    """The regulatory dials of the CBAM calculation.

    ``cbam_factor_by_year`` is the share of EU ETS free allocation still
    granted (0.975 in 2026), *not* the payable share.  See ``payable_share``.
    """

    year: int
    cbam_factor_by_year: Mapping[int, float]
    default_value_markup_by_year: Mapping[int, float]
    cross_sectoral_correction_factor: float
    benchmarks_t_co2_per_t: Mapping[str, float]
    default_values_t_co2_per_t: Mapping[str, float]
    de_minimis_tonnes_per_year: float
    notes: Mapping[str, str] = field(default_factory=dict)

    def cbam_factor(self, year: int | None = None) -> float:
        year = self.year if year is None else year
        years = sorted(self.cbam_factor_by_year)
        if year <= years[0]:
            return self.cbam_factor_by_year[years[0]]
        if year >= years[-1]:
            return self.cbam_factor_by_year[years[-1]]
        return self.cbam_factor_by_year[year]

    def payable_share(self, year: int | None = None) -> float:
        """Share of benchmark-level emissions no longer covered by free allocation."""
        return 1.0 - self.cbam_factor(year)

    def default_value_markup(self, year: int | None = None) -> float:
        year = self.year if year is None else year
        years = sorted(self.default_value_markup_by_year)
        if year <= years[0]:
            return self.default_value_markup_by_year[years[0]]
        if year >= years[-1]:
            return self.default_value_markup_by_year[years[-1]]
        return self.default_value_markup_by_year[year]

    def benchmark(self, route: str) -> float:
        if route not in self.benchmarks_t_co2_per_t:
            raise KeyError(f"no CBAM benchmark for production route {route!r}")
        return self.benchmarks_t_co2_per_t[route]

    def default_value(self, route: str) -> float:
        if route not in self.default_values_t_co2_per_t:
            raise KeyError(f"no CBAM default value for production route {route!r}")
        return self.default_values_t_co2_per_t[route]

    @property
    def years(self) -> list[int]:
        return sorted(self.cbam_factor_by_year)


@dataclass(frozen=True)
class Scenario:
    """Everything one model run needs."""

    plant: Plant
    factors: Factors
    prices: Prices
    cbam: CbamParams


# ----------------------------------------------------------------- loader ---
def load_scenario(path: str = PARAMETERS_PATH) -> Scenario:
    """Read ``data/parameters.json`` into typed objects."""
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return scenario_from_dict(raw)


def scenario_from_dict(raw: Mapping) -> Scenario:
    plant_raw = raw["plant"]
    stations = tuple(
        Station(
            name=s["name"],
            cycle_time_s=s["cycle_time_s"],
            performance=s["performance"],
            mtbf_h=s["mtbf_h"],
            mttr_h=s["mttr_h"],
            scrap_rate=s["scrap_rate"],
            power_run_kw=s["power_run_kw"],
            power_idle_kw=s["power_idle_kw"],
            power_down_kw=s["power_down_kw"],
            gas_run_kw=s.get("gas_run_kw", 0.0),
            gas_idle_kw=s.get("gas_idle_kw", 0.0),
        )
        for s in plant_raw["stations"]
    )
    plant = Plant(
        name=plant_raw["name"],
        good=plant_raw["good"],
        cn_code=plant_raw["cn_code"],
        cbam_sector=plant_raw["cbam_sector"],
        production_route=plant_raw["production_route"],
        stations=stations,
        shifts_per_day=plant_raw["shifts_per_day"],
        hours_per_shift=plant_raw["hours_per_shift"],
        days_per_year=plant_raw["days_per_year"],
        changeovers_per_day=plant_raw["changeovers_per_day"],
        setup_time_min=plant_raw["setup_time_min"],
        baseload_kw=plant_raw["baseload_kw"],
        compressed_air_leak_kw=plant_raw["compressed_air_leak_kw"],
        part_mass_kg=plant_raw["part_mass_kg"],
        input_mass_kg=plant_raw["input_mass_kg"],
        eu_export_share=plant_raw["eu_export_share"],
    )

    f = raw["factors"]
    factors = Factors(
        ef_grid_t_co2_per_mwh=f["ef_grid_t_co2_per_mwh"],
        ef_grid_country_default_t_co2_per_mwh=f.get(
            "ef_grid_country_default_t_co2_per_mwh", f["ef_grid_t_co2_per_mwh"]
        ),
        ef_gas_t_co2_per_mwh_th=f["ef_gas_t_co2_per_mwh_th"],
        ef_precursor_t_co2_per_t=f["ef_precursor_t_co2_per_t"],
        ef_precursor_scrap_eaf_t_co2_per_t=f["ef_precursor_scrap_eaf_t_co2_per_t"],
        sources={k: v for k, v in f.items() if k.endswith("_source")},
    )

    p = raw["prices"]
    prices = Prices(
        electricity_eur_per_mwh=p["electricity_eur_per_mwh"],
        gas_eur_per_mwh_th=p["gas_eur_per_mwh_th"],
        steel_eur_per_t=p["steel_eur_per_t"],
        steel_scrap_eaf_premium_eur_per_t=p["steel_scrap_eaf_premium_eur_per_t"],
        scrap_sale_eur_per_t=p["scrap_sale_eur_per_t"],
        ets_price_eur_per_t=p["ets_price_eur_per_t"],
        origin_carbon_price_eur_per_t=p["origin_carbon_price_eur_per_t"],
        origin_carbon_price_coverage=p.get("origin_carbon_price_coverage", 0.0),
        discount_rate=p["discount_rate"],
        sources={k: v for k, v in p.items() if k.endswith("_source")},
    )

    c = raw["cbam"]
    cbam = CbamParams(
        year=c["year"],
        cbam_factor_by_year={int(k): v for k, v in c["cbam_factor_by_year"].items()},
        default_value_markup_by_year={
            int(k): v for k, v in c["default_value_markup_by_year"].items()
        },
        cross_sectoral_correction_factor=c["cross_sectoral_correction_factor"],
        benchmarks_t_co2_per_t=dict(c["benchmarks_t_co2_per_t"]),
        default_values_t_co2_per_t=dict(c["default_values_t_co2_per_t"]),
        de_minimis_tonnes_per_year=c["de_minimis_tonnes_per_year"],
        notes={k: v for k, v in c.items() if k.endswith("_note")},
    )

    return Scenario(plant=plant, factors=factors, prices=prices, cbam=cbam)


SIMULATED_DATA_NOTICE = (
    "Simulated data. The plant, its parameters and the CBAM benchmark and "
    "default values in this repository are illustrative placeholders, not "
    "official figures."
)
