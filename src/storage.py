"""Substation battery: dispatch shape and Storage element."""

import numpy as np
import opendssdirect as dss


def battery_dispatch(
    loading_pct: np.ndarray,
    kw_rated: float,
    target_pct: float = 98.0,
    charge_hours: tuple[int, ...] = (1, 2, 3, 4, 5),
    charge_rate: float = 0.6,
    xfmr_kva: float = 5000.0,
) -> list[float]:
    """Build a 24-point dispatch shape from a measured loading profile.

    Positive values discharge, negative charge, as a fraction of the kW
    rating. Dispatch is derived from a profile measured beforehand.

    OpenDSS's StorageController in PeakShave mode was tried first and
    it emptied the battery overnight and made it sit at reserve
    through the peak demand. Explicit dispatch is used instead.

    Args:
        loading_pct: 24 hourly loading percentages with no battery.
        kw_rated: battery power rating.
        target_pct: loading the dispatch aims to hold.
        charge_hours: hours in which to recharge.
        charge_rate: charge power as a fraction of the kW rating.
        xfmr_kva: transformer nameplate, for converting percent to kVA.
    """
    over_kw = np.clip((loading_pct - target_pct) / 100 * xfmr_kva, 0, None)
    disp = np.round(np.clip(over_kw / kw_rated, 0, 1), 3)
    for h in charge_hours:
        disp[h] = -charge_rate
    return list(disp)


def add_battery(
    kw_rated: float,
    kwh_rated: float,
    dispatch: list[float],
    bus: str = "150r",
    shape_name: str = "battdisp",
) -> None:
    """Add one substation battery driven by an explicit dispatch shape.

    Sited at the feeder head, immediately downstream of the constrained
    transformer.
    Starting at 10% state of charge makes the simulation consistent.
    The battery will charge overnight, and discharge at the evening peak.
    """
    mult = ", ".join(str(x) for x in dispatch)
    dss.Text.Command(f"New LoadShape.{shape_name} npts=24 interval=1 mult=[{mult}]")
    dss.Text.Command(
        f"New Storage.batt bus1={bus} phases=3 kV=4.16 "
        f"kWrated={kw_rated} kWhrated={kwh_rated} "
        f"%stored=10 %reserve=10 "
        f"%EffCharge=93 %EffDischarge=93 "
        f"%IdlingkW=0 "
        f"dispmode=follow daily={shape_name}"
    )
