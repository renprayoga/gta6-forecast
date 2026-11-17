"""Forecast GTA VI's launch-day Twitch viewers hour by hour (gta6-twitch-ccu-forecast-01).

Reads one case at a time from /input (or $MAKEFUN_INPUT_DIR) and writes
/output/<id>.out (or $MAKEFUN_OUTPUT_DIR): for hours 2..24 of the release
day, five quantiles (5%, 25%, 50%, 75%, 95%) of the Twitch category's
concurrent viewers.

Approach (designed from the kit's practice data, see README.md):

  A launch day's audience curve is mostly a question of scale.  Across the
  38 comparable launches shipped in the case file, the shape of the day --
  the ratio of each hour's viewers to hour 1's -- depends overwhelmingly on
  how big hour 1 itself was.  A launch whose category was nearly dead at
  00:00 UTC (a simultaneous global unlock later in the day, e.g. 14:00 UTC)
  explodes hundreds of times over by the evening; a launch that was already
  huge at hour 1 (rolling midnight-local unlock, most of the world already
  playing) stays roughly flat and peaks only ~1.0-1.3x hour 1.  So for each
  forecast hour we take a kernel-weighted average of the comparables'
  log-ratios ln(viewers_h / viewers_1), with weights falling off as a
  Gaussian in ln(hour-1 viewers) with bandwidth 1.0 -- comparables whose
  hour 1 was a similar size count most.  The centre is the average of the
  weighted median and the weighted mean of those log-ratios (median for
  robustness against freak launches, mean for efficiency), lightly smoothed
  across neighbouring hours.  The spread is the weighted standard deviation
  of the same log-ratios around that centre (floored at 0.12 in log units),
  so hours and launches where history disagrees get honestly wide
  quantiles.  Quantiles are lognormal around the centre:
  q_tau = p1 * exp(centre_h + z_tau * sigma_h).

  The target game's own pre-release history was examined and deliberately
  NOT used as a shape input: in leave-one-out tests over the comparables,
  weighting by pre-release level made the loss worse, and hour 1's print
  already carries the launch's scale.  No unlock-time text is parsed either:
  the same tests showed it adds nothing once hour-1 size is conditioned on.

  If a case carries no usable comparables, we fall back to the flat
  persistence forecast (every hour at hour 1's print, spread widening like
  a random walk), so the output is always valid.

Deterministic: fixed iteration order (comparables sorted by name, hours in
order), no randomness, no wall-clock, no network, standard library only.
"""

import json
import math
import os
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0, 0.674, 1.645]

# Gaussian kernel bandwidth (in natural-log units) for how similar another
# launch's hour-1 size must be to count fully.  Tuned by leave-one-out
# pinball loss over the 38 comparables in the kit (bw 1.0: 0.394, vs 0.930
# for the flat baseline; bw 0.7: 0.423, bw 1.2: 0.395).
BANDWIDTH = 1.0
# Floor on the log-spread of any hour, so no hour is ever forecast with
# false certainty.
SIGMA_FLOOR = 0.12
# Fallback random-walk spread per sqrt-hour, as in the house baseline.
FALLBACK_SIGMA = 0.15


def round2(x):
    """Round to 2 decimals, half up (same convention as the kit starter)."""
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if value == int(value) else value


