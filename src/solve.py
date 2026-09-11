"""Solving the feeder and reading results back out of the engine."""

import math

import opendssdirect as dss
import pandas as pd


def load_bus_names() -> set[str]:
    """Bus names that serve at least one load, phase suffix stripped.
    """
    buses: set[str] = set()
    i = dss.Loads.First()
    while i:
        dss.Circuit.SetActiveElement("Load." + dss.Loads.Name())
        buses.add(dss.CktElement.BusNames()[0].split(".")[0].lower())
        i = dss.Loads.Next()
    return buses


def solve_snapshot() -> bool:
    """Run a single power-flow solve at the feeder's current load level."""
    dss.Text.Command("Set Mode=Snapshot")
    dss.Solution.Solve()
    return dss.Solution.Converged()


def get_bus_voltages_pu() -> pd.DataFrame:
    """Per-unit voltage magnitude at every node in the solved circuit."""
    df = pd.DataFrame(
        {"v_pu": dss.Circuit.AllBusMagPu()},
        index=dss.Circuit.AllNodeNames(),
    )
    df.index.name = "node"
    return df


def get_transformer_loading_pct(name: str) -> float:
    """Loading of one transformer as a percentage of its kVA nameplate.

    Apparent power, not real power: windings heat according to current, which
    is indifferent to whether that current is doing useful work. Measured at
    terminal 1, which differs from terminal 2 only by the transformer's losses.

    Args:
        name: transformer name without the class prefix.
    """
    dss.Transformers.Name(name)
    dss.Transformers.Wdg(1)          # ratings are per winding
    nameplate = dss.Transformers.kVA()

    dss.Circuit.SetActiveElement(f"Transformer.{name}")
    pw = dss.CktElement.Powers()     # [P, Q] per conductor, terminal 1 then 2
    half = len(pw) // 2

    apparent = math.hypot(sum(pw[0:half:2]), sum(pw[1:half:2]))
    return 100 * apparent / nameplate


def get_total_power_kw_kvar() -> tuple[float, float]:
    """Total real and reactive power supplied by the source.

    OpenDSS reports circuit total power from the circuit's perspective, so the
    sign is inverted here to give power delivered by the source.
    """
    p, q = dss.Circuit.TotalPower()
    return -p, -q


def run_daily(monitor_xfmr: str = "SubXFMR") -> pd.DataFrame:
    """Solve 24 hourly steps and record the feeder response at each hour.

    Returns a frame indexed by hour with v_min and v_max over load-serving
    buses, v_min_all and v_max_all over every node, transformer loading as a
    percentage of nameplate, and the convergence flag.
    """
    setup = [
        "Set Mode=Daily",         # each Solve() advances the clock and
                                  # re-applies each load's daily LoadShape
        "Set stepsize=1h",
        "Set number=1",           # one step per Solve(), so results can be
                                  # read between steps
        "Set ControlMode=Static", # regulators and cap controls iterate to a
                                  # settled state at each step
        "Set hour=0",             # reset the clock; the sweep calls this
                                  # repeatedly and the clock would otherwise
                                  # keep advancing between runs
    ]
    for cmd in setup:
        dss.Text.Command(cmd)

    node_names = dss.Circuit.AllNodeNames()
    served = load_bus_names()
    served_idx = [k for k, n in enumerate(node_names)
                  if n.split(".")[0].lower() in served]

    rows = []
    for h in range(24):
        dss.Solution.Solve()
        v = dss.Circuit.AllBusMagPu()
        v_served = [v[k] for k in served_idx]
        rows.append({
            # own counter: Solve() advances the engine clock, so reading it
            # back would give the following hour
            "hour": h,
            "v_min": min(v_served),
            "v_max": max(v_served),
            "v_min_all": min(v),
            "v_max_all": max(v),
            "xfmr_pct": get_transformer_loading_pct(monitor_xfmr),
            # recorded rather than raised: at high penetration a failure to
            # converge is a result, not a fault
            "converged": dss.Solution.Converged(),
        })

    return pd.DataFrame(rows).set_index("hour")
