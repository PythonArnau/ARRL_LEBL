import datetime as dt
import math
import os
import tempfile

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

pd.set_option("styler.render.max_elements", 2_000_000)

from Fligths import read_sql, read_frustrades, get_arrivals, get_tipo_frustrada
from Distancias import (
    LeaderFollower,
    radar_sparation,
    loa_separation,
    wake_separation,
    tod_to_hhmmss,
    export_pairs_to_excel,
)
from geo_utils2 import latlon_to_xy
from Airspeed import get_ias, get_time_to_thr, export_ias_to_excel, export_time_to_thr_excel
from kml_export import export_arrival_kml

# ──────────────────────────────────────────────────────────────────────────────
# Page config
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Dashboard ARR LEBL",
    page_icon="🛬",
    layout="wide",
)

# ──────────────────────────────────────────────────────────────────────────────
# Constantes
# ──────────────────────────────────────────────────────────────────────────────
THR_LATLON = {
    "LEBL-24R": (41 + 18 / 60 + 20.37 / 3600, 2 + 6 / 60 + 12.68 / 3600),
    "LEBL-06L": (41 + 17 / 60 + 41.70 / 3600, 2 + 4 / 60 + 19.97 / 3600),
    "LEBL-02": (41 + 17 / 60 + 16.66 / 3600, 2 + 5 / 60 + 5.76 / 3600),
    "LEBL-20": (41 + 18 / 60 + 32.85 / 3600, 2 + 5 / 60 + 40.51 / 3600),
}
THR = {rwy: latlon_to_xy(lat, lon) for rwy, (lat, lon) in THR_LATLON.items()}

RUNWAY_COLORS = {
    "LEBL-24R": "#1f77b4",
    "LEBL-06L": "#ff7f0e",
    "LEBL-02": "#2ca02c",
    "LEBL-20": "#d62728",
}
SENSOR_COLORS = {"ADSB-BCN": "#2ca02c", "Radar-BCN": "#d62728", "INTERPOLATED": "#e6a700"}

RECAT_ORDER = ["J", "H+", "H-", "M+", "M-", "L+"]
RADAR_MIN_NM = 2.4
DEFAULT_DAY = dt.date(2025, 1, 14)
DEFAULT_ARRIBADES_SQL = "arribades.sql"
DEFAULT_FRUSTRADES_SQL = "frustrades.sql"
MAX_SELECTED_TRAJ = 15
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Incumplimientos: nombre en el dashboard -> atributo de Pair
INC_ATTRS = {
    "Inc radar THR": "radar_thr",
    "Inc radar 4NM": "radar_4mile",
    "Inc LoA THR": "loa_thr",
    "Inc LoA 4NM": "loa_4mile",
    "Inc estela THR": "estela_thr",
    "Inc estela 4NM": "estela_4mile",
}
INC_COLS = list(INC_ATTRS.keys())

PAIR_COLS = [
    "idx", "Date", "THR_dt", "T4_dt", "hora", "Hora THR", "Hora 4NM",
    "Pareja", "Pista", "Líder", "Seguidor",
    "Frustrada líder", "Frustrada seguidor", "Tipo frustrada seguidor",
    "STAR", "Prev STAR", "Wake Cat", "Cat",
    "Prev Wake Cat", "Prev Cat", "Par RECAT",
    "Sep THR", "Sep 4NM",
    "Alt THR", "Alt 4NM",
] + INC_COLS + [
    "Sep operacional THR",
    "Sep operacional 4NM",
]

ARR_META = ["idx", "Date", "Vuelo", "Callsign", "Pista", "STAR", "Wake Cat", "Cat",
            "Hora llegada", "ATA", "hora", "Última", "Frustrada", "Tipo frustrada",
            "ias_THR", "gs_THR"]


# ──────────────────────────────────────────────────────────────────────────────
# Pipeline (cacheado por día + distancias)
# ──────────────────────────────────────────────────────────────────────────────
def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


@st.cache_resource(show_spinner=False)
def load_frustrades(path, mtime):
    """(Callsign) -> [(HoraFR, tipo)]  — mismo formato que usa main.py."""
    return read_frustrades(path)


@st.cache_resource(show_spinner=False)
def run_day(fecha, distancias: tuple, sql_path, sql_mtime):
    # sql_mtime solo forma parte de la clave de caché (si cambia el .sql se recalcula)
    vuelos = read_sql(sql_path, fecha)
    arrivals = get_arrivals(vuelos.values())

    # Solo pistas con umbral definido (si no, all_cum_dist fallaría)
    validas = [a for a in arrivals if a.runway in THR]
    descartadas = len(arrivals) - len(validas)

    pairs = LeaderFollower(validas, vuelos, THR)
    # Mismo orden de prioridad que main.py: estela -> radar -> LoA
    pairs = wake_separation(pairs)
    pairs = radar_sparation(pairs)
    pairs = loa_separation(pairs)

    validas = get_ias(validas, list(distancias), THR)
    validas = get_time_to_thr(validas, list(distancias), THR)

    info = {k: (f.wake, f.wake_recat, f.star) for k, f in vuelos.items()}
    return {
        "n_vuelos": len(vuelos),
        "arrivals": validas,
        "pairs": pairs,
        "descartadas": descartadas,
        "info": info,
    }


def load_range(d0, d1, distancias, sql_path, sql_mtime):
    days = [d0 + dt.timedelta(days=i) for i in range((d1 - d0).days + 1)]
    results, errores = [], []
    bar = st.progress(0.0, text="Cargando datos...")
    for i, d in enumerate(days):
        bar.progress(i / len(days), text=f"Procesando {d}...")
        try:
            results.append((d, run_day(d, tuple(distancias), sql_path, sql_mtime)))
        except Exception as e:  # un día con error no tumba el resto
            errores.append((d, str(e)))
    bar.empty()
    return results, errores


def nz(x):
    if x is None or x == "" or (isinstance(x, float) and math.isnan(x)):
        return "N/D"
    return str(x)


def _dt(base, seconds):
    if seconds is None:
        return pd.NaT
    return base + pd.to_timedelta(seconds, unit="s")


