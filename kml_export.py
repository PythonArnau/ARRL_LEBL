import math
from xml.sax.saxutils import escape

# Colores KML: aabbggrr
COLORES = {
    "ADSB-BCN": "ff00ff00",       # verde
    "Radar-BCN": "ff0000ff",      # rojo
    "INTERPOLATED": "ff00ffff",   # amarillo
}
COLOR_DEFECTO = "ffffffff"
FT_A_M = 0.3048


def _iso(rec):
    """day=20250114, time=ToD [s] -> '2025-01-14T05:30:16Z' (para el slider temporal de Google Earth)."""
    d = rec.day
    t = int(rec.time)
    return (f"{d // 10000:04d}-{(d // 100) % 100:02d}-{d % 100:02d}"
            f"T{t // 3600:02d}:{(t % 3600) // 60:02d}:{t % 60:02d}Z")


def _coord(rec, usar_altitud):
    alt = rec.alt * FT_A_M if usar_altitud else 0
    return f"{rec.lon},{rec.lat},{alt:.1f}"


def _estilos():
    out = []
    for nombre, color in list(COLORES.items()) + [("DEFECTO", COLOR_DEFECTO)]:
        out.append(
            f'<Style id="pt_{nombre}"><IconStyle><color>{color}</color><scale>0.5</scale>'
            f'<Icon><href>http://maps.google.com/mapfiles/kml/shapes/shaded_dot.png</href></Icon>'
            f'</IconStyle><LabelStyle><scale>0</scale></LabelStyle></Style>'
        )
    out.append('<Style id="linea"><LineStyle><color>ffffffff</color><width>2</width></LineStyle></Style>')
    out.append('<Style id="salto"><LineStyle><color>ff00a5ff</color><width>4</width></LineStyle></Style>')
    out.append(
        '<Style id="thr"><IconStyle><scale>1.2</scale><Icon><href>'
        'http://maps.google.com/mapfiles/kml/paddle/wht-stars.png</href></Icon></IconStyle></Style>'
    )
    return "\n".join(out)


def export_arrival_kml(arrival, output_filename, thr_latlon=None,
                       usar_altitud=True, umbral_salto_nm=0.5):
    """
    Exporta la trayectoria de una Arrival a KML para Google Earth.

    Genera:
      - Linea blanca con la trayectoria completa.
      - Un punto por record, coloreado por sensor (verde ADSB, rojo Radar, amarillo interpolado),
        con TimeStamp para usar el slider temporal y datos en la descripcion.
      - Tramos entre records consecutivos con salto > umbral_salto_nm en naranja (para detectar zigzag).
      - Marcador del umbral (si se pasa thr_latlon=(lat, lon)).

    Parameters
    ----------
    arrival : Arrival
    output_filename : str
    thr_latlon : tuple[float, float] | None
    usar_altitud : bool   (altitud absoluta en ft -> m)
    umbral_salto_nm : float   (NM entre records consecutivos para marcar un salto)
    """
    recs = arrival.records
    nombre = f"{arrival.callsign}_FR{arrival.numfr}"
    alt_mode = "absolute" if usar_altitud else "clampToGround"

    partes = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
        f"<name>{escape(nombre)}</name>",
        _estilos(),
    ]

    # Trayectoria completa
    coords = " ".join(_coord(r, usar_altitud) for r in recs)
    partes.append(
        f'<Placemark><name>Trayectoria {escape(nombre)}</name><styleUrl>#linea</styleUrl>'
        f'<LineString><altitudeMode>{alt_mode}</altitudeMode><coordinates>{coords}</coordinates>'
        f'</LineString></Placemark>'
    )

    # Puntos por sensor
    partes.append("<Folder><name>Records</name>")
    for i, r in enumerate(recs):
        estilo = r.sensor if r.sensor in COLORES else "DEFECTO"
        desc = (f"idx={i} | t={int(r.time)} s | {r.sensor}<br/>"
                f"x={r.pos_x:.3f} y={r.pos_y:.3f} NM<br/>"
                f"alt={r.alt:.0f} ft | IAS={r.ias:.0f} | GS={r.gs:.0f}")
        partes.append(
            f'<Placemark><name>{i}</name><description><![CDATA[{desc}]]></description>'
            f'<styleUrl>#pt_{estilo}</styleUrl><TimeStamp><when>{_iso(r)}</when></TimeStamp>'
            f'<Point><altitudeMode>{alt_mode}</altitudeMode>'
            f'<coordinates>{_coord(r, usar_altitud)}</coordinates></Point></Placemark>'
        )
    partes.append("</Folder>")

    # Saltos sospechosos
    saltos = []
    for i in range(len(recs) - 1):
        a, b = recs[i], recs[i + 1]
        d = math.hypot(b.pos_x - a.pos_x, b.pos_y - a.pos_y)
        if d > umbral_salto_nm:
            saltos.append((i, d, a, b))
    partes.append(f"<Folder><name>Saltos &gt; {umbral_salto_nm} NM ({len(saltos)})</name>")
    for i, d, a, b in saltos:
        partes.append(
            f'<Placemark><name>salto {i}: {d:.2f} NM</name>'
            f'<description>{escape(a.sensor)} -&gt; {escape(b.sensor)} | t={int(a.time)}-{int(b.time)}</description>'
            f'<styleUrl>#salto</styleUrl><LineString><altitudeMode>{alt_mode}</altitudeMode>'
            f'<coordinates>{_coord(a, usar_altitud)} {_coord(b, usar_altitud)}</coordinates>'
            f'</LineString></Placemark>'
        )
    partes.append("</Folder>")

    # Umbral
    if thr_latlon is not None:
        lat, lon = thr_latlon
        partes.append(
            f'<Placemark><name>THR {escape(str(arrival.runway))}</name><styleUrl>#thr</styleUrl>'
            f'<Point><coordinates>{lon},{lat},0</coordinates></Point></Placemark>'
        )

    partes.append("</Document></kml>")

    with open(output_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(partes))
    print(f"-> KML exportado a '{output_filename}' ({len(recs)} records, {len(saltos)} saltos > {umbral_salto_nm} NM)")


def export_callsign_kml(arrivals, callsign, output_prefix="", **kwargs):
    """Exporta un KML por cada Arrival (frustradas incluidas) del callsign indicado."""
    for arr in arrivals:
        if arr.callsign == callsign:
            export_arrival_kml(arr, f"{output_prefix}{arr.callsign}_FR{arr.numfr}.kml", **kwargs)