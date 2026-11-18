"""Layer 1 -- the shop-floor carbon model.

The question this module answers is the one an industrial engineer actually
owns: *how much of the carbon in a product comes from making it, and how much
comes from the way the line is run?*

Production is modelled analytically rather than event by event.  Each station
has a capacity, a breakdown availability and a scrap rate; the yield cascade
turns a required number of good parts into the number of parts every upstream
station has to process.  The station whose capacity yields the fewest good
parts sets the line throughput.  Buffer and blocking interactions are
deliberately out of scope -- the discrete-event companion project
(production-line-simulation-simpy) covers those.

The useful part is the energy decomposition.  Running hours split exactly into
value-adding time, speed loss and scrap rework, and the remaining hours split
into breakdown, idle and changeover time.  Multiplying each bucket by the right
power draw gives an energy -- and therefore a carbon -- attribution that sums
to the total without a residual.  That identity is asserted in the tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

from config import SECONDS_PER_HOUR, Factors, Plant, Prices, Scenario

LOSS_BUCKETS = (
    "value_adding",
    "performance",
    "scrap",
    "offcut",
    "downtime",
    "idle",
    "baseload",
)


# ----------------------------------------------------------------- results ---
@dataclass(frozen=True)
class StationResult:
    name: str
    processed_parts: float
    run_h: float
    changeover_h: float
    down_h: float
    idle_h: float
    electricity_mwh: float
    gas_mwh_th: float
    is_bottleneck: bool

    @property
    def utilisation(self) -> float:
        """Share of planned time spent actually processing parts."""
        total = self.run_h + self.changeover_h + self.down_h + self.idle_h
        return self.run_h / total if total > 0 else 0.0


@dataclass(frozen=True)
class PlantResult:
    """One year of simulated production, energy, material and emissions."""

    good_parts: float
    output_t: float
    eu_output_t: float
    starts: float
    stations: tuple[StationResult, ...]
    bottleneck: str

    availability: float
    performance: float
    quality: float

    electricity_mwh: float
    gas_mwh_th: float
    input_steel_t: float
    scrap_t: float

    direct_t_co2: float
    indirect_t_co2: float
    precursor_t_co2: float

    electricity_loss_mwh: Mapping[str, float]
    gas_loss_mwh: Mapping[str, float]
    material_loss_t: Mapping[str, float]

    electricity_cost_eur: float
    gas_cost_eur: float
    steel_cost_eur: float
    scrap_revenue_eur: float

    meta: Mapping[str, object] = field(default_factory=dict)

    # --- headline indicators ------------------------------------------------
    @property
    def oee(self) -> float:
        return self.availability * self.performance * self.quality

    @property
    def total_t_co2(self) -> float:
        return self.direct_t_co2 + self.indirect_t_co2 + self.precursor_t_co2

    @property
    def see_direct(self) -> float:
        """Specific embedded direct emissions, t CO2e per tonne of goods."""
        return self.direct_t_co2 / self.output_t

    @property
    def see_indirect(self) -> float:
        return self.indirect_t_co2 / self.output_t

    @property
    def see_precursor(self) -> float:
        return self.precursor_t_co2 / self.output_t

    @property
    def see_total(self) -> float:
        return self.total_t_co2 / self.output_t

    @property
    def kg_co2e_per_part(self) -> float:
        return self.total_t_co2 * 1000.0 / self.good_parts

    @property
    def kwh_per_part(self) -> float:
        return (self.electricity_mwh + self.gas_mwh_th) * 1000.0 / self.good_parts

    @property
    def energy_cost_eur(self) -> float:
        return self.electricity_cost_eur + self.gas_cost_eur

    @property
    def conversion_cost_eur(self) -> float:
        """Energy plus material, net of scrap sales."""
        return self.energy_cost_eur + self.steel_cost_eur - self.scrap_revenue_eur

    # --- carbon attribution -------------------------------------------------
    def carbon_loss_t_co2(self, factors: Factors) -> dict[str, float]:
        """Split total emissions across the six loss buckets.

        Electricity, fuel and material each carry their own emission factor,
        so the buckets are converted separately and then added.
        """
        out: dict[str, float] = {}
        for bucket in LOSS_BUCKETS:
            out[bucket] = (
                self.electricity_loss_mwh.get(bucket, 0.0) * factors.ef_grid_t_co2_per_mwh
                + self.gas_loss_mwh.get(bucket, 0.0) * factors.ef_gas_t_co2_per_mwh_th
                + self.material_loss_t.get(bucket, 0.0) * factors.ef_precursor_t_co2_per_t
            )
        return out

    def avoidable_share(self, factors: Factors) -> float:
        """Share of emissions that is not value-adding."""
        losses = self.carbon_loss_t_co2(factors)
        return 1.0 - losses["value_adding"] / self.total_t_co2


# ------------------------------------------------------------------- model ---
def yield_cascade(plant: Plant) -> list[float]:
    """For each station, the probability a part processed there becomes good.

    Station *i* only has to survive itself and everything downstream, so the
    factors are the reversed cumulative product of ``1 - scrap_rate``.
    """
    survive: list[float] = []
    running = 1.0
    for station in reversed(plant.stations):
        running *= 1.0 - station.scrap_rate
        survive.append(running)
    survive.reverse()
    return survive


def run_plant(scenario: Scenario) -> PlantResult:
    """Evaluate one year of production for the given scenario."""
    plant, factors, prices = scenario.plant, scenario.factors, scenario.prices

    planned_h = plant.planned_hours_per_year
    changeover_total_h = plant.changeover_hours_per_year
    if changeover_total_h >= planned_h:
        raise ValueError("changeovers consume the whole planned production time")

    survive = yield_cascade(plant)

    # Hours each station could run, after changeovers and breakdowns.
    runnable_h = []
    down_h = []
    for station in plant.stations:
        gross_h = planned_h - changeover_total_h
        runnable_h.append(gross_h * station.availability)
        down_h.append(gross_h * (1.0 - station.availability))

    # Good parts each station's capacity supports; the smallest wins.
    capability = [
        runnable_h[i] * plant.stations[i].capacity_parts_per_hour * survive[i]
        for i in range(len(plant.stations))
    ]
    bottleneck_index = int(np.argmin(capability))
    good_parts = float(capability[bottleneck_index])
    starts = good_parts / survive[0]

    # --- per-station time and energy ---------------------------------------
    station_results: list[StationResult] = []
    elec_loss = {bucket: 0.0 for bucket in LOSS_BUCKETS}
    gas_loss = {bucket: 0.0 for bucket in LOSS_BUCKETS}

    for i, station in enumerate(plant.stations):
        processed = good_parts / survive[i]
        run_h = processed * station.cycle_time_s / (
            SECONDS_PER_HOUR * station.performance
        )
        idle_h = max(0.0, runnable_h[i] - run_h)

        # Exact three-way split of running hours.
        ideal_h = good_parts * station.cycle_time_s / SECONDS_PER_HOUR
        performance_h = ideal_h * (1.0 / station.performance - 1.0)
        scrap_h = run_h - ideal_h - performance_h

        elec_loss["value_adding"] += station.power_run_kw * ideal_h / 1000.0
        elec_loss["performance"] += station.power_run_kw * performance_h / 1000.0
        elec_loss["scrap"] += station.power_run_kw * scrap_h / 1000.0
        elec_loss["downtime"] += station.power_down_kw * down_h[i] / 1000.0
        elec_loss["idle"] += (
            station.power_idle_kw * (idle_h + changeover_total_h) / 1000.0
        )

        gas_loss["value_adding"] += station.gas_run_kw * ideal_h / 1000.0
        gas_loss["performance"] += station.gas_run_kw * performance_h / 1000.0
        gas_loss["scrap"] += station.gas_run_kw * scrap_h / 1000.0
        gas_loss["downtime"] += station.gas_idle_kw * down_h[i] / 1000.0
        gas_loss["idle"] += station.gas_idle_kw * (idle_h + changeover_total_h) / 1000.0

        station_elec = (
            station.power_run_kw * run_h
            + station.power_idle_kw * (idle_h + changeover_total_h)
            + station.power_down_kw * down_h[i]
        ) / 1000.0
        station_gas = (
            station.gas_run_kw * run_h
            + station.gas_idle_kw * (idle_h + changeover_total_h + down_h[i])
        ) / 1000.0

        station_results.append(
            StationResult(
                name=station.name,
                processed_parts=processed,
                run_h=run_h,
                changeover_h=changeover_total_h,
                down_h=down_h[i],
                idle_h=idle_h,
                electricity_mwh=station_elec,
                gas_mwh_th=station_gas,
                is_bottleneck=(i == bottleneck_index),
            )
        )

    # Site services run through the whole planned time.
    elec_loss["baseload"] = (
        (plant.baseload_kw + plant.compressed_air_leak_kw) * planned_h / 1000.0
    )

    electricity_mwh = sum(elec_loss.values())
    gas_mwh_th = sum(gas_loss.values())

    # --- material ----------------------------------------------------------
    input_steel_t = starts * plant.input_mass_kg / 1000.0
    output_t = good_parts * plant.part_mass_kg / 1000.0
    material_loss = {bucket: 0.0 for bucket in LOSS_BUCKETS}
    # Steel splits exactly three ways: what leaves as product, the offcut that
    # nesting and machining never put into a part, and the parts that were
    # rejected and took their whole blank with them.
    material_loss["value_adding"] = output_t
    material_loss["offcut"] = good_parts * (plant.input_mass_kg - plant.part_mass_kg) / 1000.0
    material_loss["scrap"] = (starts - good_parts) * plant.input_mass_kg / 1000.0
    rejected_steel_t = material_loss["scrap"]
    scrap_t = input_steel_t - output_t

    # --- emissions ---------------------------------------------------------
    direct_t = gas_mwh_th * factors.ef_gas_t_co2_per_mwh_th
    indirect_t = electricity_mwh * factors.ef_grid_t_co2_per_mwh
    precursor_t = input_steel_t * factors.ef_precursor_t_co2_per_t

    # --- OEE ---------------------------------------------------------------
    bn = plant.stations[bottleneck_index]
    bn_result = station_results[bottleneck_index]
    availability = (
        (bn_result.run_h + bn_result.idle_h) / planned_h
    )
    bn_ideal_h = bn_result.processed_parts * bn.cycle_time_s / SECONDS_PER_HOUR
    performance = (
        bn_ideal_h / (bn_result.run_h + bn_result.idle_h)
        if (bn_result.run_h + bn_result.idle_h) > 0
        else 0.0
    )
    quality = survive[bottleneck_index]

    return PlantResult(
        good_parts=good_parts,
        output_t=output_t,
        eu_output_t=output_t * plant.eu_export_share,
        starts=starts,
        stations=tuple(station_results),
        bottleneck=bn.name,
        availability=availability,
        performance=performance,
        quality=quality,
        electricity_mwh=electricity_mwh,
        gas_mwh_th=gas_mwh_th,
        input_steel_t=input_steel_t,
        scrap_t=scrap_t,
        direct_t_co2=direct_t,
        indirect_t_co2=indirect_t,
        precursor_t_co2=precursor_t,
        electricity_loss_mwh=elec_loss,
        gas_loss_mwh=gas_loss,
        material_loss_t=material_loss,
        electricity_cost_eur=electricity_mwh * prices.electricity_eur_per_mwh,
        gas_cost_eur=gas_mwh_th * prices.gas_eur_per_mwh_th,
        steel_cost_eur=input_steel_t * prices.steel_eur_per_t,
        scrap_revenue_eur=scrap_t * prices.scrap_sale_eur_per_t,
        meta={
            "planned_hours": planned_h,
            "changeover_hours": changeover_total_h,
            "rejected_steel_t": rejected_steel_t,
            "offcut_steel_t": material_loss["offcut"],
            "material_yield": output_t / input_steel_t,
        },
    )


# ------------------------------------------------------- Monte Carlo spread ---
def _gamma_sample(rng: np.random.Generator, mean: float, cv: float) -> float:
    """Draw from a gamma distribution with the given mean and variability.

    A coefficient of variation of zero means "no variability", which the gamma
    sampler cannot express -- the shape parameter would be infinite.  Returning
    the mean directly is the fix for a crash this project family hit before.
    """
    if cv <= 0 or mean <= 0:
        return mean
    shape = 1.0 / (cv * cv)
    return float(rng.gamma(shape, mean / shape))


def sample_plant(scenario: Scenario, rng: np.random.Generator, cv: float = 0.25) -> Scenario:
    """Perturb MTBF, MTTR and scrap rates to represent year-to-year spread."""
    from dataclasses import replace as dc_replace

    def perturb(station):
        return dc_replace(
            station,
            mtbf_h=max(1e-6, _gamma_sample(rng, station.mtbf_h, cv)),
            mttr_h=_gamma_sample(rng, station.mttr_h, cv),
            scrap_rate=min(0.5, _gamma_sample(rng, station.scrap_rate, cv)),
        )

    return dc_replace(scenario, plant=scenario.plant.map_stations(perturb))


def monte_carlo(
    scenario: Scenario,
    seeds: Sequence[int],
    cv: float = 0.25,
) -> list[PlantResult]:
    """Run the plant once per seed with perturbed reliability and scrap."""
    results = []
    for seed in seeds:
        rng = np.random.default_rng(seed)
        results.append(run_plant(sample_plant(scenario, rng, cv=cv)))
    return results


def mean_ci(values: Sequence[float], confidence: float = 0.95) -> tuple[float, float]:
    """Return the mean and the half-width of a normal-approximation interval."""
    arr = np.asarray(list(values), dtype=float)
    if arr.size < 2:
        return float(arr.mean()), 0.0
    z = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}.get(confidence, 1.96)
    return float(arr.mean()), float(z * arr.std(ddof=1) / np.sqrt(arr.size))
