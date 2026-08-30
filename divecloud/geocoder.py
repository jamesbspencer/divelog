"""GPS decoding and reverse geocoding utility for dive logs."""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# State name to standard 2-letter abbreviation
US_STATE_ABBR = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO",
    "Montana": "MT", "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ",
    "New Mexico": "NM", "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH",
    "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT",
    "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}

# In-memory geocoding cache
_GEOCODE_CACHE: Dict[Tuple[float, float], str] = {}


class GPSGeocoder:
    """Handles parsing binary BAM coordinates and reverse geocoding to City, State, Country."""

    @classmethod
    def parse_gps_string(cls, loc_str: str) -> Tuple[Optional[float], Optional[float]]:
        """Parse binary angle measurement (BAM) GPS string e.g. GPS=[1.1082911E9,-1.0296864E9]."""
        if not loc_str or "GPS=[" not in loc_str:
            return None, None

        match = re.search(r"GPS=\[([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\]", loc_str)
        if not match:
            return None, None

        try:
            raw_lat = float(match.group(1))
            raw_lng = float(match.group(2))

            if abs(raw_lat) < 0.001 and abs(raw_lng) < 0.001:
                return None, None

            # If values are in BAM binary angular measurement format (scaled by 2^31)
            if abs(raw_lat) > 90.0 or abs(raw_lng) > 180.0:
                lat = (raw_lat / (2**31)) * 90.0
                lng = (raw_lng / (2**31)) * 180.0
            else:
                lat = raw_lat
                lng = raw_lng

            if -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0:
                return round(lat, 5), round(lng, 5)

        except (ValueError, ZeroDivisionError):
            pass

        return None, None

    @classmethod
    def reverse_geocode(cls, lat: Optional[float], lng: Optional[float]) -> str:
        """Reverse geocode coordinates to 'City, State, Country' format."""
        if lat is None or lng is None:
            return ""

        cache_key = (round(lat, 3), round(lng, 3))
        if cache_key in _GEOCODE_CACHE:
            return _GEOCODE_CACHE[cache_key]

        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lng}&format=json&zoom=10"
        req = urllib.request.Request(url, headers={"User-Agent": "divelog-sync/1.0"})

        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                addr = data.get("address", {})

                city = (
                    addr.get("city")
                    or addr.get("town")
                    or addr.get("village")
                    or addr.get("municipality")
                    or addr.get("county")
                    or ""
                )
                city_clean = city.replace(" Township", "").replace(" County", "").strip()

                state_raw = addr.get("state", "").strip()
                state_abbr = US_STATE_ABBR.get(state_raw, state_raw)

                country = addr.get("country", "").strip()
                country_clean = "USA" if country in ("United States", "United States of America") else country

                parts = [p for p in [city_clean, state_abbr, country_clean] if p]
                result = ", ".join(parts)

                if result:
                    _GEOCODE_CACHE[cache_key] = result
                    return result

        except Exception as exc:
            logger.debug("Reverse geocoding failed for (%s, %s): %s", lat, lng, exc)

        return ""