def build_data(results, distancias, key, tipos):
    pairs_all, arrs_all, p_rows, a_rows = [], [], [], []
    n_vuelos = descartadas = 0

    for d, r in results:
        n_vuelos += r["n_vuelos"]
        descartadas += r["descartadas"]
        base = pd.Timestamp(d)

        for p in r["pairs"]:
            i = len(pairs_all)
            pairs_all.append(p)
            thr_dt = _dt(base, p.tod_thr)
            t4_dt = _dt(base, p.tod_4mile)
            # Cruce de medianoche: el líder pasa por 4 NM antes de las 24:00 y por THR después
            if pd.notna(thr_dt) and pd.notna(t4_dt) and t4_dt > thr_dt:
                t4_dt -= pd.Timedelta(days=1)
            tipo_seg = None
            if p.frustrada_follower:
                tipo_seg = get_tipo_frustrada(p.follower, p.arr_hour_follower, tipos) or "N/D"
            row = {
                "idx": i, "Date": d,
                "THR_dt": thr_dt, "T4_dt": t4_dt,
                "hora": thr_dt.hour if pd.notna(thr_dt) else None,
                "Hora THR": tod_to_hhmmss(p.tod_thr), "Hora 4NM": tod_to_hhmmss(p.tod_4mile),
                "Pareja": p.pair, "Pista": p.runway, "Líder": p.leader, "Seguidor": p.follower,
                "Frustrada líder": bool(p.frustrada_leader),
                "Frustrada seguidor": bool(p.frustrada_follower),
                "Tipo frustrada seguidor": tipo_seg or "",
                "STAR": nz(p.star_follower), "Prev STAR": nz(p.star_leader),
                "Wake Cat": nz(p.wake_follower), "Cat": nz(p.wake_recat_follower),
                "Prev Wake Cat": nz(p.wake_leader), "Prev Cat": nz(p.wake_recat_leader),
                "Par RECAT": f"{nz(p.wake_recat_leader)} → {nz(p.wake_recat_follower)}",
                "Sep THR": p.separation_thr, "Sep 4NM": p.separation_4mile,
                "Alt THR": p.alt_thr, "Alt 4NM": p.alt_4mile,
                "Sep operacional THR": bool(p.sep_op_thr),
                "Sep operacional 4NM": bool(p.sep_op_4mile),

            }
            for col, attr in INC_ATTRS.items():
                row[col] = bool(getattr(p, attr))
            p_rows.append(row)

        for a in r["arrivals"]:
            i = len(arrs_all)
            arrs_all.append(a)
            wake, recat, star = r["info"].get((a.callsign, a.arr_hour), (None, None, None))
            ata = _dt(base, a.thr_record.time) if a.thr_record is not None else pd.NaT
            # Frustrada: en la BBDD cada aproximación llega como un Flight distinto (distinta
            # HoraARR) con su propio NumFR, así que a.last_arr no sirve (siempre True).
            # NumFR > 0 = frustrada (p.ej. PGT56PJ_FR1 = frustrada, PGT56PJ_FR0 = aterrizaje).
            es_frustrada = (a.numfr or 0) > 0 or not a.last_arr
            # Tipo de frustrada (ALPI...) desde frustrades.sql, igual que los export_* del proyecto
            tipo = None
            if es_frustrada:
                tipo = get_tipo_frustrada(a.callsign, a.arr_hour, tipos)
            frustrada_txt = "No" if not es_frustrada else (f"Sí - {tipo}" if tipo else "Sí")
            row = {
                "idx": i, "Date": d,
                "Vuelo": f"{a.callsign}_FR{a.numfr}", "Callsign": a.callsign, "Pista": a.runway,
                "STAR": nz(star), "Wake Cat": nz(wake), "Cat": nz(recat),
                "Hora llegada": pd.to_datetime(a.arr_hour, errors="coerce"),
                "ATA": ata, "hora": ata.hour if pd.notna(ata) else None,
                "Última": not es_frustrada,   # True = aproximación que termina en aterrizaje
                "Frustrada": frustrada_txt,
                "Tipo frustrada": tipo or ("N/D" if es_frustrada else ""),
                "ias_THR": a.ias_dict.get("THR"), "gs_THR": a.gs_dict.get("THR"),
            }
            for dist in distancias:
                row[f"ias_{dist}"] = a.ias_dict.get(dist)
                row[f"gs_{dist}"] = a.gs_dict.get(dist)
                row[f"t_{dist}"] = a.time_to_thr_dict.get(dist)
            a_rows.append(row)

    arr_cols = (ARR_META + [f"ias_{d}" for d in distancias]
                + [f"gs_{d}" for d in distancias] + [f"t_{d}" for d in distancias])
    pairs_df = pd.DataFrame(p_rows, columns=PAIR_COLS)
    arr_df = pd.DataFrame(a_rows, columns=arr_cols)
    for c in INC_COLS + [
        "Sep operacional THR",
        "Sep operacional 4NM",
        "Frustrada líder",
        "Frustrada seguidor",
    ]:
        pairs_df[c] = pairs_df[c].astype(bool)
    arr_df["Última"] = arr_df["Última"].astype(bool)

    return {
        "pairs": pairs_all, "arrivals": arrs_all,
        "pairs_df": pairs_df, "arr_df": arr_df,
        "n_vuelos": n_vuelos, "descartadas": descartadas,
        "dists": list(distancias), "key": key,
        "n_days": len(results), "tipos": tipos,
    }


def to_long(df, distancias):
    meta = ["idx", "Date", "Vuelo", "Pista", "STAR", "Wake Cat", "Cat", "ATA", "hora", "Última"]
    rows = []
    for r in df.to_dict("records"):
        base = {k: r[k] for k in meta}
        for d in distancias:
            rows.append({**base, "dist": d, "dist_label": f"{d} NM",
                         "ias": r[f"ias_{d}"], "gs": r[f"gs_{d}"], "tiempo": r[f"t_{d}"]})
    return pd.DataFrame(rows, columns=meta + ["dist", "dist_label", "ias", "gs", "tiempo"])


# ──────────────────────────────────────────────────────────────────────────────
# Excel: usa las funciones export_* del proyecto y devuelve los bytes
# ──────────────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def make_xlsx(kind, idx, distancias, load_key, _objs, _tipos):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "export.xlsx")
        if kind == "pairs":
            export_pairs_to_excel(_objs, path, _tipos)
        elif kind == "ias":
            export_ias_to_excel(_objs, list(distancias), path, _tipos)
        else:
            export_time_to_thr_excel(_objs, list(distancias), path, _tipos)
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            return f.read()


def xlsx_button(label, kind, idx, objs, file_name, key):
    data_bytes = make_xlsx(kind, tuple(idx), tuple(DATA["dists"]), DATA["key"], _objs=objs, _tipos=DATA["tipos"])
    if data_bytes is None:
        st.caption("Sin datos para exportar.")
        return
    st.download_button(label, data_bytes, file_name=file_name, mime=XLSX_MIME, key=key)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers: ventana pico
