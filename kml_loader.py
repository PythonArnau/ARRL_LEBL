"""Lectura de los KML generados por ``kml_export.export_arrival_kml``.

Cada KML contiene una aproximación: la línea de la trayectoria, un Placemark por record
(con t, sensor, x/y en NM, altitud en ft, IAS y GS en la descripción), los saltos > umbral
y el marcador del umbral de pista. Aquí se recupera todo eso y se calcula la distancia
acumulada a THR igual que en ``Distancias.cumulative_dist``.
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

REC_RE = re.compile(
    r"idx=(?P<i>\d+)\s*\|\s*t=(?P<t>-?\d+)\s*s\s*\|\s*(?P<sensor>.+?)\s*<br\s*/?>\s*"
    r"x=(?P<x>-?[\d.]+)\s+y=(?P<y>-?[\d.]+)\s*NM\s*<br\s*/?>\s*"
    r"alt=(?P<alt>-?[\d.]+)\s*ft\s*\|\s*IAS=(?P<ias>-?[\d.]+)\s*\|\s*GS=(?P<gs>-?[\d.]+)",
    re.S,
)


@dataclass
class Track:
    name: str                                   # p. ej. VLG11K_FR0
    runway: str | None = None
    thr: tuple | None = None                    # (lat, lon) del marcador de umbral
    records: list = field(default_factory=list)  # dicts: i, t, time, sensor, x, y, alt, ias, gs, lat, lon, cum_dist
    jumps: list = field(default_factory=list)    # dicts: i, nm, lat, lon (extremos del tramo), text
    idx_thr: int | None = None                   # record más cercano al umbral
    line: list = field(default_factory=list)     # [(lat, lon)] de la línea blanca (si no hay records)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el, name):
    return next((c for c in el if _local(c.tag) == name), None)


def _text(el) -> str:
    return (el.text or "").strip() if el is not None else ""


def _coords(text: str) -> list:
    out = []
    for tok in text.split():
        p = tok.split(",")
        try:
            out.append((float(p[1]), float(p[0])))  # (lat, lon)
        except (ValueError, IndexError):
            pass
    return out


def haversine_nm(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 3440.065 * math.asin(math.sqrt(a))


def parse_kml(data: bytes, name: str | None = None) -> Track:
    """``name`` (p. ej. el nombre del fichero) tiene prioridad sobre el <name> del Document."""
    root = ET.fromstring(data)
    doc = next((e for e in root.iter() if _local(e.tag) == "Document"), root)
    track = Track(name=name or _text(_child(doc, "name")) or "trayectoria")

    for pm in (e for e in doc.iter() if _local(e.tag) == "Placemark"):
        name = _text(_child(pm, "name"))
        desc = _text(_child(pm, "description"))
        point = next((e for e in pm.iter() if _local(e.tag) == "Point"), None)
        line = next((e for e in pm.iter() if _local(e.tag) == "LineString"), None)

        m = REC_RE.search(desc)
        if m and point is not None:
            (lat, lon), *_ = _coords(_text(_child(point, "coordinates")))
            ts = next((e for e in pm.iter() if _local(e.tag) == "when"), None)
            track.records.append({
                "i": int(m["i"]), "t": int(m["t"]), "time": _text(ts), "sensor": m["sensor"],
                "x": float(m["x"]), "y": float(m["y"]), "alt": float(m["alt"]),
                "ias": float(m["ias"]), "gs": float(m["gs"]), "lat": lat, "lon": lon,
            })
        elif name.startswith("THR") and point is not None:
            track.runway = name[3:].strip() or None
            track.thr = _coords(_text(_child(point, "coordinates")))[0]
        elif name.startswith("salto") and line is not None:
            pts = _coords(_text(_child(line, "coordinates")))
            nm = re.search(r"([\d.]+)\s*NM", name)
            track.jumps.append({"nm": float(nm[1]) if nm else None, "pts": pts, "text": name})
        elif line is not None and not track.line:
            track.line = _coords(_text(_child(line, "coordinates")))

    track.records.sort(key=lambda r: r["i"])
    _add_cum_dist(track)
    return track


def _add_cum_dist(track: Track):
    """Distancia acumulada hacia atrás desde el record más cercano al umbral (como cumulative_dist)."""
    recs = track.records
    if not recs:
        return
    if track.thr is not None:
        track.idx_thr = min(range(len(recs)), key=lambda i: haversine_nm(recs[i]["lat"], recs[i]["lon"], *track.thr))
    else:
        track.idx_thr = len(recs) - 1
    ref = track.idx_thr
    for r in recs:
        r["cum_dist"] = None
    recs[ref]["cum_dist"] = 0.0
    for i in range(ref - 1, -1, -1):
        step = math.hypot(recs[i]["x"] - recs[i + 1]["x"], recs[i]["y"] - recs[i + 1]["y"])
        recs[i]["cum_dist"] = recs[i + 1]["cum_dist"] + step