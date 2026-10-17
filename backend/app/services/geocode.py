"""Server-side geocoding. Google Geocoding API when a key is present, otherwise a
small offline fallback for Miami-Dade ZIP codes and well-known neighborhoods so the
app still works without keys."""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Optional

import httpx

from ..config import GOOGLE_GEOCODING_KEY, MIAMI_BOUNDS

# Approximate centroids (lat, lon) for Miami-Dade ZIP codes. Used only when no Google key is configured.
ZIP_CENTROIDS: dict[str, tuple[float, float]] = {
    "33010": (25.834, -80.279), "33012": (25.868, -80.303), "33013": (25.861, -80.270), "33014": (25.902, -80.306),
    "33015": (25.939, -80.318), "33016": (25.892, -80.332), "33018": (25.912, -80.388), "33030": (25.470, -80.491),
    "33031": (25.526, -80.502), "33032": (25.526, -80.390), "33033": (25.487, -80.418), "33034": (25.431, -80.480),
    "33035": (25.436, -80.449), "33039": (25.497, -80.391), "33054": (25.909, -80.253), "33055": (25.948, -80.277),
    "33056": (25.950, -80.246), "33109": (25.761, -80.139), "33122": (25.797, -80.312), "33125": (25.782, -80.236),
    "33126": (25.779, -80.299), "33127": (25.813, -80.205), "33128": (25.776, -80.204), "33129": (25.755, -80.202),
    "33130": (25.768, -80.202), "33131": (25.765, -80.188), "33132": (25.784, -80.185), "33133": (25.730, -80.242),
    "33134": (25.754, -80.271), "33135": (25.766, -80.235), "33136": (25.785, -80.204), "33137": (25.815, -80.186),
    "33138": (25.853, -80.182), "33139": (25.783, -80.135), "33140": (25.818, -80.131), "33141": (25.850, -80.137),
    "33142": (25.812, -80.238), "33143": (25.702, -80.298), "33144": (25.763, -80.311), "33145": (25.753, -80.233),
    "33146": (25.723, -80.273), "33147": (25.850, -80.237), "33149": (25.713, -80.164), "33150": (25.851, -80.206),
    "33154": (25.880, -80.128), "33155": (25.738, -80.311), "33156": (25.668, -80.303), "33157": (25.607, -80.344),
    "33158": (25.637, -80.312), "33160": (25.933, -80.138), "33161": (25.894, -80.183), "33162": (25.928, -80.176),
    "33165": (25.734, -80.359), "33166": (25.826, -80.311), "33167": (25.886, -80.231), "33168": (25.892, -80.210),
    "33169": (25.943, -80.213), "33170": (25.558, -80.447), "33172": (25.787, -80.359), "33173": (25.702, -80.358),
    "33174": (25.762, -80.361), "33175": (25.733, -80.408), "33176": (25.657, -80.360), "33177": (25.597, -80.405),
    "33178": (25.829, -80.372), "33179": (25.957, -80.181), "33180": (25.961, -80.142), "33181": (25.898, -80.154),
    "33182": (25.781, -80.411), "33183": (25.699, -80.405), "33184": (25.759, -80.405), "33185": (25.727, -80.449),
    "33186": (25.661, -80.408), "33187": (25.593, -80.463), "33189": (25.573, -80.343), "33190": (25.558, -80.350),
    "33193": (25.700, -80.460), "33194": (25.754, -80.464), "33196": (25.655, -80.446), "33101": (25.774, -80.198),
}