# ──────────────────────────────────────────────────────────────────────────────
def find_peak_window(ata_series: pd.Series, window_min: int = 60):
    """Devuelve (inicio_min, fin_min, nº) de la ventana de 60 min con más llegadas."""
    valid = ata_series.dropna()
    if valid.empty:
        return None, None, 0
    mins = valid.dt.hour * 60 + valid.dt.minute + valid.dt.second / 60.0
    lo = int(mins.min())
    hi = int(mins.max())
    best_start, best_count = lo, 0
    for start in range(lo, max(lo + 1, hi - window_min + 2)):
        cnt = int(((mins >= start) & (mins < start + window_min)).sum())
        if cnt > best_count:
            best_count = cnt
            best_start = start
    return best_start, best_start + window_min, best_count


def hour_overlaps_window(h: int, w_start, w_end) -> bool:
    if w_start is None:
        return False
    return h * 60 < w_end and (h + 1) * 60 > w_start


# ──────────────────────────────────────────────────────────────────────────────
# Sidebar (carga)
# ──────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🛬 Dashboard ARR LEBL")
    st.markdown("---")
    st.subheader("Filtros globales")

    date_from = st.date_input("Fecha inicio", value=DEFAULT_DAY, key="date_from")
    date_to = st.date_input("Fecha fin", value=DEFAULT_DAY, key="date_to")
    sel_dists = st.multiselect(
        "Distancias a THR (NM)",
        options=[1, 2, 2.5, 3, 4, 5, 6, 7, 8, 9, 10], 
        default=[1, 2, 2.5, 3, 4, 5, 6, 7, 8, 9, 10],
    )
    st.subheader("Ficheros SQL")
    sql_path = st.text_input("arribades.sql", value=DEFAULT_ARRIBADES_SQL, key="sql_path")
    fr_path = st.text_input("frustrades.sql", value=DEFAULT_FRUSTRADES_SQL, key="fr_path")
    load_clicked = st.button("Cargar datos", type="primary", width="stretch")

if load_clicked:
    if date_to < date_from:
        st.sidebar.error("La fecha fin es anterior a la fecha inicio.")
    elif not sel_dists:
        st.sidebar.warning("Selecciona al menos una distancia.")
    elif not os.path.isfile(sql_path):
        st.sidebar.error(f"No existe el fichero: {sql_path}")
    elif not os.path.isfile(fr_path):
        st.sidebar.error(f"No existe el fichero: {fr_path}")
    else:
        dists_sorted = sorted(sel_dists)
        tipos = load_frustrades(fr_path, _mtime(fr_path))
        results, errores = load_range(date_from, date_to, dists_sorted, sql_path, _mtime(sql_path))
        st.session_state["errores"] = errores
        if results:
            st.session_state["data"] = build_data(
                results, dists_sorted,
                (date_from, date_to, tuple(dists_sorted), sql_path, fr_path, _mtime(sql_path), _mtime(fr_path)),
                tipos,
            )
        else:
            st.session_state.pop("data", None)

for d_err, msg in st.session_state.get("errores", []):
    st.sidebar.error(f"{d_err}: {msg}")

if "data" not in st.session_state:
    st.info("Elige el rango de fechas y las distancias en la barra lateral y pulsa **Cargar datos**.")
    st.stop()

DATA = st.session_state["data"]
dists = DATA["dists"]
pairs_df: pd.DataFrame = DATA["pairs_df"]
arr_df: pd.DataFrame = DATA["arr_df"]

if arr_df.empty:
    st.warning("No hay aproximaciones para el rango seleccionado.")
    st.stop()

# ──────────────────────────────────────────────────────────────────────────────
# Sidebar (filtros sobre los datos cargados)
# ──────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    available_runways = sorted(set(arr_df["Pista"].dropna()) | set(pairs_df["Pista"].dropna()))
    sel_runways = st.multiselect("Pista", options=available_runways, default=available_runways)

    available_wake = sorted(set(arr_df["Wake Cat"]) | set(pairs_df["Wake Cat"]))
    sel_wake = st.multiselect("Wake Cat", options=available_wake, default=available_wake)

    available_cat = sorted(set(arr_df["Cat"]) | set(pairs_df["Cat"]))
    sel_cat = st.multiselect("Cat", options=available_cat, default=available_cat)

    excl_fr = st.checkbox("Excluir frustradas en IAS / GS / tiempos", value=True)
    excl_fr_pairs = st.checkbox("Excluir parejas con frustrada (líder o seguidor)", value=False)

    st.markdown("---")
    st.caption(
        f"📂 {DATA['n_days']} día(s) cargado(s) · {len(arr_df)} aproximaciones · "
        f"{len(pairs_df)} parejas"
    )
    if DATA["descartadas"]:
        st.caption(f"⚠️ {DATA['descartadas']} aproximaciones descartadas (pista sin umbral definido).")


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    return df[
        df["Pista"].isin(sel_runways)
        & df["Wake Cat"].isin(sel_wake)
        & df["Cat"].isin(sel_cat)
    ].copy()


pairs_f = apply_filters(pairs_df)       # el filtro Wake/Cat se aplica al seguidor (Callsign)
if excl_fr_pairs:
    pairs_f = pairs_f[~(pairs_f["Frustrada líder"] | pairs_f["Frustrada seguidor"])]
arr_g = apply_filters(arr_df)           # todas las aproximaciones filtradas
arr_f = arr_g[arr_g["Última"]] if excl_fr else arr_g
arr_long = to_long(arr_f, dists)

if arr_g.empty and pairs_f.empty:
    st.warning("No hay datos para los filtros seleccionados.")
    st.stop()


