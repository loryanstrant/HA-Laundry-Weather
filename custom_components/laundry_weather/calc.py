"""The drying model.

This module is deliberately free of Home Assistant imports — it takes plain
numbers and returns plain numbers, which is what makes the whole model
testable without a running instance. All I/O, unit conversion and state
reading belongs in ``coordinator.py``.

Units throughout: temperature °C, relative humidity %, wind km/h, solar
irradiance W/m², vapour pressure deficit hPa, sun elevation degrees. Every
datetime arriving here is tz-aware and already in the user's local zone —
hour-of-day bucketing and the weekday label both depend on that.

The model scores drying power as vapour pressure deficit: how much more water
the air *could* hold than it currently does. That is the quantity that
actually drives evaporation, and it is why a cold clear day can beat a warm
humid one. The Magnus formula below was validated against a weather station's
own vapour-pressure-deficit reading and reproduced it exactly.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

# --- tunable defaults ------------------------------------------------------

#: How much full sun multiplies the drying rate. 1.2 means clear midday sun
#: makes the exposed line dry at 2.2x the rate of the same air under cover.
#: Deliberately conservative and explicitly untuned — the whole point of
#: exposing it in the options flow is to calibrate it against real washing.
DEFAULT_SUN_COEFF = 1.2

#: How much better outside has to be before it is recommended over the best
#: indoor room. Without this margin the recommendation flip-flops every few
#: minutes as cloud passes.
DEFAULT_MARGIN = 1.15

#: Below this score nothing meaningful is still drying, so this is the cutoff
#: that sets "bring it in by".
DEFAULT_BRING_IN_FLOOR = 2.5

#: Fast / Moderate / Slow thresholds. Anything below the last one is "Barely".
DEFAULT_BANDS = (12.0, 6.0, 3.0)

BAND_NAMES = ("Barely", "Slow", "Moderate", "Fast")
#: Fill meters, not colours — the reader is colour-blind.
BAND_MARKS = ("○○○", "●○○", "●●○", "●●●")

#: Wind stops helping at about this speed; beyond it, extra wind mostly just
#: throws the washing around.
WIND_CAP_KMH = 20.0

#: Peak clear-sky irradiance at the zenith, W/m². Used to turn a raw
#: irradiance reading into "what fraction of full sun is actually getting
#: through", which is what the model needs.
CLEAR_SKY_PEAK = 1050.0

#: Below this modelled clear-sky value the ratio becomes meaningless (dividing
#: a small number by a smaller one), so the sky fraction is forced to zero.
CLEAR_SKY_FLOOR = 20.0

#: Rain rate above which the line counts as wet regardless of what any rain
#: detector says.
RAIN_RATE_THRESHOLD = 0.2

#: Forecast hour counts as wet at or above either of these.
FORECAST_WET_PROBABILITY = 50.0
FORECAST_WET_PRECIPITATION = 0.5

#: How far ahead the forecast is scored.
DEFAULT_HORIZON_HOURS = 48

#: The best window spans hours scoring at least this fraction of the peak.
BEST_WINDOW_FRACTION = 0.6

#: Overnight dew check looks this far ahead, over these hours of the day.
OVERNIGHT_HORIZON_HOURS = 20
OVERNIGHT_HOURS = (18, 8)
OVERNIGHT_DEFAULT_MIN = 99.0

#: Home Assistant truncates entity states at 255 characters.
ADVICE_LIMIT = 255

COVERED_LINE = "Line under cover"
OPEN_LINE = "Line in the sun"

FORECAST_MODEL_UV = "uv"
FORECAST_MODEL_CLOUD = "cloud"
FORECAST_MODEL_ELEVATION = "elevation"
FORECAST_MODEL_AUTO = "auto"


@dataclass(frozen=True)
class Tuning:
    """User-adjustable knobs, carried as one object so nothing goes unpassed."""

    sun_coeff: float = DEFAULT_SUN_COEFF
    margin: float = DEFAULT_MARGIN
    bring_in_floor: float = DEFAULT_BRING_IN_FLOOR
    bands: tuple[float, float, float] = DEFAULT_BANDS
    forecast_sun_model: str = FORECAST_MODEL_AUTO


# --- primitives ------------------------------------------------------------


def clamp(value: float, low: float, high: float) -> float:
    """Constrain `value` to the inclusive range [low, high]."""
    return max(low, min(high, value))


def vpd_hpa(temp_c: float, rh_pct: float) -> float:
    """Vapour pressure deficit in hPa, via the Magnus formula.

    This is the drying score. Saturation vapour pressure rises steeply with
    temperature; the deficit is the part of that capacity the air has not
    already used. Humidity is clamped rather than trusted, because sensors do
    occasionally report 101%.
    """
    rh = clamp(float(rh_pct), 0.0, 100.0)
    saturation = 6.112 * math.exp((17.67 * float(temp_c)) / (float(temp_c) + 243.5))
    return saturation * (1.0 - rh / 100.0)


def wind_norm(wind_kmh: float | None, cap: float = WIND_CAP_KMH) -> float:
    """Wind as a 0-1 fraction of the speed beyond which it stops helping."""
    if wind_kmh is None:
        return 0.0
    return clamp(float(wind_kmh), 0.0, cap) / cap


def band_index(score: float, bands: Sequence[float] = DEFAULT_BANDS) -> int:
    """Return 0 (Barely) to 3 (Fast) for a drying score."""
    fast, moderate, slow = bands
    if score >= fast:
        return 3
    if score >= moderate:
        return 2
    if score >= slow:
        return 1
    return 0


def band(score: float, bands: Sequence[float] = DEFAULT_BANDS) -> str:
    """Name the drying band — the thing to lead with, ahead of the number."""
    return BAND_NAMES[band_index(score, bands)]


def band_marks(score: float, bands: Sequence[float] = DEFAULT_BANDS) -> str:
    """Fill meter for the band. Shape and fill, never colour."""
    return BAND_MARKS[band_index(score, bands)]


# --- live scoring ----------------------------------------------------------


def indoor_score(temp_c: float, rh_pct: float) -> float:
    """Drying power of a room: plain VPD, with no wind or sun term.

    Indoor air is still, so neither of the outdoor multipliers applies. This
    is why a warm dry sunroom regularly beats a breezy overcast line.
    """
    return vpd_hpa(temp_c, rh_pct)


def covered_score(vpd_out: float, wn: float) -> float:
    """Drying power under a roof: outdoor air, most of the breeze lost."""
    return vpd_out * (0.55 + 0.45 * wn)


def sky_fraction(solar_wm2: float | None, elevation_deg: float | None) -> float:
    """How much of the available sun is actually reaching the ground, 0-1.

    Comparing measured irradiance against the clear-sky value for the current
    sun elevation separates "dim because it is cloudy" from "dim because it is
    nearly evening" — which matter very differently for drying.
    """
    if solar_wm2 is None or elevation_deg is None:
        return 0.0
    clear = CLEAR_SKY_PEAK * math.sin(math.radians(float(elevation_deg)))
    if clear <= CLEAR_SKY_FLOOR:
        return 0.0
    return clamp(float(solar_wm2) / clear, 0.0, 1.0)


def sun_gate(elevation_deg: float | None) -> float:
    """Ramp the sun's contribution in between 10° and 40° of elevation.

    Low sun is bright but glancing: it warms the washing far less than the
    irradiance figure alone suggests.
    """
    if elevation_deg is None:
        return 0.0
    return clamp((float(elevation_deg) - 10.0) / 30.0, 0.0, 1.0)


def live_sun_factor(
    solar_wm2: float | None,
    elevation_deg: float | None,
    sun_coeff: float = DEFAULT_SUN_COEFF,
) -> float:
    """Multiplier the sun applies to the exposed line right now."""
    return 1.0 + sun_coeff * sky_fraction(solar_wm2, elevation_deg) * sun_gate(
        elevation_deg
    )


def is_wet_now(
    rain_state: str | None,
    dry_state: str,
    rain_rate_mm_h: float | None,
    rate_threshold: float = RAIN_RATE_THRESHOLD,
) -> bool:
    """Is the exposed line getting rained on?

    An unknown detector reading is treated as *dry*, not as wet. The detector
    in the reference setup is a template sensor with no unique id, so it goes
    unavailable on every template reload; zeroing the score each time would be
    far noisier than a brief optimistic reading. Rain rate is the independent
    backstop that catches actual rain.
    """
    if rain_state is not None:
        if rain_state.strip().casefold() != dry_state.strip().casefold():
            return True
    return (rain_rate_mm_h or 0.0) > rate_threshold


def open_line_score(
    vpd_out: float, wn: float, sun_factor: float, wet: bool
) -> float:
    """Drying power on the exposed line: full breeze, plus whatever sun."""
    if wet:
        return 0.0
    return vpd_out * (0.8 + 0.6 * wn) * sun_factor


# --- forecast scoring ------------------------------------------------------


@dataclass(frozen=True)
class ForecastHour:
    """One normalised hour of forecast, in the units this module expects."""

    ts: datetime
    temp_c: float | None = None
    humidity: float | None = None
    wind_kmh: float | None = None
    uv_index: float | None = None
    cloud_pct: float | None = None
    precip_prob: float | None = None
    precip_mm: float | None = None
    elevation_deg: float | None = None


@dataclass(frozen=True)
class ScoredHour:
    """One hour of forecast, scored for both outdoor spots."""

    ts: datetime
    hhmm: str
    sun: float
    cov: float
    wet: bool
    vpd: float
    temp_c: float | None


def forecast_sun_factor(
    hour: ForecastHour, tuning: Tuning, model: str
) -> float:
    """Multiplier the sun applies to a forecast hour.

    Expressed in terms of ``sun_coeff`` so the single tunable moves the live
    and forecast scales together. At the default 1.2 the UV model is exactly
    the ``1 + 0.6 * min(uv, 5) / 5`` of the reference implementation, so
    tuning changes nothing on day one.
    """
    if model == FORECAST_MODEL_UV:
        uv = hour.uv_index
        if uv is None:
            return 1.0
        return 1.0 + (tuning.sun_coeff / 2.0) * (clamp(float(uv), 0.0, 5.0) / 5.0)
    if model == FORECAST_MODEL_CLOUD:
        cloud = hour.cloud_pct
        if cloud is None:
            return 1.0
        clear = clamp(1.0 - float(cloud) / 100.0, 0.0, 1.0)
        return 1.0 + tuning.sun_coeff * clear * sun_gate(hour.elevation_deg)
    if model == FORECAST_MODEL_ELEVATION:
        return 1.0 + tuning.sun_coeff * sun_gate(hour.elevation_deg)
    return 1.0


def choose_forecast_sun_model(
    hours: Sequence[ForecastHour], tuning: Tuning
) -> str:
    """Pick the best sunshine signal the forecast provider actually supplies.

    UV index is the strongest signal but several providers — Met.no among them
    — do not return it at all. Falling back to cloud cover is the difference
    between the timing features working and silently never firing.
    """
    if tuning.forecast_sun_model != FORECAST_MODEL_AUTO:
        return tuning.forecast_sun_model
    if not hours:
        return FORECAST_MODEL_UV
    total = len(hours)
    if sum(1 for h in hours if h.uv_index is not None) >= total / 2:
        return FORECAST_MODEL_UV
    if sum(1 for h in hours if h.cloud_pct is not None) >= total / 2:
        return FORECAST_MODEL_CLOUD
    return FORECAST_MODEL_ELEVATION


def forecast_is_wet(hour: ForecastHour) -> bool:
    """Will this hour rain enough to matter?"""
    return (hour.precip_prob or 0.0) >= FORECAST_WET_PROBABILITY or (
        hour.precip_mm or 0.0
    ) >= FORECAST_WET_PRECIPITATION


def score_forecast_hour(
    hour: ForecastHour, tuning: Tuning, model: str
) -> ScoredHour:
    """Score one forecast hour for both outdoor spots.

    A missing humidity is read as 100% — the pessimistic reading, so a gap in
    the data never manufactures a drying opportunity that isn't there.
    """
    temp = hour.temp_c
    vpd = 0.0 if temp is None else vpd_hpa(temp, hour.humidity if hour.humidity is not None else 100.0)
    wn = wind_norm(hour.wind_kmh)
    wet = forecast_is_wet(hour)
    sun = 0.0 if wet else vpd * (0.8 + 0.6 * wn) * forecast_sun_factor(
        hour, tuning, model
    )
    # The covered line is deliberately *not* zeroed on a wet hour: that is the
    # whole point of a roof, and it is why "move it under cover" stays useful
    # advice when rain is coming.
    cov = covered_score(vpd, wn)
    return ScoredHour(
        ts=hour.ts,
        hhmm=hour.ts.strftime("%H:%M"),
        sun=sun,
        cov=cov,
        wet=wet,
        vpd=vpd,
        temp_c=temp,
    )


def score_forecast(
    hours: Sequence[ForecastHour],
    now: datetime,
    tuning: Tuning,
    horizon_hours: int = DEFAULT_HORIZON_HOURS,
) -> tuple[list[ScoredHour], str]:
    """Score every future forecast hour inside the horizon.

    Returns the series sorted by time, plus the sunshine model that was used —
    the card names it when it isn't UV, so a thin forecast is visible rather
    than mysterious.
    """
    horizon = now.timestamp() + horizon_hours * 3600
    upcoming = [h for h in hours if now.timestamp() < h.ts.timestamp() < horizon]
    upcoming.sort(key=lambda h: h.ts)
    model = choose_forecast_sun_model(upcoming, tuning)
    return [score_forecast_hour(h, tuning, model) for h in upcoming], model


# --- derived answers -------------------------------------------------------


def pick_recommendation(
    rooms: Mapping[str, float],
    cov: float,
    sun: float,
    margin: float = DEFAULT_MARGIN,
) -> tuple[str, float, str | None]:
    """Choose where the washing should go.

    Returns ``(label, score, best_room_name)``. The exposed line has to beat
    the best indoor room by ``margin`` before it wins, which is what stops the
    answer oscillating as cloud crosses the sun.
    """
    best_room: str | None = None
    best_indoor = 0.0
    if rooms:
        best_room = max(rooms, key=lambda name: rooms[name])
        best_indoor = rooms[best_room]

    if sun >= best_indoor * margin and sun >= cov:
        return OPEN_LINE, sun, best_room
    if best_room is not None and best_indoor >= cov:
        return best_room, best_indoor, best_room
    return COVERED_LINE, cov, best_room


def move_outside_at(
    series: Sequence[ScoredHour],
    best_indoor: float,
    sunset: datetime,
    margin: float = DEFAULT_MARGIN,
) -> datetime | None:
    """First upcoming hour where taking it outside is worth the trip.

    Returns ``None`` when no hour before sunset beats indoors — which is a
    real answer ("not worth it today"), not a missing one.
    """
    for hour in series:
        if hour.ts > sunset:
            continue
        if hour.sun > best_indoor * margin:
            return hour.ts
    return None


def bring_in_by(
    series: Sequence[ScoredHour],
    sunset: datetime,
    floor: float = DEFAULT_BRING_IN_FLOOR,
) -> tuple[datetime, str]:
    """When washing left outside should come in — always a real time.

    Note the signature: this takes no ``move_outside_at``. In the reference
    implementation the two were coupled, so when going outside stopped being
    worthwhile the bring-in time was wiped along with it — exactly when it
    mattered most, with washing already on the line. Keeping the parameter out
    of the signature is what stops that being rewritten by accident.

    Uses ``max(sun, cov)`` because the line is movable: as long as *either*
    position is still drying, there is a reason to leave it out.
    """
    for hour in series:
        if hour.ts > sunset:
            continue
        if max(hour.sun, hour.cov) < floor:
            return hour.ts, "score_drop"
    return sunset, "sunset"


@dataclass(frozen=True)
class Window:
    """A contiguous stretch of good drying, around the day's peak."""

    start: datetime
    end: datetime
    peak: float


