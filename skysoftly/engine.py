"""Compute the real sky for a place and a date, fully offline (PyEphem + bundled star catalogue)."""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path
from zoneinfo import ZoneInfo

import ephem

from .catalog import STAR_NAMES, METEOR_SHOWERS, MOON_NAMES

DATA = Path(__file__).parent / "data"
LIGHT_YEAR_PER_PARSEC = 3.26156
PLANETS = ["Mercury", "Venus", "Mars", "Jupiter", "Saturn"]

_CONST_NAMES = {
    "Bootes": "Boötes",
}


@dataclass
class Place:
    name: str
    lat: float
    lon: float
    tz: str
    country: str = ""


@dataclass
class Body:
    name: str
    alt: float
    az: float
    mag: float
    constellation: str
    rise: str | None = None     # ISO local time
    set: str | None = None
    status: str = ""            # up | rises_later | morning | hidden
    extra: dict = field(default_factory=dict)


def find_place(city: str, country: str | None = None) -> Place:
    """Look a city up in the offline GeoNames cache (cities with population > 15,000)."""
    import geonamescache
    gc = geonamescache.GeonamesCache()
    hits = [c for c in gc.search_cities(city, case_sensitive=False)
            if c["name"].lower() == city.lower() or city.lower() in [a.lower() for a in c.get("alternatenames", [])]]
    if country:
        hits = [c for c in hits if c["countrycode"].lower() == country.lower()]
    if not hits:
        raise SystemExit(f"City not found offline: {city!r} {country or ''}. Pass --lat --lon --tz instead.")
    c = max(hits, key=lambda x: x["population"])
    return Place(c["name"], float(c["latitude"]), float(c["longitude"]), c["timezone"], c["countrycode"])


def _observer(place: Place, when_utc: dt.datetime) -> ephem.Observer:
    o = ephem.Observer()
    o.lat, o.lon = str(place.lat), str(place.lon)
    o.elevation = 0
    o.date = ephem.Date(when_utc.replace(tzinfo=None))
    return o


def _local(d: ephem.Date | None, tz: ZoneInfo) -> dt.datetime | None:
    if d is None:
        return None
    return ephem.Date(d).datetime().replace(tzinfo=dt.timezone.utc).astimezone(tz)


def _iso(x: dt.datetime | None) -> str | None:
    return x.isoformat(timespec="minutes") if x else None


def _safe(fn, *a, **k):
    try:
        return fn(*a, **k)
    except (ephem.AlwaysUpError, ephem.NeverUpError):
        return None


def constellation_name(body_or_radec) -> str:
    name = ephem.constellation(body_or_radec)[1]
    return _CONST_NAMES.get(name, name)


def load_stars() -> list[dict]:
    with open(DATA / "stars.csv") as f:
        rows = []
        for r in csv.DictReader(f):
            rows.append({"hip": int(r["hip"]), "ra": float(r["ra"]), "dec": float(r["dec"]),
                         "mag": float(r["magnitude"]), "bv": float(r["bv"] or 0.6),
                         "plx": float(r["parallax_mas"] or 0), "con": r["constellation_id"]})
    return rows


def load_constellations() -> list[dict]:
    return json.loads((DATA / "constellations.json").read_text())


def radec_to_altaz(ra_deg: float, dec_deg: float, lst_rad: float, lat_deg: float) -> tuple[float, float]:
    """J2000 RA/Dec to horizon coordinates. Precession is ignored (well under a degree for 1900-2100 charts)."""
    ha = lst_rad - math.radians(ra_deg)
    dec, lat = math.radians(dec_deg), math.radians(lat_deg)
    sin_alt = math.sin(dec) * math.sin(lat) + math.cos(dec) * math.cos(lat) * math.cos(ha)
    alt = math.asin(max(-1, min(1, sin_alt)))
    cos_az = (math.sin(dec) - math.sin(alt) * math.sin(lat)) / (math.cos(alt) * math.cos(lat) + 1e-12)
    az = math.acos(max(-1, min(1, cos_az)))
    if math.sin(ha) > 0:
        az = 2 * math.pi - az
    return math.degrees(alt), math.degrees(az)


def phase_name(illum: float, waxing: bool, nearest: dict | None = None) -> str:
    """Named phases only within ~18 hours of the actual instant; otherwise the in-between name."""
    if nearest:
        for label, days in nearest.items():
            if abs(days) <= 0.75:
                return label
    if illum < 50:
        return "Waxing Crescent" if waxing else "Waning Crescent"
    return "Waxing Gibbous" if waxing else "Waning Gibbous"


