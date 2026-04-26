"""State bounding boxes for the Geographica offline pipeline.

This module lives in scripts/common (not setup/) because the pipeline
container mounts ./scripts:/scripts:ro but NOT ./setup. The pipeline needs
to intersect bboxes against state boundaries, so the primitive must be
importable from the pipeline context.

The setup wizard (setup/runner.py) re-imports these from here to avoid
duplication.
"""

STATE_BBOXES: dict[str, tuple[float, float, float, float]] = {
    "alabama":              (-88.47, 30.14, -84.89, 35.01),
    "arizona":              (-114.82, 31.33, -109.05, 37.00),
    "arkansas":             (-94.62, 33.00, -89.64, 36.50),
    "california":           (-124.48, 32.53, -114.13, 42.01),
    "colorado":             (-109.06, 37.00, -102.04, 41.00),
    "connecticut":          (-73.73, 40.98, -71.79, 42.05),
    "delaware":             (-75.79, 38.45, -74.98, 39.84),
    "district-of-columbia": (-77.12, 38.79, -76.91, 38.99),
    "florida":              (-87.63, 24.52, -80.03, 31.00),
    "georgia-us":           (-85.61, 30.36, -80.84, 35.00),
    "idaho":                (-117.24, 41.99, -111.05, 49.00),
    "illinois":             (-91.51, 36.97, -87.49, 42.51),
    "indiana":              (-88.10, 37.77, -84.78, 41.76),
    "iowa":                 (-96.64, 40.38, -90.14, 43.50),
    "kansas":               (-102.05, 36.99, -94.59, 40.00),
    "kentucky":             (-89.57, 36.50, -81.96, 39.15),
    "louisiana":            (-94.04, 28.93, -88.75, 33.02),
    "maine":                (-71.08, 43.06, -66.95, 47.46),
    "maryland":             (-79.49, 37.89, -75.05, 39.72),
    "massachusetts":        (-73.51, 41.23, -69.93, 42.89),
    "michigan":             (-90.42, 41.70, -82.12, 48.31),
    "minnesota":            (-97.24, 43.50, -89.49, 49.38),
    "mississippi":          (-91.66, 30.17, -88.10, 35.01),
    "missouri":             (-95.77, 35.99, -89.10, 40.61),
    "montana":              (-116.05, 44.36, -104.04, 49.00),
    "nebraska":             (-104.05, 40.00, -95.31, 43.00),
    "nevada":               (-120.01, 35.00, -114.04, 42.00),
    "new-hampshire":        (-72.56, 42.70, -70.61, 45.30),
    "new-jersey":           (-75.56, 38.93, -73.89, 41.36),
    "new-mexico":           (-109.05, 31.33, -103.00, 37.00),
    "new-york":             (-79.76, 40.50, -71.86, 45.01),
    "north-carolina":       (-84.32, 33.75, -75.46, 36.59),
    "north-dakota":         (-104.05, 45.94, -96.55, 49.00),
    "ohio":                 (-84.82, 38.40, -80.52, 41.98),
    "oklahoma":             (-103.00, 33.62, -94.43, 37.00),
    "oregon":               (-124.57, 41.99, -116.46, 46.29),
    "pennsylvania":         (-80.52, 39.72, -74.69, 42.27),
    "rhode-island":         (-71.86, 41.15, -71.12, 42.02),
    "south-carolina":       (-83.35, 32.03, -78.54, 35.22),
    "south-dakota":         (-104.06, 42.48, -96.44, 45.95),
    "tennessee":            (-90.31, 34.98, -81.65, 36.68),
    "texas":                (-106.65, 25.84, -93.52, 36.50),
    "utah":                 (-114.05, 37.00, -109.04, 42.00),
    "vermont":              (-73.44, 42.73, -71.46, 45.02),
    "virginia":             (-83.68, 36.54, -75.24, 39.47),
    "washington":           (-124.77, 45.54, -116.92, 49.00),
    "west-virginia":        (-82.64, 37.20, -77.72, 40.64),
    "wisconsin":            (-92.89, 42.49, -86.80, 47.08),
    "wyoming":              (-111.06, 40.99, -104.05, 45.01),
}