def best_window(
    series: Sequence[ScoredHour], fraction: float = BEST_WINDOW_FRACTION
) -> Window | None:
    """The stretch around the peak that still scores most of the peak.

    Expanded outwards from the best hour and stopped at the first dip, rather
    than taking every hour above the threshold — a good afternoon and a good
    tomorrow morning are two windows, not one long one.
    """
    if not series:
        return None
    peak = max(h.sun for h in series)
    if peak <= 0:
        return None
    peak_index = next(i for i, h in enumerate(series) if h.sun == peak)
    threshold = peak * fraction

    start = peak_index
    while start > 0 and series[start - 1].sun >= threshold:
        start -= 1
    end = peak_index
    while end < len(series) - 1 and series[end + 1].sun >= threshold:
        end += 1

    return Window(start=series[start].ts, end=series[end].ts, peak=peak)


def format_window(window: Window | None) -> str | None:
    """Render a window as e.g. ``Sun 11:00-16:00 (peak 16.2)``.

    The leading token is the weekday: with a 48-hour horizon the best window
    is regularly tomorrow, so dropping the day would be actively misleading.
    """
    if window is None:
        return None
    start_day = window.start.strftime("%a")
    end_day = window.end.strftime("%a")
    tail = window.end.strftime("%H:%M")
    if end_day != start_day:
        tail = f"{end_day} {tail}"
    return (
        f"{start_day} {window.start.strftime('%H:%M')}-{tail} "
        f"(peak {window.peak:.1f})"
    )