def active_showers(day: dt.date) -> list[dict]:
    out = []
    for s in METEOR_SHOWERS:
        for yr in (day.year - 1, day.year, day.year + 1):
            start = dt.date(yr, *s["start"])
            end = dt.date(yr if s["end"] >= s["start"] else yr + 1, *s["end"])
            peak = dt.date(yr if s["peak"] >= s["start"] else yr + 1, *s["peak"])
            if start <= day <= end:
                out.append({**s, "days_to_peak": (peak - day).days, "peak_date": peak.isoformat()})
                break
    return out


def upcoming_shower(day: dt.date, within_days: int = 21) -> dict | None:
    best = None
    for s in METEOR_SHOWERS:
        for yr in (day.year, day.year + 1):
            start = dt.date(yr, *s["start"])
            peak = dt.date(yr if s["peak"] >= s["start"] else yr + 1, *s["peak"])
            if day < start and (start - day).days <= within_days:
                cand = {**s, "days_to_start": (start - day).days, "peak_date": peak.isoformat()}
                if best is None or cand["days_to_start"] < best["days_to_start"]:
                    best = cand
    return best


def sky_for(place: Place, local_day: dt.date, look_time: dt.time | None = None) -> dict:
    """Everything the narrator needs for one evening.

    look_time: the moment the listener looks out of the window. Default is after nautical dusk,
    no earlier than 19:30 and no later than 22:30 local time.
    """
    tz = ZoneInfo(place.tz)
    noon_local = dt.datetime.combine(local_day, dt.time(12, 0), tz)
    noon_utc = noon_local.astimezone(dt.timezone.utc)
    obs = _observer(place, noon_utc)
    sun = ephem.Sun()

    sunset = _local(_safe(obs.next_setting, sun), tz)
    def dusk(deg: str):
        o = _observer(place, noon_utc); o.horizon = deg
        return _local(_safe(o.next_setting, ephem.Sun(), use_center=True), tz)
    civil, nautical, astro = dusk("-6"), dusk("-12"), dusk("-18")
    o2 = _observer(place, noon_utc + dt.timedelta(hours=6))
    sunrise = _local(_safe(o2.next_rising, ephem.Sun()), tz)
    sunrise_today = _local(_safe(_observer(place, noon_utc - dt.timedelta(hours=12)).next_rising, ephem.Sun()), tz)

    def day_length(day: dt.date) -> float | None:
        n = dt.datetime.combine(day, dt.time(12), tz).astimezone(dt.timezone.utc)
        r = _safe(_observer(place, n - dt.timedelta(hours=12)).next_rising, ephem.Sun())
        s = _safe(_observer(place, n).next_setting, ephem.Sun())
        if r is None or s is None:
            return None
        return (ephem.Date(s) - ephem.Date(r)) * 24 * 60

    dl_today = day_length(local_day)
    dl_week = day_length(local_day - dt.timedelta(days=7))

    # When to look
    if look_time is not None:
        look = dt.datetime.combine(local_day, look_time, tz)
        if look_time < dt.time(12):
            look += dt.timedelta(days=1)
        still_light = bool(nautical and look < nautical)
    else:
        floor = dt.datetime.combine(local_day, dt.time(19, 30), tz)
        cap = dt.datetime.combine(local_day, dt.time(22, 30), tz)
        cand = nautical or cap
        look = min(max(cand, floor), cap)
        still_light = bool(nautical is None or nautical > cap)
    look_utc = look.astimezone(dt.timezone.utc)
    lo = _observer(place, look_utc)
    lst = float(lo.sidereal_time())

    # Moon
    moon = ephem.Moon(lo)
    prev_new = ephem.previous_new_moon(lo.date)
    next_new = ephem.next_new_moon(lo.date)
    next_full = ephem.next_full_moon(lo.date)
    prev_full = ephem.previous_full_moon(lo.date)
    waxing = next_full < next_new
    illum = float(moon.phase)
    def _d(x):
        return float(x - lo.date)
    nearest = {
        "Full Moon": min(_d(next_full), _d(prev_full), key=abs),
        "New Moon": min(_d(next_new), _d(prev_new), key=abs),
        "First Quarter": min(_d(ephem.next_first_quarter_moon(lo.date)), _d(ephem.previous_first_quarter_moon(lo.date)), key=abs),
        "Last Quarter": min(_d(ephem.next_last_quarter_moon(lo.date)), _d(ephem.previous_last_quarter_moon(lo.date)), key=abs),
    }
    moon_up = math.degrees(moon.alt) > 0
    if moon_up:
        moon_rise = _local(_safe(_observer(place, look_utc).previous_rising, ephem.Moon()), tz)
    else:
        moon_rise = _local(_safe(_observer(place, look_utc).next_rising, ephem.Moon()), tz)
    moon_set = _local(_safe(_observer(place, look_utc).next_setting, ephem.Moon()), tz)
    if moon_up:
        moon_status = "up"
    elif moon_rise and (moon_rise - look).total_seconds() < 5 * 3600:
        moon_status = "rises_later"
    else:
        moon_status = "hidden"
    nf_local = _local(next_full, tz)
    moon_info = Body("Moon", round(math.degrees(moon.alt), 1), round(math.degrees(moon.az), 1), round(float(moon.mag), 1),
                     constellation_name(moon), _iso(moon_rise), _iso(moon_set), moon_status,
                     {"illumination": round(illum, 1), "waxing": bool(waxing), "phase": phase_name(illum, waxing, nearest),
                      "next_full": _iso(nf_local), "next_full_name": MOON_NAMES[nf_local.month],
                      "days_to_full": round(float(next_full - lo.date), 1),
                      "days_to_new": round(float(next_new - lo.date), 1),
                      "days_since_full": round(float(lo.date - prev_full), 1)})

    # Planets
    planets = []
    late = look + dt.timedelta(hours=4)
    pre_dawn = (sunrise - dt.timedelta(minutes=60)) if sunrise else None
    for name in PLANETS:
        b = getattr(ephem, name)(lo)
        alt, az = math.degrees(b.alt), math.degrees(b.az)
        rise = _local(_safe(_observer(place, look_utc).next_rising, getattr(ephem, name)()), tz)
        setting = _local(_safe(_observer(place, look_utc).next_setting, getattr(ephem, name)()), tz)
        status = "hidden"
        if alt > 5:
            status = "up"
        elif rise and rise <= late:
            status = "rises_later"
        elif pre_dawn:
            pb = getattr(ephem, name)(_observer(place, pre_dawn.astimezone(dt.timezone.utc)))
            if math.degrees(pb.alt) > 8:
                status = "morning"
                az = math.degrees(pb.az); alt = math.degrees(pb.alt)
        sep_moon = math.degrees(ephem.separation(b, moon))
        planets.append(Body(name, round(alt, 1), round(az, 1), round(float(b.mag), 1), constellation_name(b),
                            _iso(rise), _iso(setting), status, {"moon_separation": round(sep_moon, 1)}))

    # Named bright stars above 20 degrees
    stars = []
    for s in load_stars():
        nm = STAR_NAMES.get(s["hip"])
        if not nm:
            continue
        alt, az = radec_to_altaz(s["ra"], s["dec"], lst, place.lat)
        if alt > 20:
            ly = LIGHT_YEAR_PER_PARSEC * 1000 / s["plx"] if s["plx"] > 0.5 else None
            stars.append({"name": nm, "alt": round(alt, 1), "az": round(az, 1), "mag": s["mag"],
                          "light_years": round(ly) if ly else None})
    stars.sort(key=lambda x: x["mag"])
    seen, uniq = set(), []
    for x in stars:
        if x["name"] not in seen:
            seen.add(x["name"]); uniq.append(x)
    stars = uniq

    # Constellation nearest the zenith, and others high in the sky
    zen = None
    high = []
    for c in load_constellations():
        alt, az = radec_to_altaz(c["ra"], c["dec"], lst, place.lat)
        if zen is None or alt > zen[1]:
            zen = (c["name"], alt)
        if alt > 40:
            high.append({"name": c["name"], "alt": round(alt, 1), "az": round(az, 1)})
    high.sort(key=lambda x: -x["alt"])

    # Seasons
    season = None
    for fn, label in ((ephem.next_equinox, "equinox"), (ephem.next_solstice, "solstice")):
        midnight = dt.datetime.combine(local_day, dt.time(0), tz).astimezone(dt.timezone.utc)
        d = _local(fn(ephem.Date(midnight.replace(tzinfo=None))), tz)
        days = (d.date() - local_day).days
        if 0 <= days <= 10 and (season is None or days < season["days"]):
            season = {"kind": label, "date": d.date().isoformat(), "days": days, "month": d.month}

    return {
        "place": asdict(place),
        "date": local_day.isoformat(),
        "weekday": local_day.strftime("%A"),
        "look_time": _iso(look),
        "still_light_at_look": still_light,
        "sun": {"sunrise_today": _iso(sunrise_today), "sunset": _iso(sunset), "civil_dusk": _iso(civil),
                "nautical_dusk": _iso(nautical), "astronomical_dusk": _iso(astro), "sunrise_tomorrow": _iso(sunrise),
                "day_length_min": round(dl_today) if dl_today else None,
                "day_length_change_week_min": round(dl_today - dl_week) if dl_today and dl_week else None},
        "moon": asdict(moon_info),
        "planets": [asdict(p) for p in planets],
        "stars": stars[:10],
        "zenith_constellation": zen[0] if zen else None,
        "high_constellations": high,
        "meteors_active": active_showers(local_day),
        "meteors_upcoming": upcoming_shower(local_day),
        "season": season,
        "lst_rad": lst,
    }