# ──────────────────────────────────────────────────────────────────────────────
# Tabs
# ──────────────────────────────────────────────────────────────────────────────
def tab_resumen():
    st.header("Resumen diario")

    landings = arr_g[arr_g["Última"]]

    n_land = len(landings)
    n_ga = int((~arr_g["Última"]).sum())

    n_pairs = len(pairs_f)

    # Parejas con algún incumplimiento
    n_inc = int(pairs_f[INC_COLS].any(axis=1).sum())

    # Separación operacional
    n_op_thr = int(pairs_f["Sep operacional THR"].sum())
    n_op_4nm = int(pairs_f["Sep operacional 4NM"].sum())
    n_op_total = int(
        pairs_f[["Sep operacional THR", "Sep operacional 4NM"]]
        .any(axis=1)
        .sum()
    )

    k1, k2, k3, k4 = st.columns(4)

    k1.metric("🛬 Llegadas", f"{n_land:,}")

    n_fr_flights = arr_g.loc[~arr_g["Última"], "Callsign"].nunique()

    k2.metric(
        "🔁 Frustradas",
        f"{n_ga:,}",
        delta=f"{n_fr_flights} vuelo(s)" if n_ga else None,
        delta_color="off",
    )

    k3.metric(
        "⚠️ Parejas con incumplimiento",
        f"{n_inc:,}",
        delta=f"{n_inc / n_pairs * 100:.1f}%" if n_pairs else "0%",
        delta_color="inverse",
    )

    k4.metric(
        "🔴 Separación operacional",
        f"{n_op_total:,}",
        delta=f"THR: {n_op_thr} | 4NM: {n_op_4nm}",
        delta_color="off",
    )

    st.markdown("---")

    # ── Llegadas por hora con ventana pico ────────────────────────────────────
    hours = list(range(24))
    hour_counts = landings.groupby("hora").size().reindex(hours, fill_value=0)

    single_day = landings["Date"].nunique() == 1
    w_start, w_end, w_count = find_peak_window(landings["ATA"]) if single_day else (None, None, 0)
    colors = ["#FF6B35" if hour_overlaps_window(h, w_start, w_end) else "#4C72B0" for h in hours]

    if single_day and w_start is not None:
        wh_s = f"{w_start // 60:02d}:{w_start % 60:02d}"
        wh_e = f"{w_end // 60:02d}:{w_end % 60:02d}"
        title_extra = f"<br><sup style='color:#FF6B35'>Ventana pico: {wh_s}–{wh_e} ({w_count} llegadas)</sup>"
    else:
        title_extra = ""

    fig_hourly = go.Figure(
        go.Bar(
            x=hours, y=hour_counts.values, marker_color=colors,
            text=hour_counts.values, textposition="outside",
            hovertemplate="Hora %{x}:00<br>%{y} llegadas<extra></extra>",
        )
    )
    fig_hourly.update_layout(
        title=f"Llegadas por hora{title_extra}",
        xaxis=dict(title="Hora", tickmode="linear", tick0=0, dtick=1),
        yaxis=dict(title="Nº llegadas"),
        showlegend=False, height=380,
    )
    st.plotly_chart(fig_hourly, width="stretch", key="res_hourly")

    # ── Parejas por pista ─────────────────────────────────────────────────────
    c1, c2 = st.columns(2)
    with c1:
        cnt = landings.groupby("Pista").size().reset_index(name="Llegadas")
        st.plotly_chart(
            px.bar(cnt, x="Pista", y="Llegadas", color="Pista", color_discrete_map=RUNWAY_COLORS,
                   title="Llegadas por pista", text="Llegadas"),
            width="stretch", key="res_runway",
        )
    with c2:
        if not arr_long.empty:
            resumen = arr_long.groupby("dist").agg(
                ias_media=("ias", "mean"), ias_mediana=("ias", "median"),
                t_media=("tiempo", "mean"), t_mediana=("tiempo", "median"),
            ).reset_index()
            resumen.columns = ["Distancia (NM)", "IAS media (kt)", "IAS mediana (kt)",
                               "Tiempo medio (s)", "Tiempo mediana (s)"]
            st.subheader("IAS y tiempo a THR por distancia")
            st.dataframe(resumen.round(1), width="stretch", hide_index=True)

    # ── Frustradas ────────────────────────────────────────────────────────────
    fr = arr_g[~arr_g["Última"]]
    if not fr.empty:
        st.subheader("Aproximaciones frustradas")
        cf1, cf2 = st.columns([1, 2])
        with cf1:
            por_tipo = fr.groupby("Tipo frustrada").size().reset_index(name="Nº")
            st.plotly_chart(
                px.bar(por_tipo, x="Tipo frustrada", y="Nº", text="Nº", title="Frustradas por tipo"),
                width="stretch", key="res_fr_tipo",
            )
        with cf2:
            fr_tab = fr[["Date", "Vuelo", "Tipo frustrada", "Pista", "STAR", "Wake Cat", "Cat", "ATA"]].copy()
            fr_tab["ATA"] = fr_tab["ATA"].dt.strftime("%H:%M:%S")
            fr_tab = fr_tab.rename(columns={"ATA": "Hora THR (punto más cercano)"})
            st.dataframe(fr_tab, width="stretch", hide_index=True)

    # ── Resumen por fecha ─────────────────────────────────────────────────────
    st.subheader("Resumen por fecha")

    rows = []
    for date in sorted(arr_g["Date"].unique()):
        a_d = arr_g[arr_g["Date"] == date]
        p_d = pairs_f[pairs_f["Date"] == date]
        n = len(p_d)
        n_i = int(p_d[INC_COLS].any(axis=1).sum())
        n_op_thr = int(p_d["Sep operacional THR"].sum())
        n_op_4nm = int(p_d["Sep operacional 4NM"].sum())
        n_op = int(p_d[["Sep operacional THR", "Sep operacional 4NM"]].any(axis=1).sum())
        rows.append({
            "Fecha": str(date),
            "Llegadas": int(a_d["Última"].sum()),
            "Frustradas": int((~a_d["Última"]).sum()),
            "Parejas": n,
            "Con incumplimiento": n_i,
            "% incumplimiento": f"{n_i / n * 100:.1f}%" if n else "0%",
            "Sep. operacional": n_op,
            "Sep. op. THR": n_op_thr,
            "Sep. op. 4NM": n_op_4nm,
            "% sep. operacional": f"{n_op / n * 100:.1f}%" if n else "0%",
        })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def tab_tabla():
    st.header("Tablas")

    # ── Parejas ───────────────────────────────────────────────────────────────
    st.subheader("Parejas líder – seguidor")
    all_stars = sorted(pairs_f["STAR"].dropna().unique().tolist())
    sel_stars = st.multiselect("Filtrar por STAR (seguidor)", options=all_stars, default=all_stars)
    df_tab = pairs_f[pairs_f["STAR"].isin(sel_stars)].copy() if sel_stars else pairs_f.copy()

    st.caption(
        "ℹ️ **Seguidor** = tráfico que puede cometer el incumplimiento. "
        "**Prev** = tráfico precedente (líder). Sep. en NM, alturas en ft."
    )
    st.caption(f"Mostrando {len(df_tab):,} parejas")

    if df_tab.empty:
        st.info("No hay parejas para los filtros seleccionados.")
    else:
        df_tab["⚠️ Inc"] = df_tab[INC_COLS].any(axis=1)
        display_cols = (
            ["Date", "Hora THR", "Pareja", "Pista", "Líder", "Seguidor", "STAR", "Prev STAR",
             "Wake Cat", "Cat", "Prev Wake Cat", "Prev Cat", "⚠️ Inc",
             "Frustrada líder", "Frustrada seguidor", "Tipo frustrada seguidor"]
            + INC_COLS
            + ["Sep operacional THR", "Sep operacional 4NM", "Hora 4NM", "Sep 4NM", "Alt 4NM", "Sep THR", "Alt THR"]
        )

        def _style(row):
            if row["Sep operacional THR"] or row["Sep operacional 4NM"]:
                return ["background-color: #ffcccc"] * len(row)
            if bool(row.get("⚠️ Inc")):
                return ["background-color: #ffe8e8"] * len(row)
            return [""] * len(row)

        fmt = {c: "{:.2f}" for c in ["Sep 4NM", "Sep THR"]}
        fmt.update({c: "{:.0f}" for c in ["Alt 4NM", "Alt THR"]})
        styled = df_tab[display_cols].style.apply(_style, axis=1).format(fmt, na_rep="")
        st.dataframe(styled, width="stretch", hide_index=True)

        xlsx_button(
            "⬇️ Excel de separaciones", "pairs", df_tab["idx"].tolist(),
            [DATA["pairs"][i] for i in df_tab["idx"]],
            "separaciones.xlsx", "dl_pairs",
        )

    st.markdown("---")

    # ── Aproximaciones: IAS y tiempo a THR ────────────────────────────────────
    st.subheader("Aproximaciones: IAS y tiempo a THR")
    st.caption(f"Mostrando {len(arr_f):,} aproximaciones"
               + (" (sin frustradas)" if excl_fr else " (con frustradas)"))
    if arr_f.empty:
        st.info("No hay aproximaciones para los filtros seleccionados.")
        return

    arr_tab = arr_f[["Date", "Vuelo", "Frustrada", "Pista", "STAR", "Wake Cat", "Cat", "ATA", "Última",
                     "ias_THR", "gs_THR"]
                    + [f"ias_{d}" for d in dists] + [f"gs_{d}" for d in dists]
                    + [f"t_{d}" for d in dists]].copy()
    arr_tab["ATA"] = arr_tab["ATA"].dt.strftime("%H:%M:%S")
    arr_tab = arr_tab.rename(columns={"ATA": "Hora THR"}
                             | {"ias_THR": "IAS THR", "gs_THR": "GS THR"}
                             | {f"ias_{d}": f"IAS {d} NM" for d in dists}
                             | {f"gs_{d}": f"GS {d} NM" for d in dists}
                             | {f"t_{d}": f"Tiempo {d} NM (s)" for d in dists})
    fmt_a = ({f"IAS {d} NM": "{:.0f}" for d in dists} | {f"GS {d} NM": "{:.0f}" for d in dists}
             | {f"Tiempo {d} NM (s)": "{:.0f}" for d in dists} | {"IAS THR": "{:.0f}", "GS THR": "{:.0f}"})
    st.dataframe(arr_tab.style.format(fmt_a, na_rep=""), width="stretch", hide_index=True)

    idx_a = arr_f["idx"].tolist()
    objs_a = [DATA["arrivals"][i] for i in idx_a]
    b1, b2, _ = st.columns([1, 1, 3])
    with b1:
        xlsx_button("⬇️ Excel de IAS", "ias", idx_a, objs_a, "ias.xlsx", "dl_ias_tab")
    with b2:
        xlsx_button("⬇️ Excel de tiempo a THR", "time", idx_a, objs_a, "tiempo_a_thr.xlsx", "dl_time_tab")