def overnight_rewet(
    series: Sequence[ScoredHour],
    now: datetime,
    dewpoint_now: float | None,
    horizon_hours: int = OVERNIGHT_HORIZON_HOURS,
    night: tuple[int, int] = OVERNIGHT_HOURS,
    default_min: float = OVERNIGHT_DEFAULT_MIN,
) -> tuple[bool, float]:
    """Will dew re-wet anything left out tonight?

    If the air cools below its own dew point, moisture condenses back onto the
    washing — so a load that was dry at dusk is damp by morning.
    """
    evening, morning = night
    horizon = now.timestamp() + horizon_hours * 3600
    temps = [
        h.temp_c
        for h in series
        if h.ts.timestamp() < horizon
        and h.temp_c is not None
        and (h.ts.hour >= evening or h.ts.hour <= morning)
    ]
    lowest = min(temps) if temps else default_min
    if dewpoint_now is None:
        return False, lowest
    return dewpoint_now > lowest, lowest


def good_drying_day(
    sun: float, cov: float, wet: bool, bands: Sequence[float] = DEFAULT_BANDS
) -> bool:
    """Is today worth putting a load out at all?

    Deliberately about the *outdoors*, not the best spot overall: a rainy day
    with an excellent sunroom is not a good day to dry, and saying it was
    would read as nonsense over a photo of rain.
    """
    if wet:
        return False
    return max(sun, cov) >= bands[1]


