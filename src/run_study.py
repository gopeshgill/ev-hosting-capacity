"""Entry point: runs every scenario, writes data/sweep_all.csv, prints the summary.

    python src/run_study.py
"""

from pathlib import Path

import pandas as pd

from study import run_sweep, run_sweep_battery, threshold_pct

XFMR_KVA = 5000


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    feeder_master = root / "feeder" / "IEEE123" / "IEEE123Master.dss"
    out_csv = root / "data" / "sweep_all.csv"

    # base case plus one run per assumption under test
    runs = [
        ("base",    {}),
        ("kva7500", dict(kva=7500)),      # substation transformer rating
        ("admd2.0", dict(admd_kw=2.0)),   # dwellings per spot load
    ]

    frames = [
        run_sweep(feeder_master, scenario=label, seeds=(1, 2, 3, 4, 5), **kw)
        for label, kw in runs
    ]

    # 1% grid across the thermal crossing, to avoid interpolating over a
    # 10-point gap
    frames.append(run_sweep(
        feeder_master, scenario="fine", seeds=(1, 2, 3, 4, 5),
        penetrations=[0.25, 0.26, 0.27, 0.28, 0.29, 0.30],
    ))

    frames.append(run_sweep_battery(
        feeder_master, kw_rated=900, kwh_rated=2400,
        scenario="battery900", seeds=(1,),
    ))

    sweep = pd.concat(frames, ignore_index=True)
    sweep.to_csv(out_csv, index=False)
    print(f"{len(sweep)} rows -> {out_csv.name}\n")

    print_summary(sweep)
    print_sizing_curve(sweep)


def print_summary(sweep: pd.DataFrame) -> None:
    """Worst hour within each run, then the spread across seeds, then thresholds."""
    per_run = (
        sweep.groupby(["scenario", "penetration_pct", "seed"])
        .agg(v_min=("v_min", "min"), peak_pct=("xfmr_pct", "max"))
        .reset_index()
    )
    peak = per_run.pivot_table(index="penetration_pct", columns="scenario",
                               values="peak_pct", aggfunc="max")
    volt = per_run.pivot_table(index="penetration_pct", columns="scenario",
                               values="v_min", aggfunc="min")

    print("Peak transformer loading %")
    print(peak.round(1).to_string(), "\n")
    print("Minimum voltage pu (load-serving buses)")
    print(volt.round(4).to_string(), "\n")

    print(f"{'scenario':12s} {'thermal':>9s} {'voltage':>9s}")
    for sc in peak.columns:
        t = threshold_pct(peak[sc], 100.0, rising=True)
        v = threshold_pct(volt[sc], 0.95, rising=False)
        print(f"{sc:12s} {('%.1f%%' % t) if t else '  none':>9s} "
              f"{('%.1f%%' % v) if v else '  none':>9s}")


def print_sizing_curve(sweep: pd.DataFrame) -> None:
    """What a battery would need to hold each penetration level.

    Power rating comes from worst_kva; energy rating from energy_kwh adjusted
    for the usable fraction and discharge efficiency.
    """
    b = sweep[(sweep.scenario == "base") & (sweep.seed == 1)].copy()
    b["over_kva"] = ((b.xfmr_pct - 100) / 100 * XFMR_KVA).clip(lower=0)
    sizing = b.groupby("penetration_pct").agg(
        hours_over=("over_kva", lambda s: int((s > 0).sum())),
        worst_kva=("over_kva", "max"),
        energy_kwh=("over_kva", "sum"),
    )
    print("\nBattery sizing curve (base scenario)")
    print(sizing.round(0).to_string())


if __name__ == "__main__":
    main()
