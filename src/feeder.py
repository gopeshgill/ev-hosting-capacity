"""Construction of the IEEE 123-bus feeder model and its load shape."""

from pathlib import Path

import numpy as np
import opendssdirect as dss


def compile_feeder(master_path: str | Path) -> None:
    """Load the feeder into the DSS engine from its master file.
    """
    p = Path(master_path).as_posix()
    dss.Text.Command(f"Compile [{p}]")

    if dss.Circuit.NumBuses() == 0:
        raise RuntimeError(f"Compile failed - no circuit loaded from {p}")


def add_substation_transformer(kva: float = 5000, xhl_pct: float = 8.0) -> None:
    """Insert a 72/4.16 kV substation transformer between the source and bus 150.

    Args:
        kva: transformer rating.
        xhl_pct: percent leakage impedance, on the transformer's own base.
    """
    cmds = [
        # move the source up to transmission voltage so the transformer has
        # something to sit between
        "Edit Vsource.source bus1=sourcebus basekv=72 pu=1.0",
        f"New Transformer.SubXFMR phases=3 windings=2 XHL={xhl_pct} "
        f"buses=[sourcebus, 150] conns=[delta, wye] "
        f"kvs=[72, 4.16] kvas=[{kva}, {kva}] %Rs=[0.4, 0.4]",
        # 72 kV is a new voltage level; without redeclaring, every bus above
        # the transformer reports meaningless per-unit values
        "Set VoltageBases=[72, 4.16, 0.48]",
        "CalcVoltageBases",
    ]
    for cmd in cmds:
        dss.Text.Command(cmd)


def build_load_shape(peak_hour: int = 17) -> list[float]:
    """Construct a 24-point residential winter weekday load shape.

    Peak timing (hour 17) is derived from AESO hourly load data for the Edmonton region.

    Args:
        peak_hour: hour of the evening peak.

    Returns:
        24 hourly multipliers.
    """
    anchor_h = [0, 3, 6, 8, 10, 14, 16, peak_hour, 19, 21, 23]
    anchor_y = [0.46, 0.35, 0.48, 0.70, 0.55, 0.50, 0.80, 1.00, 0.94, 0.72, 0.52]

    return [round(v, 2) for v in np.interp(np.arange(24), anchor_h, anchor_y)]


def apply_load_shape(shape: list[float], name: str = "resi") -> None:
    """Create a LoadShape and attach it to every load on the feeder.
    """
    mult = ", ".join(str(x) for x in shape)
    dss.Text.Command(f"New LoadShape.{name} npts=24 interval=1 mult=[{mult}]")
    dss.Text.Command(f"BatchEdit Load..* daily={name}")