def tab_separacion():
    st.header("Gráficas de separación")

    if pairs_f.empty:
        st.info("No hay parejas de tráfico en los datos seleccionados.")
        return

    # ── Histogramas ───────────────────────────────────────────────────────────
    st.subheader("Distribución de separaciones")
    c1, c2 = st.columns(2)
    for col, (campo, titulo) in zip((c1, c2), (("Sep 4NM", "Separación en 4 NM"),
                                                ("Sep THR", "Separación en THR"))):
        with col:
            d = pairs_f[pairs_f[campo].notna()]
            fig = px.histogram(
                d, x=campo, color="Pista", color_discrete_map=RUNWAY_COLORS,
                nbins=40, barmode="overlay", opacity=0.75,
                labels={campo: f"{campo} (NM)", "count": "Nº parejas"}, title=titulo,
            )
            
            fig.update_layout(legend_title_text="Pista")
            st.plotly_chart(fig, width="stretch", key=f"sep_hist_{campo}")

    # ── Evolución temporal ────────────────────────────────────────────────────
    st.subheader("Evolución temporal de separaciones")
    hover = ["Pareja", "STAR", "Par RECAT"]
    for campo, tcol, titulo in (("Sep 4NM", "T4_dt", "Evolución temporal Sep 4NM"),
                                ("Sep THR", "THR_dt", "Evolución temporal Sep THR")):
        d = pairs_f[pairs_f[campo].notna()].sort_values(tcol)
        fig = px.scatter(
            d, x=tcol, y=campo, color="Pista", color_discrete_map=RUNWAY_COLORS,
            labels={tcol: "Hora del líder", campo: f"{campo} (NM)"},
            title=titulo, hover_data=hover,
        )

        fig.update_traces(marker=dict(size=6, opacity=0.7))
        fig.update_layout(legend_title_text="Pista", height=360)
        st.plotly_chart(fig, width="stretch", key=f"sep_time_{campo}")

    # ── 4 NM vs THR y mapa de calor RECAT ─────────────────────────────────────
    st.subheader("Relación entre puntos y combinación RECAT")
    c1, c2 = st.columns(2)
    with c1:
        d = pairs_f.dropna(subset=["Sep 4NM", "Sep THR"])
        fig = px.scatter(
            d, x="Sep 4NM", y="Sep THR", color="Pista", color_discrete_map=RUNWAY_COLORS,
            hover_name="Pareja", hover_data=["Par RECAT", "Hora THR"],
            title="Separación 4 NM vs THR",
        )

        fig.update_layout(legend_title_text="Pista")
        st.plotly_chart(fig, width="stretch", key="sep_scatter")
    with c2:
        punto = st.radio("Punto de medida", ["THR", "4NM"], horizontal=True, key="sep_punto")
        campo = "Sep THR" if punto == "THR" else "Sep 4NM"
        piv = pairs_f.pivot_table(index="Prev Cat", columns="Cat", values=campo, aggfunc="mean")
        if piv.empty:
            st.info("Sin datos para el mapa de calor.")
        else:
            piv = piv.reindex(index=[c for c in RECAT_ORDER if c in piv.index],
                              columns=[c for c in RECAT_ORDER if c in piv.columns])
            fig = px.imshow(
                piv, text_auto=".1f", aspect="auto", color_continuous_scale="RdYlGn",
                title=f"Separación media en {punto} (RECAT líder × seguidor)",
                labels=dict(x="Seguidor", y="Líder", color="NM"),
            )
            st.plotly_chart(fig, width="stretch", key="sep_heat")


