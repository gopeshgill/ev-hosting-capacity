"""EV population: splitting spot loads into dwellings, placing and injecting chargers."""

import numpy as np
import opendssdirect as dss
import pandas as pd


# Synthetic charging profile: fraction of the installed EV fleet drawing power,
# by hour. Follows uncontrolled charge-on-arrival behaviour - plug in on
# arrival, charge until done - which is the same behavioural model used in the
# literature, though the arrival distribution here is assumed rather than
# derived from travel survey data.
#
# Calibrated against two checks. The values sum to 1.46 fleet-hours, so each
# vehicle takes 1.46 * 7.2 = 10.5 kWh/day, consistent with roughly 50 km/day at
# 0.2 kWh/km. Peak coincidence is 0.20 at hour 18: one charger in five drawing
# power at the worst moment.
#
# Peak coincidence is the single assumption sitting most directly on top of the
# result, since EV load at the binding hour scales with it, and it is the one
# assumption this study does not test.
EV_SHAPE = [0.06, 0.05, 0.04, 0.03, 0.02, 0.02,   # 00-05
            0.02, 0.02, 0.02, 0.01, 0.01, 0.01,   # 06-11
            0.02, 0.02, 0.02, 0.03, 0.06, 0.14,   # 12-17
            0.20, 0.19, 0.16, 0.13, 0.10, 0.08]   # 18-23


def houses_per_load(admd_kw: float = 1.38) -> pd.DataFrame:
    """Split each aggregated spot load into a number of dwellings.

    One Load object in a test feeder is a spot load: the aggregated demand at
    one primary node, here representing 14-152 dwellings fed through service
    transformers the model does not contain.

    ADMD (After Diversity Maximum Demand) is peak demand per customer once
    diversity is accounted for. The 1.38 kW default is 600 kWh/month per
    residential customer (Alberta MSA) converted to peak using this study's
    own load factor of 0.605.

    Args:
        admd_kw: after-diversity maximum demand per dwelling.

    Returns:
        DataFrame indexed by load name with columns bus1 (including phase
        suffix), phases, kv, kw, is_delta and houses.
    """
    rows = []
    i = dss.Loads.First()
    while i:
        name = dss.Loads.Name()
        kw = dss.Loads.kW()
        kv = dss.Loads.kV()
        is_delta = dss.Loads.IsDelta()

        dss.Circuit.SetActiveElement("Load." + name)
        rows.append({
            "name": name,
            # the phase suffix is retained: it determines which phase the
            # dwellings, and therefore the chargers, sit on
            "bus1": dss.CktElement.BusNames()[0],
            "phases": dss.CktElement.NumPhases(),
            "kv": kv,
            "kw": kw,
            "is_delta": is_delta,
            "houses": round(kw / admd_kw),
        })
        i = dss.Loads.Next()

    df = pd.DataFrame(rows).set_index("name")

    # a load that fails to construct is dropped silently, taking its demand
    # with it, so compare what was built against what the engine holds
    assert len(df) == dss.Loads.Count(), (
        f"load count mismatch: built {len(df)}, engine reports {dss.Loads.Count()}"
    )
    return df


def assign_evs(hpl: pd.DataFrame, penetration: float, seed: int) -> pd.Series:
    """Randomly place Level 2 chargers on a fraction of the dwellings.

    Sampling is without replacement from the pool of all dwellings, so the
    total is exactly round(n_dwellings * penetration) and no dwelling receives
    two chargers. Placement is random, so the count at each load varies between
    seeds while the total does not.

    Args:
        hpl: output of houses_per_load().
        penetration: fraction of dwellings with a charger.
        seed: RNG seed; the same seed reproduces the same placement.

    Returns:
        Integer EV count per load, indexed like hpl, zeros included.
    """
    # one entry per dwelling, holding the name of the load it belongs to
    pool = np.repeat(hpl.index.values, hpl["houses"].values)
    n = round(len(pool) * penetration)

    rng = np.random.default_rng(seed)
    chosen = rng.choice(pool, size=n, replace=False)

    counts = pd.Series(chosen).value_counts()
    return counts.reindex(hpl.index, fill_value=0).astype(int)


def add_ev_loads(
    hpl: pd.DataFrame,
    ev_counts: pd.Series,
    ev_shape: list[float] | None = None,
    kw_per_charger: float = 7.2,
    shape_name: str = "evshape",
    vminpu: float = 0.85,
) -> int:
    """Inject aggregated EV charging load, one Load object per host load.

    Each EV load mirrors its host's bus, phase count, kV and connection, so
    the chargers sit electrically where the dwellings are.

    Args:
        hpl: output of houses_per_load().
        ev_counts: output of assign_evs().
        ev_shape: hourly fractions of the fleet charging; defaults to EV_SHAPE.
        kw_per_charger: Level 2 charger rating.
        shape_name: DSS LoadShape name for the charging profile.
        vminpu: voltage below which OpenDSS reverts a load to constant
            impedance. The 0.95 default would make chargers shed demand across
            the whole region of interest, so it is lowered.

    Returns:
        Number of EV Load objects created.
    """
    if ev_shape is None:
        ev_shape = EV_SHAPE

    mult = ", ".join(str(x) for x in ev_shape)
    dss.Text.Command(f"New LoadShape.{shape_name} npts=24 interval=1 mult=[{mult}]")

    added = 0
    for load_name, n_ev in ev_counts.items():
        if n_ev <= 0:
            continue
        host = hpl.loc[load_name]
        conn = "delta" if host["is_delta"] else "wye"
        dss.Text.Command(
            # named after the host load rather than the bus: several buses
            # carry more than one load object, so bus names would collide
            f"New Load.ev_{load_name} "
            f"bus1={host['bus1']} "
            f"phases={int(host['phases'])} "
            f"conn={conn} "
            f"kV={host['kv']} "
            f"kW={n_ev * kw_per_charger} "
            f"pf=1.0 "        # active power factor correction, near unity
            f"model=1 "       # constant kW: a charger draws its set power
            f"Vminpu={vminpu} "
            f"daily={shape_name}"
        )
        added += 1

    return added