def _parse_time(text):
    """Parse an ISO-8601 UTC timestamp into epoch seconds (stdlib only)."""
    # Format in the case files: "2026-09-15T00:00:00Z".
    try:
        from datetime import datetime, timezone
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def _day_hour(day_start_s, from_s):
    """Hour-of-day index (1..24) of a point, or None if outside the day."""
    if day_start_s is None or from_s is None:
        return None
    h = int((from_s - day_start_s) // 3600) + 1
    return h if 1 <= h <= 24 else None


def _comparable_curves(case):
    """Launch-day log-ratio curves of the case's comparables.

    Returns a list of (log_hour1, {hour: log(viewers_h / viewers_1)}),
    sorted by name for determinism.  A comparable is used only if it has a
    positive hour-1 print and at least 12 of the 24 launch-day hours.
    The target game's own pre-release category history (shipped as a
    comparable in every case) is excluded: it is not a launch day.
    """
    target_name = (case.get("game") or {}).get("name", "").lower()
    curves = []
    for comp in case.get("comparables") or []:
        name = (comp.get("name") or "").lower()
        if target_name and target_name in name:
            continue
        day_start = _parse_time(comp.get("day_start") or "")
        if day_start is None:
            continue
        by_hour = {}
        for row in comp.get("hourly") or []:
            viewers = row.get("viewers")
            if not viewers or viewers <= 0:
                continue
            h = _day_hour(day_start, _parse_time(row.get("from") or ""))
            if h is not None and h not in by_hour:
                by_hour[h] = float(viewers)
        if 1 not in by_hour or len(by_hour) < 12:
            continue
        p1 = by_hour[1]
        curves.append((
            math.log(p1),
            {h: math.log(v / p1) for h, v in by_hour.items()},
            comp.get("name") or "",
        ))
    curves.sort(key=lambda item: item[2])
    return [(lp1, curve) for lp1, curve, _ in curves]


def _weighted_median(pairs):
    """Weighted median of (value, weight) pairs."""
    ordered = sorted(pairs)
    total = sum(w for _, w in ordered)
    acc = 0.0
    for value, weight in ordered:
        acc += weight
        if acc >= total / 2:
            return value
    return ordered[-1][0]


def _weighted_mean(pairs):
    total = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / total


def _shape_for_hour(curves, log_p1, hour):
    """(centre log-ratio, log-spread) for one forecast hour, or None."""
    pairs = []
    for comp_log_p1, curve in curves:
        if hour not in curve:
            continue
        distance = (comp_log_p1 - log_p1) / BANDWIDTH
        weight = math.exp(-0.5 * distance * distance)
        pairs.append((curve[hour], weight))
    if not pairs:
        return None
    centre = 0.5 * (_weighted_median(pairs) + _weighted_mean(pairs))
    total = sum(w for _, w in pairs)
    variance = sum(w * (v - centre) ** 2 for v, w in pairs) / total
    return centre, max(SIGMA_FLOOR, math.sqrt(variance))


def forecast_case(case):
    if case["levels"] != LEVELS:
        raise ValueError("case asks for levels %r, not %r" % (case["levels"], LEVELS))
    first = next((k for k in case["known"] if k["hour"] == 1), None)
    if first is None:
        raise ValueError("case has no hour-1 print")
    p1 = max(1.0, float(first["viewers"]))

    curves = _comparable_curves(case)
    centres = {}
    sigmas = {}
    if curves:
        log_p1 = math.log(p1)
        raw = {}
        for hour in range(2, 25):
            got = _shape_for_hour(curves, log_p1, hour)
            if got is not None:
                raw[hour] = got
        # Fill any missing hour from its neighbours, then smooth the
        # centres with a (1, 2, 1) / 4 filter so the curve has no jags
        # that no real launch day shows.
        for hour in range(2, 25):
            if hour not in raw:
                neighbours = [raw[h] for h in (hour - 1, hour + 1) if h in raw]
                raw[hour] = neighbours[0] if neighbours else (0.0, SIGMA_FLOOR)
        for hour in range(2, 25):
            prev_c = raw[hour - 1][0] if hour - 1 in raw else raw[hour][0]
            next_c = raw[hour + 1][0] if hour + 1 in raw else raw[hour][0]
            centres[hour] = (prev_c + 2 * raw[hour][0] + next_c) / 4
            sigmas[hour] = raw[hour][1]

    hours = []
    for row in case["forecast"]:
        h = row["hour"]
        if curves:
            centre = centres[h]
            sigma = sigmas[h]
        else:
            centre = 0.0
            sigma = FALLBACK_SIGMA * math.sqrt(h - 1)
        quantiles = []
        for z in Z:
            q = p1 * math.exp(centre + z * sigma)
            q = min(max(q, 0.01), 1e9)
            quantiles.append(round2(q))
        # Guarantee non-decreasing after rounding.
        for i in range(1, 5):
            if quantiles[i] < quantiles[i - 1]:
                quantiles[i] = quantiles[i - 1]
        hours.append({"hour": h, "q": quantiles})
    hours.sort(key=lambda row: row["hour"])
    return {"hours": hours}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case)
        (OUTPUT_DIR / (path.stem + ".out")).write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