def tab_incumplimientos():
    st.header("Análisis de incumplimientos")

    total = len(pairs_f)
    if total == 0:
        st.info("No hay parejas en los datos seleccionados.")
        return

    # ── Total por tipo ────────────────────────────────────────────────────────
    counts = {c: int(pairs_f[c].sum()) for c in INC_COLS}
    counts["Sep operacional THR"] = int(pairs_f["Sep operacional THR"].sum())
    counts["Sep operacional 4NM"] = int(pairs_f["Sep operacional 4NM"].sum())
    df_counts = pd.DataFrame(list(counts.items()), columns=["Tipo incumplimiento", "Nº casos"])
    df_counts = df_counts.sort_values("Nº casos", ascending=True)
    df_counts["% sobre total"] = (df_counts["Nº casos"] / total * 100).round(1)

    c1, c2 = st.columns([2, 1])
    with c1:
        fig = px.bar(
            df_counts, x="Nº casos", y="Tipo incumplimiento", orientation="h", text="Nº casos",
            color="Nº casos", color_continuous_scale="Reds",
            title="Total incumplimientos por tipo (seguidor)",
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(showlegend=False, coloraxis_showscale=False, height=360)
        st.plotly_chart(fig, width="stretch", key="inc_total")
    with c2:
        st.dataframe(df_counts, width="stretch", hide_index=True)

    st.markdown("---")

    df_any = pairs_f[pairs_f[INC_COLS].any(axis=1)]
    if df_any.empty:
        st.success("No hay incumplimientos en los datos seleccionados.")
    else:
        for campo, titulo, barmode in (("STAR", "Desglose por STAR (seguidor)", "stack"),
                                       ("Pista", "Desglose por pista", "group")):
            st.subheader(titulo)
            g = df_any.groupby(campo)[INC_COLS].sum().reset_index()
            m = g.melt(id_vars=campo, var_name="Tipo", value_name="Casos")
            m = m[m["Casos"] > 0]
            fig = px.bar(m, x=campo, y="Casos", color="Tipo", barmode=barmode,
                         title=f"Incumplimientos por {campo}")
            fig.update_layout(xaxis_tickangle=-45, height=400)
            st.plotly_chart(fig, width="stretch", key=f"inc_by_{campo}")

        c1, c2 = st.columns(2)
        for col, campo in zip((c1, c2), ("Wake Cat", "Cat")):
            with col:
                st.subheader(f"Desglose por {campo} (seguidor)")
                g = df_any.groupby(campo)[INC_COLS].sum().reset_index()
                m = g.melt(id_vars=campo, var_name="Tipo", value_name="Casos")
                m = m[m["Casos"] > 0]
                fig = px.bar(m, x=campo, y="Casos", color="Tipo", barmode="group",
                             title=f"Incumplimientos por {campo}")
                st.plotly_chart(fig, width="stretch", key=f"inc_by_{campo}")

    st.markdown("---")

    # ── Separación operacional ────────────────────────────────────────────────
    st.subheader("Separación operacional")
    n_op_thr = int(pairs_f["Sep operacional THR"].sum())
    n_op_4nm = int(pairs_f["Sep operacional 4NM"].sum())

    n_op = int(
        pairs_f[
            ["Sep operacional THR", "Sep operacional 4NM"]
        ].any(axis=1).sum()
    )

    st.metric(
        "Parejas con separación operacional",
        n_op,
        delta=f"THR: {n_op_thr} | 4NM: {n_op_4nm}",
        delta_color="off",
    )

    df_op = pairs_f[
    pairs_f[
        ["Sep operacional THR", "Sep operacional 4NM"]
    ].any(axis=1)
]
    if df_op.empty:
        st.success("No se han detectado separaciones operacionales.")
    else:
        show = [
    "Date",
    "Hora THR",
    "Pareja",
    "Pista",
    "STAR",
    "Par RECAT",
    "Sep operacional THR",
    "Sep operacional 4NM",
    "Sep 4NM",
    "Alt 4NM",
    "Sep THR",
    "Alt THR",
] + INC_COLS
        st.dataframe(df_op[show].reset_index(drop=True), width="stretch", hide_index=True)


def tab_metric(col: str, nombre: str, unidad: str, key: str):
    """Pestaña genérica para IAS o tiempo a THR."""
    if arr_long.empty or arr_long[col].notna().sum() == 0:
        st.info("No hay datos en la selección actual.")
        return

    d_sel = st.selectbox("Distancia a THR (NM)", dists, index=min(1, len(dists) - 1), key=f"{key}_d")
    sub = arr_long[(arr_long["dist"] == d_sel)].dropna(subset=[col])
    if sub.empty:
        st.info(f"No hay datos a {d_sel} NM.")
        return
    orden = [f"{d} NM" for d in dists]

    k1, k2, k3, k4 = st.columns(4)
    k1.metric(f"Mínimo ({unidad})", f"{sub[col].min():.0f}")
    k2.metric(f"Media ({unidad})", f"{sub[col].mean():.0f}")
    k3.metric(f"Mediana ({unidad})", f"{sub[col].median():.0f}")
    k4.metric(f"Máximo ({unidad})", f"{sub[col].max():.0f}")
    st.markdown("---")

    c1, c2 = st.columns(2)
    with c1:
        fig = px.box(
            arr_long.dropna(subset=[col]), x="dist_label", y=col, color="Pista",
            color_discrete_map=RUNWAY_COLORS, category_orders={"dist_label": orden},
            points="outliers",
            labels={"dist_label": "Distancia", col: f"{nombre} ({unidad})"},
            title=f"{nombre} por distancia a THR",
        )
        fig.update_layout(legend_title_text="Pista", height=380)
        st.plotly_chart(fig, width="stretch", key=f"{key}_box")
    with c2:
        perfil = arr_long.groupby(["Pista", "dist"])[col].mean().reset_index()
        fig = px.line(
            perfil, x="dist", y=col, color="Pista", color_discrete_map=RUNWAY_COLORS, markers=True,
            labels={"dist": "Distancia a THR (NM)", col: f"{nombre} media ({unidad})"},
            title=f"{nombre} medio vs distancia a THR",
        )
        fig.update_layout(legend_title_text="Pista", height=380)
        st.plotly_chart(fig, width="stretch", key=f"{key}_perfil")

    st.subheader(f"Detalle a {d_sel} NM")
    c1, c2 = st.columns(2)
    with c1:
        fig = px.histogram(
            sub, x=col, color="Pista", color_discrete_map=RUNWAY_COLORS,
            nbins=40, barmode="overlay", opacity=0.75,
            labels={col: f"{nombre} ({unidad})", "count": "Nº aproximaciones"},
            title=f"Distribución de {nombre} a {d_sel} NM",
        )
        fig.update_layout(legend_title_text="Pista", height=380)
        st.plotly_chart(fig, width="stretch", key=f"{key}_hist")
    with c2:
        d_t = sub[sub["ATA"].notna()].sort_values("ATA")
        fig = px.scatter(
            d_t, x="ATA", y=col, color="Pista", color_discrete_map=RUNWAY_COLORS,
            hover_data=["Vuelo", "STAR", "Wake Cat"],
            labels={"ATA": "Hora de paso por THR", col: f"{nombre} ({unidad})"},
            title=f"Evolución temporal de {nombre} a {d_sel} NM",
        )
        fig.update_traces(marker=dict(size=6, opacity=0.7))
        fig.update_layout(legend_title_text="Pista", height=380)
        st.plotly_chart(fig, width="stretch", key=f"{key}_time")

    # Por STAR
    sub_star = sub[sub["STAR"].notna()]
    orden_star = sub_star.groupby("STAR")[col].median().sort_values().index.tolist()
    fig = px.box(
        sub_star, x="STAR", y=col, color="Pista", color_discrete_map=RUNWAY_COLORS,
        category_orders={"STAR": orden_star}, points="outliers",
        labels={col: f"{nombre} ({unidad})"}, title=f"{nombre} a {d_sel} NM por STAR",
    )
    fig.update_layout(legend_title_text="Pista", height=400, xaxis_tickangle=-45)
    st.plotly_chart(fig, width="stretch", key=f"{key}_star")

    # Por fecha (solo con varios días)
    if sub["Date"].nunique() > 1:
        sub = sub.assign(Date_str=sub["Date"].astype(str))
        fig = px.box(
            sub, x="Date_str", y=col, color="Pista", color_discrete_map=RUNWAY_COLORS,
            category_orders={"Date_str": sorted(sub["Date_str"].unique())}, points="outliers",
            labels={col: f"{nombre} ({unidad})", "Date_str": "Fecha"},
            title=f"Distribución de {nombre} a {d_sel} NM por día",
        )
        fig.update_layout(legend_title_text="Pista", height=400, xaxis_tickangle=-30)
        st.plotly_chart(fig, width="stretch", key=f"{key}_date")


def tab_ias():
    st.header("Velocidad indicada (IAS) a distintas distancias de THR")
    tab_metric("ias", "IAS", "kt", "ias")
    if not arr_f.empty:
        idx_a = arr_f["idx"].tolist()
        xlsx_button("⬇️ Excel de IAS", "ias", idx_a, [DATA["arrivals"][i] for i in idx_a],
                    "ias.xlsx", "dl_ias")


def tab_gs():
    st.header("Velocidad respecto al suelo (GS) a distintas distancias de THR")
    tab_metric("gs", "GS", "kt", "gs")
    if not arr_f.empty:
        st.caption("El Excel de IAS incluye también la GS (IAS THR/GS THR y a cada distancia).")


def tab_tiempo():
    st.header("Tiempo hasta THR desde distintas distancias")
    tab_metric("tiempo", "Tiempo a THR", "s", "time")

    if not arr_long.empty and arr_long["tiempo"].notna().any():
        d_sel = st.session_state.get("time_d", dists[min(1, len(dists) - 1)])
        sub = arr_long[arr_long["dist"] == d_sel].dropna(subset=["tiempo", "ias"])
        if not sub.empty:
            fig = px.scatter(
                sub, x="ias", y="tiempo", color="Pista", color_discrete_map=RUNWAY_COLORS,
                hover_name="Vuelo", hover_data=["STAR", "Wake Cat"],
                labels={"ias": "IAS (kt)", "tiempo": "Tiempo a THR (s)"},
                title=f"IAS vs tiempo a THR a {d_sel} NM",
            )
            fig.update_layout(legend_title_text="Pista", height=380)
            st.plotly_chart(fig, width="stretch", key="time_ias_scatter")

    if not arr_f.empty:
        idx_a = arr_f["idx"].tolist()
        xlsx_button("⬇️ Excel de tiempo a THR", "time", idx_a, [DATA["arrivals"][i] for i in idx_a],
                    "tiempo_a_thr.xlsx", "dl_time")


def tab_trayectorias():
    st.header("Trayectorias")

    if arr_g.empty:
        st.info("No hay aproximaciones en los datos seleccionados.")
        return

    # Selector de aproximaciones
    label_idx = {}
    for r in arr_g.sort_values("ATA").to_dict("records"):
        ts = r["ATA"].strftime("%H:%M:%S") if pd.notna(r["ATA"]) else "s/h"
        label_idx[f"{r['Vuelo']} · {r['Date']} {ts} · {r['Pista']}"] = r["idx"]
    opciones = list(label_idx.keys())

    sel = st.multiselect(
        f"Aproximaciones a visualizar (máx. {MAX_SELECTED_TRAJ})", opciones,
        default=opciones[:3], max_selections=MAX_SELECTED_TRAJ,
    )
    if not sel:
        st.info("Selecciona al menos una aproximación.")
        return

    map_style = "open-street-map"
    by_sensor = False

    arrs = {lab: DATA["arrivals"][label_idx[lab]] for lab in sel}
    palette = px.colors.qualitative.Plotly

    # ── Mapa ──────────────────────────────────────────────────────────────────
    fig = go.Figure()
    sensor_pts = {s: {"lat": [], "lon": [], "text": []} for s in SENSOR_COLORS}
    thr_pts = {"lat": [], "lon": []}
    nm4_pts = {"lat": [], "lon": []}
    all_lat, all_lon = [], []

    for n, (lab, a) in enumerate(arrs.items()):
        color = palette[n % len(palette)]
        lats = [r.lat for r in a.records]
        lons = [r.lon for r in a.records]
        texts = [
            f"{a.callsign}_FR{a.numfr}<br>{tod_to_hhmmss(r.time)} · {r.sensor}"
            f"<br>Alt {r.alt:.0f} ft · IAS {r.ias:.0f} kt"
            for r in a.records
        ]
        all_lat += lats
        all_lon += lons

        if by_sensor:
            fig.add_trace(go.Scattermap(
                lat=lats, lon=lons, mode="lines", line=dict(width=2, color=color),
                name=f"{a.callsign}_FR{a.numfr}", hoverinfo="skip",
            ))
            for r, tx in zip(a.records, texts):
                bucket = sensor_pts.get(r.sensor, sensor_pts["INTERPOLATED"])
                bucket["lat"].append(r.lat)
                bucket["lon"].append(r.lon)
                bucket["text"].append(tx)
        else:
            fig.add_trace(go.Scattermap(
                lat=lats, lon=lons, mode="lines+markers",
                line=dict(width=3, color=color), marker=dict(size=4, color=color),
                name=f"{a.callsign}_FR{a.numfr}", text=texts, hoverinfo="text",
            ))

        if a.thr_record is not None:
            thr_pts["lat"].append(a.thr_record.lat)
            thr_pts["lon"].append(a.thr_record.lon)
        if a.mile4_record is not None:
            nm4_pts["lat"].append(a.mile4_record.lat)
            nm4_pts["lon"].append(a.mile4_record.lon)

    if by_sensor:
        for s, b in sensor_pts.items():
            if b["lat"]:
                fig.add_trace(go.Scattermap(
                    lat=b["lat"], lon=b["lon"], mode="markers",
                    marker=dict(size=6, color=SENSOR_COLORS[s]), name=s,
                    text=b["text"], hoverinfo="text",
                ))

    if nm4_pts["lat"]:
        fig.add_trace(go.Scattermap(
            lat=nm4_pts["lat"], lon=nm4_pts["lon"], mode="markers+text", text=["4 NM"] * len(nm4_pts["lat"]),
            textposition="top right", marker=dict(size=11, color="#6a1b9a"), name="Record 4 NM",
        ))
    if thr_pts["lat"]:
        fig.add_trace(go.Scattermap(
            lat=thr_pts["lat"], lon=thr_pts["lon"], mode="markers+text", text=["THR"] * len(thr_pts["lat"]),
            textposition="top right", marker=dict(size=11, color="black"), name="Record THR",
        ))

    rwys = sorted({a.runway for a in arrs.values() if a.runway in THR_LATLON})
    if rwys:
        fig.add_trace(go.Scattermap(
            lat=[THR_LATLON[r][0] for r in rwys], lon=[THR_LATLON[r][1] for r in rwys],
            mode="markers+text", text=rwys, textposition="bottom right",
            marker=dict(size=14, color="#e53935"), name="Umbral (Google Earth)",
        ))

    fig.update_layout(
        map_style=map_style,
        map_center=dict(lat=sum(all_lat) / len(all_lat), lon=sum(all_lon) / len(all_lon)),
        map_zoom=9.5,
        height=680, margin=dict(l=0, r=0, t=10, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
    )
    st.plotly_chart(fig, width="stretch", key="traj_map")

    # ── Control de calidad ────────────────────────────────────────────────────
    st.subheader("Control de calidad de las trayectorias")
    qc = []
    for lab, a in arrs.items():
        recs = a.records
        saltos = [math.hypot(b.pos_x - r.pos_x, b.pos_y - r.pos_y) for r, b in zip(recs, recs[1:])]
        qc.append({
            "Vuelo": f"{a.callsign}_FR{a.numfr}",
            "Pista": a.runway,
            "Records": len(recs),
            "Sensores": ", ".join(sorted({r.sensor for r in recs})),
            "cum_dist máx (NM)": round(max(a.cum_dist), 1) if a.cum_dist else None,
            "Mayor salto entre records (NM)": round(max(saltos), 2) if saltos else None,
        })
    qc_df = pd.DataFrame(qc)
    st.dataframe(qc_df, width="stretch", hide_index=True)
    sospechosos = qc_df[qc_df["Mayor salto entre records (NM)"].fillna(0) > 0.5]
    if not sospechosos.empty:
        st.warning(
            "Hay saltos de más de 0,5 NM entre records de 1 s (físicamente imposibles) en: "
            + ", ".join(sospechosos["Vuelo"])
        )

    # ── Perfiles verticales y de IAS ──────────────────────────────────────────
    rows = []
    for lab, a in arrs.items():
        try:
            i_thr = a.records.index(a.thr_record)
        except ValueError:
            i_thr = len(a.records) - 1
        for r, cd in zip(a.records[: i_thr + 1], a.cum_dist[: i_thr + 1]):
            if cd <= 30:
                rows.append({"Vuelo": f"{a.callsign}_FR{a.numfr}", "cum_dist": cd,
                             "alt": r.alt, "ias": r.ias})
    perfil = pd.DataFrame(rows, columns=["Vuelo", "cum_dist", "alt", "ias"])
    if not perfil.empty:
        c1, c2 = st.columns(2)
        with c1:
            f = px.line(perfil, x="cum_dist", y="alt", color="Vuelo", title="Perfil vertical (últimas 30 NM)",
                        labels={"cum_dist": "Distancia acumulada a THR (NM)", "alt": "Altitud (ft)"})
            f.update_xaxes(autorange="reversed")
            st.plotly_chart(f, width="stretch", key="traj_alt")
        with c2:
            f = px.line(perfil, x="cum_dist", y="ias", color="Vuelo", title="Perfil de IAS (últimas 30 NM)",
                        labels={"cum_dist": "Distancia acumulada a THR (NM)", "ias": "IAS (kt)"})
            f.update_xaxes(autorange="reversed")
            st.plotly_chart(f, width="stretch", key="traj_ias")

    # ── KML ───────────────────────────────────────────────────────────────────
    st.subheader("Exportar a Google Earth")
    lab_kml = st.selectbox("Aproximación", sel, key="kml_sel")
    a = arrs[lab_kml]
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "traj.kml")
        export_arrival_kml(a, path, thr_latlon=THR_LATLON.get(a.runway))
        with open(path, "rb") as f_kml:
            kml_bytes = f_kml.read()
    st.download_button("⬇️ Descargar KML", kml_bytes, f"{a.callsign}_FR{a.numfr}.kml",
                       mime="application/vnd.google-earth.kml+xml", key="dl_kml")


# ──────────────────────────────────────────────────────────────────────────────
# Layout principal
# ──────────────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab5b, tab6, tab7 = st.tabs([
    "📊 Resumen",
    "📋 Tablas",
    "↔️ Separación",
    "⚠️ Incumplimientos",
    "💨 IAS",
    "🌬️ GS",
    "⏱️ Tiempo a THR",
    "🗺️ Trayectorias",
])

with tab1:
    tab_resumen()
with tab2:
    tab_tabla()
with tab3:
    tab_separacion()
with tab4:
    tab_incumplimientos()
with tab5:
    tab_ias()
with tab5b:
    tab_gs()
with tab6:
    tab_tiempo()
with tab7:
    tab_trayectorias()