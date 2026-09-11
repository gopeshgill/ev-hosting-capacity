# EV Hosting Capacity of a Residential Distribution Feeder

How many electric vehicles can a distribution feeder absorb before it violates
voltage or thermal limits — and can a battery defer the upgrade?

Built in OpenDSS, driven from Python, on the IEEE 123-bus test feeder with an
Alberta-derived load profile.

---

## Headline result

| Case | Hosting capacity | Vehicles | Binding constraint |
|---|---|---|---|
| Feeder as-is | **29%** of dwellings | ~730 | Substation transformer, 100% of 5 MVA |
| + 900 kW / 2.4 MWh battery | **51%** | ~1,290 | Same, deferred |

**The feeder is thermally limited, not voltage limited.** Voltage retains
headroom to 64% penetration while the transformer saturates at 29% — the
reverse of the usual assumption in EV hosting-capacity work. Two reasons: EV
load distributes across all 91 nodes rather than concentrating at the weak end
of the feeder, and four voltage regulators actively defend voltage while
nothing defends transformer capacity.

---

## Method

- **Network** — IEEE 123-bus test feeder, 4.16 kV, 132 buses / 278 nodes,
  91 aggregated spot loads totalling 3,490 kW.
- **Engine** — OpenDSS via `OpenDSSDirect.py`, scripted end to end. 6,264
  solved feeder-hours across five scenarios.
- **Substation transformer** — the stock model connects an ideal source
  directly to bus 150, so there is no equipment with a nameplate to overload.
  A 5 MVA, 8% impedance, 72/4.16 kV transformer was added, representing this
  feeder's share of substation capacity.
- **Load shape** — 24-hour residential winter weekday. Peak timing (hour 17,
  elevated 16:00–20:00) measured from AESO hourly load data for the Edmonton
  region, January 2024 weekdays. Normalised to 1.0 at the evening peak,
  because the test feeder's spot loads represent coincident peak demand.
- **EV model** — 7.2 kW Level 2 chargers on a random subset of 2,513
  dwellings (ADMD 1.38 kW/dwelling), five random placements per level.
  Charging follows an uncontrolled home-charging profile peaking at 20%
  fleet coincidence at hour 18.
- **Battery** — one substation-sited unit in peak-shaving dispatch, sized
  from the measured overload profile.

## Validation

The stock feeder was validated before any modification:

| Check | Result |
|---|---|
| Converged | Yes, all 6,264 hours |
| Bus / node count | 132 / 278 |
| Minimum voltage | 0.9747 pu at node `65.1` |
| Peak loading | 79.6% at hour 17 |
| Power balance | 3,519.3 kW load + 96.0 kW losses = 3,615.3 kW source — closes to 0.1 kW |
| Losses | 2.65% of delivered power, within the 2–4% typical of primary distribution |

---

## Findings

**1. Thermal binds first, in every scenario tested.** Even with a 50% larger
transformer, voltage never violates within the swept range.

**2. The result is robust in vehicles, sensitive in percent.** Doubling the
assumed dwellings-per-node changes the threshold from 29% to 42% — but from
734 vehicles to 731. The feeder's limit is in kilowatts; the percentage is
just a denominator.

**3. Transformer rating dominates the answer.** 5 MVA gives 29%; 7.5 MVA
gives 91%. Percent impedance is referenced to the unit's own base, so a larger
transformer also presents 33% less ohmic impedance and improves voltage as a
side effect.

**4. EV charging creates a new peak rather than adding to the old one.** The
feeder peaks at hour 17; charging peaks at 18. Above 20% penetration the
system peak migrates to 18, and the marginal loading per additional EV rises
by 43% — visible as a kink in the sweep curve.

**5. Storage helps thermally but can hurt voltage at moderate penetration.**
The regulators use line drop compensation (`R=3 X=7.5`). A substation battery
reduces current through the regulator, so the regulator infers less downstream
drop and boosts less — leaving the feeder end with slightly *lower* voltage at
40–50% penetration, before thermal relief dominates above 60%.

---

## Assumptions and limitations

Every assumption below is stated with the direction it biases the result.

| Assumption | Basis | Effect on the answer |
|---|---|---|
| 5 MVA substation allocation | 40 MVA bank ÷ 8 feeders; independently, ~3.8 MVA from 4.16 kV getaway ampacity | Dominant. Threshold spans 29–91% across plausible ratings. |
| ADMD 1.38 kW/dwelling | 600 kWh/month (Alberta MSA) ÷ measured load factor 0.605 | Scales the percentage, not the vehicle count. |
| No secondary network | IEEE test feeders model primary only | **Optimistic.** Adds 2–4% voltage drop and hides service-transformer thermal limits, usually the first real constraint. |
| No conductor ampacities | IEEE 123 line codes declare none | **Optimistic.** The 4.16 kV backbone carries 534 A at peak, at the limit of 336 ACSR (~3.8 MVA) — tighter than the modelled 5 MVA. |
| 4.16 kV feeder voltage | Fixed by the benchmark | **Conservative.** Edmonton runs up to 25 kV, where the same load draws one-sixth the current and percent voltage drop falls ~36×. |
| Perfect-foresight battery dispatch | Dispatch derived from the measured profile | **Optimistic.** A reactive controller performs slightly worse. |
| Hourly resolution | Standard for planning studies | **Optimistic.** Real charging is burstier; sub-hourly steps raise peaks. |
| Rooftop PV not modelled | — | Zero output during the 16:00–20:00 window in an Edmonton January, so it cannot affect this result. Summer reverse-flow overvoltage is a separate study. |

The feeder also shows a pre-existing 1.051 pu excursion at bus 1 phase B at
hour 19 under baseline conditions, arising from the modelled regulator
setpoints and fixed capacitor banks. It is not an EV effect and is excluded
from the thresholds, but it means the feeder has no upper-limit headroom for
distributed generation.

---

## Repository

```
src/feeder.py       model construction and the residential load shape
src/evs.py          dwellings per spot load, charger placement, EV injection
src/solve.py        solving, and reading voltages and loading back out
src/storage.py      battery dispatch shape and Storage element
src/study.py        scenario assembly, penetration sweeps, threshold extraction
src/run_study.py    entry point
feeder/IEEE123/     IEEE 123-bus test feeder (unmodified)
data/sweep_all.csv  4,944 rows, tidy long format
```

`sweep_all.csv` columns: `scenario, penetration_pct, seed, n_evs, hour,
v_min, v_max, v_min_all, v_max_all, xfmr_pct, converged`.

Voltage limits are assessed at **load-serving buses only** — ANSI/CSA Range A
is a service voltage standard, and both unfiltered extremes in this model fall
on regulator terminals with no customers connected.

## Running it

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
python src/run_study.py
```

Full sweep runs in a few seconds and rewrites `data/sweep_all.csv`.