# --- advice ----------------------------------------------------------------


def _hhmm(value: datetime | None) -> str:
    return "" if value is None else value.strftime("%H:%M")


def build_advice(
    *,
    spot: str,
    score: float,
    band_word: str,
    sun: float,
    cov: float,
    move_at: datetime | None,
    bring_by: datetime,
    window_text: str | None,
    dew: bool,
    washing_out: bool,
    limit: int = ADVICE_LIMIT,
) -> str:
    """One plain-English sentence, band first and never over the state limit.

    Clauses are dropped from the least useful end when the text runs long, so
    truncation never lands mid-word or costs the reader the answer. The
    opening clause and the timing clause are never dropped.
    """
    band_lower = band_word.lower()
    if washing_out:
        opening = f"Washing is out - bring in by {_hhmm(bring_by)}."
        comparison = f" {spot} is fastest now ({score:.1f}, {band_lower})."
    else:
        opening = f"{spot} now ({score:.1f}, {band_lower})."
        comparison = f" Sun {sun:.1f} vs cover {cov:.1f}."

    if move_at is not None:
        timing = f" Move out {_hhmm(move_at)}, in by {_hhmm(bring_by)}."
    elif not washing_out:
        timing = (
            " Outside will not beat inside today; if it is out, in by "
            f"{_hhmm(bring_by)}."
        )
    else:
        timing = ""

    clauses = {
        "opening": opening,
        "comparison": comparison,
        "timing": timing,
        "window": f" Best {window_text}." if window_text else "",
        "dew": " Dew overnight." if dew else "",
    }
    order = ["opening", "comparison", "timing", "window", "dew"]
    # Least useful first: the reader can live without the dew note long before
    # they can live without knowing when to bring it in.
    droppable = ["dew", "window", "comparison"]

    included = set(order)
    text = "".join(clauses[key] for key in order)
    for key in droppable:
        if len(text) <= limit:
            break
        included.discard(key)
        text = "".join(clauses[k] for k in order if k in included)
    return text[:limit]