def _states_intersecting(bbox_str: str) -> list[str]:
    """Return the subset of STATE_BBOXES that overlap ``bbox_str``.

    ``bbox_str`` is the Geographica-canonical ``"west,south,east,north"``
    form. Return order is the insertion order of ``STATE_BBOXES`` (stable).

    Returns EMPTY list for:
    - Malformed bbox (not 4 parseable floats)
    - Empty string
    - Valid bbox that doesn't overlap any of the 48 contiguous states + DC
      (e.g. Alaska, Hawaii, Europe, middle of the Atlantic)

    Prior behavior was "fall back to all states" on no-match. That
    triggered the 2026-04-21 beta-tester report where a bbox outside
    the 11-state western-US coverage silently downloaded 4 GB of
    irrelevant data. Now the caller is responsible for turning an
    empty return into a clear "your bbox isn't supported" 400 at
    /api/start (see setup/main.py::post_start).
    """
    try:
        parts = [p.strip() for p in bbox_str.split(",")]
        if len(parts) != 4:
            return []
        w, s, e, n = (float(x) for x in parts)
    except (ValueError, AttributeError):
        return []

    matching: list[str] = []
    for state, (sw, ss, se, sn) in STATE_BBOXES.items():
        # Axis-aligned bbox intersection.
        if sw <= e and se >= w and ss <= n and sn >= s:
            matching.append(state)
    return matching


# Public alias for new code. The underscore prefix on _states_intersecting
# is for backwards compatibility with setup/runner.py callers.
states_intersecting = _states_intersecting


# USPS postal code → Geographica internal slug
# AK and HI intentionally map to None — not supported by Geographica
SLUG_BY_USPS: dict[str, str | None] = {
    "AL": "alabama", "AK": None, "AZ": "arizona", "AR": "arkansas",
    "CA": "california", "CO": "colorado", "CT": "connecticut",
    "DE": "delaware", "DC": "district-of-columbia", "FL": "florida",
    "GA": "georgia-us", "HI": None, "ID": "idaho", "IL": "illinois",
    "IN": "indiana", "IA": "iowa", "KS": "kansas", "KY": "kentucky",
    "LA": "louisiana", "ME": "maine", "MD": "maryland",
    "MA": "massachusetts", "MI": "michigan", "MN": "minnesota",
    "MS": "mississippi", "MO": "missouri", "MT": "montana",
    "NE": "nebraska", "NV": "nevada", "NH": "new-hampshire",
    "NJ": "new-jersey", "NM": "new-mexico", "NY": "new-york",
    "NC": "north-carolina", "ND": "north-dakota", "OH": "ohio",
    "OK": "oklahoma", "OR": "oregon", "PA": "pennsylvania",
    "RI": "rhode-island", "SC": "south-carolina", "SD": "south-dakota",
    "TN": "tennessee", "TX": "texas", "UT": "utah", "VT": "vermont",
    "VA": "virginia", "WA": "washington", "WV": "west-virginia",
    "WI": "wisconsin", "WY": "wyoming",
}

USPS_BY_SLUG: dict[str, str] = {
    slug: usps
    for usps, slug in SLUG_BY_USPS.items()
    if slug is not None
}


def display_name(slug: str) -> str:
    """Render a slug as a human display name.

    'arizona' → 'Arizona'
    'georgia-us' → 'Georgia' (strip the disambiguation suffix)
    'district-of-columbia' → 'District of Columbia'
    'new-hampshire' → 'New Hampshire'
    """
    if slug == "georgia-us":
        return "Georgia"
    parts = slug.split("-")
    # Capitalize first part always, keep 'of' and 'the' lowercase
    result = [parts[0].capitalize()]
    for part in parts[1:]:
        if part in ("of", "the"):
            result.append(part)
        else:
            result.append(part.capitalize())
    return " ".join(result)