NEIGHBORHOODS: dict[str, tuple[float, float]] = {
    "brickell": (25.7617, -80.1918), "downtown miami": (25.7743, -80.1937), "wynwood": (25.8010, -80.1994),
    "little havana": (25.7656, -80.2195), "coral gables": (25.7215, -80.2684), "coconut grove": (25.7126, -80.2570),
    "key biscayne": (25.6935, -80.1626), "miami beach": (25.7907, -80.1300), "south beach": (25.7826, -80.1341),
    "north miami": (25.8901, -80.1867), "north miami beach": (25.9331, -80.1625), "aventura": (25.9565, -80.1392),
    "sunny isles": (25.9507, -80.1226), "hialeah": (25.8576, -80.2781), "miami lakes": (25.9087, -80.3087),
    "doral": (25.8195, -80.3553), "sweetwater": (25.7634, -80.3729), "westchester": (25.7454, -80.3272),
    "kendall": (25.6793, -80.3173), "west kendall": (25.6900, -80.4300), "pinecrest": (25.6671, -80.3081),
    "palmetto bay": (25.6218, -80.3245), "cutler bay": (25.5806, -80.3468), "homestead": (25.4687, -80.4776),
    "florida city": (25.4479, -80.4792), "miami gardens": (25.9420, -80.2456), "opa-locka": (25.9023, -80.2503),
    "miami springs": (25.8223, -80.2895), "south miami": (25.7076, -80.2934), "little haiti": (25.8290, -80.1960),
    "liberty city": (25.8350, -80.2250), "allapattah": (25.8150, -80.2240), "overtown": (25.7860, -80.2010),
    "edgewater": (25.7990, -80.1890), "design district": (25.8130, -80.1930), "fontainebleau": (25.7700, -80.3450),
    "tamiami": (25.7580, -80.4000), "the hammocks": (25.6700, -80.4450), "country walk": (25.6330, -80.4320),
    "richmond heights": (25.6340, -80.3700), "goulds": (25.5660, -80.3820), "perrine": (25.6060, -80.3550),
    "surfside": (25.8785, -80.1256), "bal harbour": (25.8915, -80.1268), "bay harbor islands": (25.8870, -80.1310),
    "el portal": (25.8550, -80.1930), "miami shores": (25.8630, -80.1930), "biscayne park": (25.8820, -80.1810),
    "virginia gardens": (25.8100, -80.3020), "medley": (25.8450, -80.3400), "hialeah gardens": (25.8650, -80.3250),
    "west miami": (25.7570, -80.2960), "olympia heights": (25.7240, -80.3390), "kendale lakes": (25.7080, -80.4070),
    "coral terrace": (25.7450, -80.3040), "glenvar heights": (25.7080, -80.3160), "sunset": (25.7060, -80.3530),
    "three lakes": (25.6420, -80.4000), "princeton": (25.5380, -80.4090), "leisure city": (25.4950, -80.4290),
    "naranja": (25.5180, -80.4230), "miami": (25.7743, -80.1937),
}


def _in_bounds(lat: float, lon: float) -> bool:
    s, w, n, e = MIAMI_BOUNDS
    return s <= lat <= n and w <= lon <= e


def _offline(q: str) -> Optional[dict]:
    text = q.strip().lower()
    m = re.search(r"\b(33\d{3})\b", text)
    if m and m.group(1) in ZIP_CENTROIDS:
        lat, lon = ZIP_CENTROIDS[m.group(1)]
        return {"lat": lat, "lon": lon, "label": f"ZIP {m.group(1)}", "provider": "offline_zip"}
    best = None
    for name, (lat, lon) in NEIGHBORHOODS.items():
        if name in text and (best is None or len(name) > len(best[0])):
            best = (name, lat, lon)
    if best:
        return {"lat": best[1], "lon": best[2], "label": best[0].title(), "provider": "offline_neighborhood"}
    return None


@lru_cache(maxsize=512)
def geocode(q: str) -> Optional[dict]:
    q = (q or "").strip()
    if not q:
        return None
    if GOOGLE_GEOCODING_KEY:
        s, w, n, e = MIAMI_BOUNDS
        try:
            r = httpx.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={
                    "address": q,
                    "key": GOOGLE_GEOCODING_KEY,
                    "bounds": f"{s},{w}|{n},{e}",
                    "components": "country:US|administrative_area:FL",
                    "region": "us",
                },
                timeout=10,
            )
            data = r.json()
            for res in data.get("results", []):
                loc = res["geometry"]["location"]
                if _in_bounds(loc["lat"], loc["lng"]):
                    return {"lat": loc["lat"], "lon": loc["lng"], "label": res.get("formatted_address", q), "provider": "google"}
        except Exception:  # noqa: BLE001 - fall through to offline
            pass
    return _offline(q)