# --- top-level assembly ----------------------------------------------------


@dataclass
class Spot:
    """One candidate place to hang washing, as shown in the card's table."""

    key: str
    name: str
    kind: str
    score: float
    band: str
    marks: str
    rank: int = 0


@dataclass
class Assessment:
    """Everything derived from one refresh, ready to be split across entities."""

    rooms: dict[str, float] = field(default_factory=dict)
    cover: float = 0.0
    sun: float = 0.0
    wet: bool = False
    spots: list[Spot] = field(default_factory=list)
    best_room: str | None = None
    best_indoor: float = 0.0
    recommendation: str = COVERED_LINE
    recommendation_score: float = 0.0
    recommendation_band: str = BAND_NAMES[0]
    good_day: bool = False
    advice: str = ""
    move_at: datetime | None = None
    bring_by: datetime | None = None
    bring_by_source: str = "sunset"
    window: Window | None = None
    window_text: str | None = None
    dew: bool = False
    overnight_min: float = OVERNIGHT_DEFAULT_MIN
    series: list[ScoredHour] = field(default_factory=list)
    sun_model: str = FORECAST_MODEL_UV


def rank_spots(
    rooms: Mapping[str, float],
    cov: float,
    sun: float,
    bands: Sequence[float] = DEFAULT_BANDS,
) -> list[Spot]:
    """Every candidate spot, best first, each carrying its own band and marks."""
    spots = [
        Spot(
            key=f"room:{name}",
            name=name,
            kind="indoor",
            score=score,
            band=band(score, bands),
            marks=band_marks(score, bands),
        )
        for name, score in rooms.items()
    ]
    spots.append(
        Spot(
            key="open_line",
            name=OPEN_LINE,
            kind="outdoor",
            score=sun,
            band=band(sun, bands),
            marks=band_marks(sun, bands),
        )
    )
    spots.append(
        Spot(
            key="covered_line",
            name=COVERED_LINE,
            kind="outdoor",
            score=cov,
            band=band(cov, bands),
            marks=band_marks(cov, bands),
        )
    )
    spots.sort(key=lambda s: s.score, reverse=True)
    for position, spot in enumerate(spots, start=1):
        spot.rank = position
    return spots


