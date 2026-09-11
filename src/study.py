"""Scenario assembly, penetration sweeps, and threshold extraction."""

from pathlib import Path

import opendssdirect as dss
import pandas as pd

from evs import add_ev_loads, assign_evs, houses_per_load
from feeder import add_substation_transformer, apply_load_shape, build_load_shape, compile_feeder
from solve import run_daily
from storage import add_battery, battery_dispatch


def build_scenario(
    master_path: str | Path,
    penetration: float = 0.0,
    seed: int = 1,
    kva: float = 5000,
    xhl_pct: float = 8.0,
    admd_kw: float = 1.38,
    peak_hour: int = 17,
) -> tuple[pd.DataFrame, pd.Series, int]:
    """Build one complete scenario from a clean engine.

    Args:
        master_path: path to IEEE123Master.dss.
        penetration: fraction of dwellings with a charger.
        seed: RNG seed for charger placement.
        kva, xhl_pct: substation transformer rating and impedance.
        admd_kw: after-diversity maximum demand per dwelling.
        peak_hour: hour of the evening load peak.

    Returns:
        (houses per load, EV counts, number of EV Load objects created).
    """
    compile_feeder(master_path)
    add_substation_transformer(kva=kva, xhl_pct=xhl_pct)
    apply_load_shape(build_load_shape(peak_hour=peak_hour))

    hpl = houses_per_load(admd_kw=admd_kw)
    ev_counts = assign_evs(hpl, penetration, seed)

    n_ev = 0
    if penetration > 0:
        n_ev = add_ev_loads(hpl, ev_counts)

        # fires if a BatchEdit ran after the EV loads were created
        first_ev = next(nm for nm, c in ev_counts.items() if c > 0)
        dss.Loads.Name(f"ev_{first_ev}")
        assert dss.Loads.Daily().lower() == "evshape", (
            f"ev_{first_ev} has daily='{dss.Loads.Daily()}', expected 'evshape'"
        )

    return hpl, ev_counts, n_ev


def run_sweep(
    master_path: str | Path,
    penetrations: list[float] | None = None,
    seeds: tuple[int, ...] = (1, 2, 3, 4, 5),
    scenario: str = "base",
    monitor_xfmr: str = "SubXFMR",
    **scenario_kwargs,
) -> pd.DataFrame:
    """Sweep EV penetration with several random placements at each level.

    Args:
        master_path: path to IEEE123Master.dss.
        penetrations: fractions to sweep; defaults to 0.0 to 1.0 by 0.1.
        seeds: RNG seeds for charger placement.
        scenario: label written into the scenario column.
        monitor_xfmr: transformer whose loading is recorded.
        **scenario_kwargs: forwarded to build_scenario, which is how the
            sensitivity runs vary one assumption at a time.
    """
    if penetrations is None:
        penetrations = [round(0.1 * i, 1) for i in range(11)]

    frames = []
    for pen in penetrations:
        for seed in seeds:
            _, ev_counts, _ = build_scenario(
                master_path, penetration=pen, seed=seed, **scenario_kwargs
            )
            day = run_daily(monitor_xfmr).reset_index()
            day.insert(0, "n_evs", int(ev_counts.sum()))
            day.insert(0, "seed", seed)
            day.insert(0, "penetration_pct", int(round(pen * 100)))
            day.insert(0, "scenario", scenario)
            frames.append(day)

    return pd.concat(frames, ignore_index=True)


def run_with_battery(
    master_path: str | Path,
    penetration: float,
    kw_rated: float,
    kwh_rated: float,
    seed: int = 1,
    monitor_xfmr: str = "SubXFMR",
    **scenario_kwargs,
) -> pd.DataFrame:
    """Measure the overload, then dispatch a battery against it.
    """
    build_scenario(master_path, penetration=penetration, seed=seed, **scenario_kwargs)
    raw = run_daily(monitor_xfmr)["xfmr_pct"].to_numpy()

    build_scenario(master_path, penetration=penetration, seed=seed, **scenario_kwargs)
    add_battery(kw_rated, kwh_rated, battery_dispatch(raw, kw_rated))
    return run_daily(monitor_xfmr)


def run_sweep_battery(
    master_path: str | Path,
    kw_rated: float,
    kwh_rated: float,
    penetrations: list[float] | None = None,
    seeds: tuple[int, ...] = (1,),
    scenario: str = "battery900",
    monitor_xfmr: str = "SubXFMR",
    **scenario_kwargs,
) -> pd.DataFrame:
    """Sweep EV penetration with a substation battery peak-shaving.
    """
    if penetrations is None:
        penetrations = [round(0.1 * i, 1) for i in range(11)]

    frames = []
    for pen in penetrations:
        for seed in seeds:
            day = run_with_battery(master_path, pen, kw_rated, kwh_rated,
                                   seed=seed, monitor_xfmr=monitor_xfmr,
                                   **scenario_kwargs).reset_index()
            day.insert(0, "n_evs", 0)
            day.insert(0, "seed", seed)
            day.insert(0, "penetration_pct", int(round(pen * 100)))
            day.insert(0, "scenario", scenario)
            frames.append(day)

    return pd.concat(frames, ignore_index=True)


def threshold_pct(curve: pd.Series, limit: float, rising: bool) -> float | None:
    """Penetration at which a curve first crosses a limit.

    Args:
        curve: worst-case metric indexed by penetration_pct, ascending.
        limit: 100.0 for transformer loading, 0.95 for the Range A floor.
        rising: True if the metric increases with penetration.

    Returns:
        Penetration percentage, or None if the limit is never crossed.
    """
    curve = curve.dropna()
    x = curve.index.to_numpy(dtype=float)
    y = curve.to_numpy(dtype=float)
    for i in range(len(x) - 1):
        a, b = y[i], y[i + 1]
        crossed = (a < limit <= b) if rising else (a > limit >= b)
        if crossed:
            return float(x[i] + (x[i + 1] - x[i]) * (limit - a) / (b - a))
    return None