def assess(
    *,
    rooms: Mapping[str, float],
    vpd_out: float,
    wn: float,
    sun_factor: float,
    wet: bool,
    series: Sequence[ScoredHour],
    sun_model: str,
    now: datetime,
    sunset: datetime,
    dewpoint_now: float | None,
    washing_out: bool,
    tuning: Tuning,
) -> Assessment:
    """Turn one set of readings into every answer the entities need."""
    cover = covered_score(vpd_out, wn)
    sun = open_line_score(vpd_out, wn, sun_factor, wet)

    recommendation, score, best_room = pick_recommendation(
        rooms, cover, sun, tuning.margin
    )
    best_indoor = rooms[best_room] if best_room else 0.0

    move_at = move_outside_at(series, best_indoor, sunset, tuning.margin)
    bring_by, bring_by_source = bring_in_by(series, sunset, tuning.bring_in_floor)
    window = best_window(series)
    window_text = format_window(window)
    dew, overnight_min = overnight_rewet(series, now, dewpoint_now)
    band_word = band(score, tuning.bands)

    return Assessment(
        rooms=dict(rooms),
        cover=cover,
        sun=sun,
        wet=wet,
        spots=rank_spots(rooms, cover, sun, tuning.bands),
        best_room=best_room,
        best_indoor=best_indoor,
        recommendation=recommendation,
        recommendation_score=score,
        recommendation_band=band_word,
        good_day=good_drying_day(sun, cover, wet, tuning.bands),
        advice=build_advice(
            spot=recommendation,
            score=score,
            band_word=band_word,
            sun=sun,
            cov=cover,
            move_at=move_at,
            bring_by=bring_by,
            window_text=window_text,
            dew=dew,
            washing_out=washing_out,
        ),
        move_at=move_at,
        bring_by=bring_by,
        bring_by_source=bring_by_source,
        window=window,
        window_text=window_text,
        dew=dew,
        overnight_min=overnight_min,
        series=list(series),
        sun_model=sun_model,
    )
