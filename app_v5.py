"""Dashboard ARR LEBL — versión basada únicamente en CSV (carpeta ``inputs``).

Los CSV ya traen separaciones, IAS, GS y tiempos a THR calculados; este fichero solo
filtra, resume y representa. La lectura y normalización vive en ``data_loader.py``.
"""
import io
from dataclasses import dataclass

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from kml_loader import Track, parse_kml
from data_loader import INPUTS_DIR, Dataset, available_days, folder_fingerprint, load_folder

pd.set_option("styler.render.max_elements", 2_000_000)

st.set_page_config(page_title="Dashboard ARR LEBL", page_icon="🛬", layout="wide")

# ──────────────────────────────────────────────────────────────────────────────
# Constantes
# ──────────────────────────────────────────────────────────────────────────────
RUNWAY_COLORS = {
    "LEBL-24R": "#1f77b4",
    "LEBL-06L": "#ff7f0e",
    "LEBL-02": "#2ca02c",
    "LEBL-20": "#d62728",
}
RECAT_ORDER = ["J", "H+", "H-", "M+", "M-", "L+"]
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Umbrales de las pistas (posición de Google Earth), los mismos que usa main.py
THR_LATLON = {
    "LEBL-24R": (41 + 18/60 + 20.37/3600, 2 + 6/60 + 12.68/3600),
    "LEBL-06L": (41 + 17/60 + 41.70/3600, 2 + 4/60 + 19.97/3600),
    "LEBL-02": (41 + 17/60 + 16.66/3600, 2 + 5/60 + 5.76/3600),
    "LEBL-20": (41 + 18/60 + 32.85/3600, 2 + 5/60 + 40.51/3600),
}
MAX_TRAJ = 15
SENSOR_COLORS = {"ADSB-BCN": "#2ca02c", "Radar-BCN": "#d62728", "INTERPOLATED": "#e6b800"}

INC_COLS = ["Inc radar THR", "Inc radar 4NM", "Inc LoA THR", "Inc LoA 4NM", "Inc estela THR", "Inc estela 4NM"]
SEP_OP_COLS = ["Sep operacional THR", "Sep operacional 4NM"]
LONG_META = ["Date", "Vuelo", "Pista", "Tipo Aeronave", "STAR", "Wake Cat", "Cat", "Hora llegada", "Última"]
PERF_ID_COLUMNS = ["Fecha", "Vuelo", "Frustrada", "Pista", "Tipo Aeronave", "Hora llegada"]  # export Excel


# ──────────────────────────────────────────────────────────────────────────────
# Datos: carga (cacheada por huella de la carpeta) y utilidades
# ──────────────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner="Leyendo CSV de las fechas seleccionadas...")
def load_inputs(folder: str, date_from, date_to, fingerprint: tuple) -> Dataset:
    """``fingerprint`` solo forma parte de la clave de caché: si cambia un CSV del rango se recarga."""
    return load_folder(folder, date_from, date_to)


@st.cache_data(show_spinner=False)
def _to_xlsx(df: pd.DataFrame, sheet_name: str) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl", date_format="DD/MM/YYYY") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return buffer.getvalue()


def xlsx_button(label: str, df: pd.DataFrame, sheet_name: str, file_name: str, key: str):
    if df.empty:
        st.caption("Sin datos para exportar.")
        return
    st.download_button(label, _to_xlsx(df, sheet_name), file_name=file_name, mime=XLSX_MIME, key=key)


def to_long(df: pd.DataFrame, distances: list) -> pd.DataFrame:
    """Una fila por (aproximación, distancia) con columnas ias / gs / tiempo."""
    parts = [
        df[LONG_META].assign(dist=d, dist_label=f"{d} NM", ias=df[f"ias_{d}"], gs=df[f"gs_{d}"], tiempo=df[f"t_{d}"])
        for d in distances
    ]
    if not parts:
        return pd.DataFrame(columns=LONG_META + ["dist", "dist_label", "ias", "gs", "tiempo"])
    return pd.concat(parts, ignore_index=True)


@dataclass
class View:
    """Datos ya filtrados por la barra lateral; es lo único que reciben las pestañas."""
    data: Dataset
    pairs: pd.DataFrame      # parejas filtradas
    arr_all: pd.DataFrame    # aproximaciones filtradas, incluidas las frustradas
    arr: pd.DataFrame        # aproximaciones para IAS / GS / tiempos (excluye frustradas si se pide)
    arr_long: pd.DataFrame   # ``arr`` en formato largo (una fila por distancia)
    dists: list
    excl_fr: bool


def pairs_export(v: View, pairs: pd.DataFrame) -> pd.DataFrame:
    """Parejas en el formato original del CSV de separaciones (con la columna Fecha)."""
    return v.data.raw_pairs.loc[pairs.index].fillna("N/A")


def performance_export(v: View, kind: str) -> pd.DataFrame:
    """Aproximaciones en el formato original del CSV de rendimiento ('ias' o 'time')."""
    if kind == "ias":
        metrics = ["IAS THR", "GS THR"] + [f"{m} {d} NM" for d in v.dists for m in ("IAS", "GS")]
    else:
        metrics = [f"Tiempo {d} NM (s)" for d in v.dists]
    raw = v.data.raw_performance
    return raw.loc[v.arr.index, [c for c in PERF_ID_COLUMNS + metrics if c in raw.columns]]


def performance_buttons(v: View, suffix: str, ias: bool = True, time: bool = True):
    cols = st.columns([1, 1, 3])
    if ias:
        with cols[0]:
            xlsx_button("⬇️ Excel de IAS", performance_export(v, "ias"), "IAS", "ias.xlsx", f"dl_ias_{suffix}")
    if time:
        with cols[1]:
            xlsx_button("⬇️ Excel de tiempo a THR", performance_export(v, "time"), "Tiempo_a_THR",
                        "tiempo_a_thr.xlsx", f"dl_time_{suffix}")


# ──────────────────────────────────────────────────────────────────────────────
# Sidebar: carga y filtros
# ──────────────────────────────────────────────────────────────────────────────
AVAILABLE = available_days(INPUTS_DIR)   # solo nombres de fichero, no lee ningún CSV

with st.sidebar:
    st.title("🛬 Dashboard ARR LEBL")
    st.markdown("---")
    st.subheader("Datos")
    st.caption(f"📁 `{INPUTS_DIR}`")
    if st.button("🔄 Recargar CSV", width="stretch"):
        st.cache_data.clear()
        st.rerun()

if not AVAILABLE:
    st.info(
        f"No se han encontrado CSV en `{INPUTS_DIR}`.\n\n"
        "Copia ahí los ficheros `DD_MM_YYYY_Results_LEBL.csv` (separaciones) y "
        "`DD_MM_YYYY_Airspeed_Time_LEBL.csv` (IAS / GS / tiempo a THR) y pulsa **Recargar CSV**."
    )
    st.stop()

with st.sidebar:
    picked = st.date_input("Fechas a cargar", value=(AVAILABLE[-1], AVAILABLE[-1]),
                           min_value=AVAILABLE[0], max_value=AVAILABLE[-1],
                           help="Solo se leen los CSV de los días seleccionados.")
    date_from, date_to = (picked[0], picked[-1]) if isinstance(picked, (tuple, list)) and picked else (picked, picked)
    n_files = len([d for d in AVAILABLE if date_from <= d <= date_to])
    st.caption(f"{n_files} día(s) con CSV en el rango (de {len(AVAILABLE)} disponibles)")

DATA = load_inputs(str(INPUTS_DIR), date_from, date_to, folder_fingerprint(INPUTS_DIR, date_from, date_to))

with st.sidebar:
    if DATA.warnings:
        with st.expander(f"⚠️ {len(DATA.warnings)} aviso(s) de carga"):
            for warning in DATA.warnings:
                st.caption(warning)

if not DATA.days:
    st.warning("No hay CSV válidos en el rango de fechas seleccionado.")
    st.stop()

with st.sidebar:
    pairs_d = DATA.pairs[DATA.pairs["Date"].between(date_from, date_to)]
    arr_d = DATA.arrivals[DATA.arrivals["Date"].between(date_from, date_to)]
    if arr_d.empty and pairs_d.empty:
        st.warning("No hay datos en el rango seleccionado.")
        st.stop()

    sel_dists = st.multiselect("Distancias a THR (NM)", options=DATA.distances, default=DATA.distances)
    if not sel_dists:
        st.warning("Selecciona al menos una distancia.")
        st.stop()

    st.markdown("---")
    st.subheader("Filtros globales")
    runways = sorted(set(arr_d["Pista"].dropna()) | set(pairs_d["Pista"].dropna()))
    sel_runways = st.multiselect("Pista", options=runways, default=runways)
    wakes = sorted(set(arr_d["Wake Cat"]) | set(pairs_d["Wake Cat"]))
    sel_wake = st.multiselect("Wake Cat", options=wakes, default=wakes)
    cats = sorted(set(arr_d["Cat"]) | set(pairs_d["Cat"]))
    sel_cat = st.multiselect("Cat", options=cats, default=cats)

    excl_fr = st.checkbox("Excluir frustradas en IAS / GS / tiempos", value=True)
    excl_fr_pairs = st.checkbox("Excluir parejas con frustrada (líder o seguidor)", value=False)

    st.markdown("---")
    st.caption(f"📂 {len(DATA.days)} día(s) cargados · {len(arr_d)} aproximaciones · {len(pairs_d)} parejas")


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    """Pista / Wake Cat / Cat. En las parejas, Wake y Cat son los del seguidor."""
    return df[df["Pista"].isin(sel_runways) & df["Wake Cat"].isin(sel_wake) & df["Cat"].isin(sel_cat)].copy()


pairs_f = apply_filters(pairs_d)
if excl_fr_pairs:
    pairs_f = pairs_f[~(pairs_f["Frustrada líder"] | pairs_f["Frustrada seguidor"])]
arr_all = apply_filters(arr_d)
arr_perf = arr_all[arr_all["Última"]] if excl_fr else arr_all

if arr_all.empty and pairs_f.empty:
    st.warning("No hay datos para los filtros seleccionados.")
    st.stop()

VIEW = View(
    data=DATA, pairs=pairs_f, arr_all=arr_all, arr=arr_perf,
    arr_long=to_long(arr_perf, sel_dists), dists=sel_dists, excl_fr=excl_fr,
)


# ──────────────────────────────────────────────────────────────────────────────
# Pestaña: Resumen
# ──────────────────────────────────────────────────────────────────────────────
def _summary_kpis(v: View):
    arr, pairs = v.arr_all, v.pairs
    n_land = int(arr["Última"].sum())
    n_ga = len(arr) - n_land
    n_pairs = len(pairs)
    n_inc = int(pairs[INC_COLS].any(axis=1).sum())
    n_op_thr, n_op_4nm = (int(pairs[c].sum()) for c in SEP_OP_COLS)
    n_op = int(pairs[SEP_OP_COLS].any(axis=1).sum())

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("🛬 Llegadas", f"{n_land:,}")
    k2.metric("🔁 Frustradas", f"{n_ga:,}",
              delta=f"{arr.loc[~arr['Última'], 'Callsign'].nunique()} vuelo(s)" if n_ga else None, delta_color="off")
    k3.metric("⚠️ Parejas con incumplimiento", f"{n_inc:,}",
              delta=f"{n_inc / n_pairs * 100:.1f}%" if n_pairs else "0%", delta_color="inverse")
    k4.metric("🔴 Separación operacional", f"{n_op:,}", delta=f"THR: {n_op_thr} | 4NM: {n_op_4nm}", delta_color="off")


def _arrivals_timeline(landings: pd.DataFrame):
    peak_mode = st.radio("Modo de análisis", ["Intervalos fijos", "Ventana pico"], horizontal=True) == "Ventana pico"
    interval = st.selectbox("Resolución temporal", [60, 30, 15], format_func=lambda x: f"{x} min")
    days = sorted(landings["Date"].unique())
    day = st.selectbox("Día", days, format_func=lambda d: d.strftime("%d/%m/%Y")) if len(days) > 1 else days[0]

    day_landings = landings[landings["Date"] == day]
    block = day_landings["Hora llegada"].dt.floor(f"{interval}min").rename("bloque")
    counts = day_landings.groupby(block).size().rename("Llegadas").reset_index()
    if counts.empty:
        st.info("No hay datos para el día seleccionado.")
        return

    fig = px.bar(counts, x="bloque", y="Llegadas", text="Llegadas",
                 title=f"Llegadas cada {interval} minutos ({day.strftime('%d/%m/%Y')})")
    fig.update_layout(xaxis_title="Hora UTC" if peak_mode else "Hora", yaxis_title="Llegadas")
    if peak_mode:
        peak = counts.loc[counts["Llegadas"].idxmax()]
        start = peak["bloque"]
        end = start + pd.Timedelta(minutes=interval)
        st.metric("Intervalo pico", f"{int(peak['Llegadas'])} llegadas",
                  delta=f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')}")
        fig.update_traces(marker_color=["#FF6B35" if t == start else "#4C72B0" for t in counts["bloque"]],
                          textposition="outside")
    st.plotly_chart(fig, width="stretch", key="res_hourly_peak" if peak_mode else "res_hourly")


def _runway_and_speed_summary(v: View, landings: pd.DataFrame):
    c1, c2 = st.columns(2)
    with c1:
        per_runway = landings.groupby("Pista").size().reset_index(name="Llegadas")
        st.plotly_chart(
            px.bar(per_runway, x="Pista", y="Llegadas", color="Pista", color_discrete_map=RUNWAY_COLORS,
                   title="Llegadas por pista", text="Llegadas"),
            width="stretch", key="res_runway")
    with c2:
        if not v.arr_long.empty:
            summary = v.arr_long.groupby("dist").agg(
                ias_media=("ias", "mean"), ias_mediana=("ias", "median"),
                t_media=("tiempo", "mean"), t_mediana=("tiempo", "median"),
            ).reset_index()
            summary.columns = ["Distancia (NM)", "IAS media (kt)", "IAS mediana (kt)",
                               "Tiempo medio (s)", "Tiempo mediana (s)"]
            st.subheader("IAS y tiempo a THR por distancia")
            st.dataframe(summary.round(1), width="stretch", hide_index=True)


def _daily_summary(v: View):
    st.subheader("Resumen por fecha")
    rows = []
    for date in sorted(v.arr_all["Date"].unique()):
        a_d = v.arr_all[v.arr_all["Date"] == date]
        p_d = v.pairs[v.pairs["Date"] == date]
        n = len(p_d)
        n_inc = int(p_d[INC_COLS].any(axis=1).sum())
        n_op = int(p_d[SEP_OP_COLS].any(axis=1).sum())
        rows.append({
            "Fecha": str(date),
            "Llegadas": int(a_d["Última"].sum()),
            "Frustradas": int((~a_d["Última"]).sum()),
            "Parejas": n,
            "Con incumplimiento": n_inc,
            "% incumplimiento": f"{n_inc / n * 100:.1f}%" if n else "0%",
            "Sep. operacional": n_op,
            "Sep. op. THR": int(p_d["Sep operacional THR"].sum()),
            "Sep. op. 4NM": int(p_d["Sep operacional 4NM"].sum()),
            "% sep. operacional": f"{n_op / n * 100:.1f}%" if n else "0%",
        })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def tab_resumen(v: View):
    st.header("Resumen diario")
    _summary_kpis(v)
    st.markdown("---")
    landings = v.arr_all[v.arr_all["Última"]]
    if landings.empty:
        st.info("No hay aterrizajes en la selección actual.")
    else:
        _arrivals_timeline(landings)
        _runway_and_speed_summary(v, landings)
    _daily_summary(v)


# ──────────────────────────────────────────────────────────────────────────────
# Pestaña: Tablas
# ──────────────────────────────────────────────────────────────────────────────
def tab_tablas(v: View):
    st.header("Tablas")

    st.subheader("Parejas líder – seguidor")
    stars = sorted(v.pairs["STAR"].dropna().unique().tolist())
    sel_stars = st.multiselect("Filtrar por STAR (seguidor)", options=stars, default=stars)
    df_tab = v.pairs[v.pairs["STAR"].isin(sel_stars)].copy() if sel_stars else v.pairs.copy()

    st.caption("ℹ️ **Seguidor** = tráfico que puede cometer el incumplimiento. "
               "**Prev** = tráfico precedente (líder). Sep. en NM, alturas en ft.")
    st.caption(f"Mostrando {len(df_tab):,} parejas")

    if df_tab.empty:
        st.info("No hay parejas para los filtros seleccionados.")
    else:
        df_tab["⚠️ Inc"] = df_tab[INC_COLS].any(axis=1)
        display_cols = (
            ["Date", "Hora THR", "Pareja", "Pista", "Líder", "Seguidor", "STAR", "Prev STAR",
             "Tipo Aeronave", "Prev Tipo Aeronave", "Wake Cat", "Cat", "Prev Wake Cat", "Prev Cat", "⚠️ Inc",
             "Frustrada líder", "Frustrada seguidor", "Tipo frustrada seguidor"]
            + INC_COLS
            + SEP_OP_COLS + ["Hora 4NM", "Sep 4NM", "Alt 4NM", "Sep THR", "Alt THR"]
        )

        def _style(row):
            if row["Sep operacional THR"] or row["Sep operacional 4NM"]:
                return ["background-color: #ffcccc"] * len(row)
            if bool(row.get("⚠️ Inc")):
                return ["background-color: #ffe8e8"] * len(row)
            return [""] * len(row)

        fmt = {c: "{:.2f}" for c in ("Sep 4NM", "Sep THR")} | {c: "{:.0f}" for c in ("Alt 4NM", "Alt THR")}
        st.dataframe(df_tab[display_cols].style.apply(_style, axis=1).format(fmt, na_rep=""),
                     width="stretch", hide_index=True)
        xlsx_button("⬇️ Excel de separaciones", pairs_export(v, df_tab), "Separaciones",
                    "separaciones.xlsx", "dl_pairs")

    st.markdown("---")

    st.subheader("Aproximaciones: IAS y tiempo a THR")
    st.caption(f"Mostrando {len(v.arr):,} aproximaciones" + (" (sin frustradas)" if v.excl_fr else " (con frustradas)"))
    if v.arr.empty:
        st.info("No hay aproximaciones para los filtros seleccionados.")
        return

    d = v.dists
    cols = (["Date", "Vuelo", "Frustrada", "Pista", "Tipo Aeronave", "STAR", "Wake Cat", "Cat", "Hora llegada",
             "Última", "ias_THR", "gs_THR"]
            + [f"ias_{x}" for x in d] + [f"gs_{x}" for x in d] + [f"t_{x}" for x in d])
    arr_tab = v.arr[cols].copy()
    arr_tab["Hora llegada"] = arr_tab["Hora llegada"].dt.strftime("%H:%M:%S")
    arr_tab = arr_tab.rename(columns={"ias_THR": "IAS THR", "gs_THR": "GS THR"}
                             | {f"ias_{x}": f"IAS {x} NM" for x in d}
                             | {f"gs_{x}": f"GS {x} NM" for x in d}
                             | {f"t_{x}": f"Tiempo {x} NM (s)" for x in d})
    fmt_a = {c: "{:.0f}" for c in arr_tab.columns if c.startswith(("IAS", "GS", "Tiempo"))}
    st.dataframe(arr_tab.style.format(fmt_a, na_rep=""), width="stretch", hide_index=True)
    performance_buttons(v, "tab")


# ──────────────────────────────────────────────────────────────────────────────
# Pestaña: Separación
# ──────────────────────────────────────────────────────────────────────────────
def tab_separacion(v: View):
    st.header("Gráficas de separación")
    pairs = v.pairs
    if pairs.empty:
        st.info("No hay parejas de tráfico en los datos seleccionados.")
        return

    st.subheader("Distribución de separaciones")
    c1, c2 = st.columns(2)
    for col, (field, title) in zip((c1, c2), (("Sep 4NM", "Separación en 4 NM"), ("Sep THR", "Separación en THR"))):
        with col:
            fig = px.histogram(pairs[pairs[field].notna()], x=field, color="Pista", color_discrete_map=RUNWAY_COLORS,
                               nbins=40, barmode="overlay", opacity=0.75,
                               labels={field: f"{field} (NM)", "count": "Nº parejas"}, title=title)
            fig.update_layout(legend_title_text="Pista")
            st.plotly_chart(fig, width="stretch", key=f"sep_hist_{field}")

    st.subheader("Evolución temporal de separaciones")
    hover = ["Pareja", "STAR", "Par RECAT", "Prev Tipo Aeronave", "Tipo Aeronave"]
    for field, time_col, title in (("Sep 4NM", "T4_dt", "Evolución temporal Sep 4NM"),
                                   ("Sep THR", "THR_dt", "Evolución temporal Sep THR")):
        d = pairs[pairs[field].notna()].sort_values(time_col)
        fig = px.scatter(d, x=time_col, y=field, color="Pista", color_discrete_map=RUNWAY_COLORS,
                         labels={time_col: "Hora del líder", field: f"{field} (NM)"}, title=title, hover_data=hover)
        fig.update_traces(marker=dict(size=6, opacity=0.7))
        fig.update_layout(legend_title_text="Pista", height=360)
        st.plotly_chart(fig, width="stretch", key=f"sep_time_{field}")

    st.subheader("Relación entre puntos y combinación RECAT")
    c1, c2 = st.columns(2)
    with c1:
        fig = px.scatter(pairs.dropna(subset=["Sep 4NM", "Sep THR"]), x="Sep 4NM", y="Sep THR", color="Pista",
                         color_discrete_map=RUNWAY_COLORS, hover_name="Pareja", hover_data=["Par RECAT", "Hora THR"],
                         title="Separación 4 NM vs THR")
        fig.update_layout(legend_title_text="Pista")
        st.plotly_chart(fig, width="stretch", key="sep_scatter")
    with c2:
        point = st.radio("Punto de medida", ["THR", "4NM"], horizontal=True, key="sep_punto")
        field = "Sep THR" if point == "THR" else "Sep 4NM"
        pivot = pairs.pivot_table(index="Prev Cat", columns="Cat", values=field, aggfunc="mean")
        if pivot.empty:
            st.info("Sin datos para el mapa de calor.")
        else:
            pivot = pivot.reindex(index=[c for c in RECAT_ORDER if c in pivot.index],
                                  columns=[c for c in RECAT_ORDER if c in pivot.columns])
            fig = px.imshow(pivot, text_auto=".1f", aspect="auto", color_continuous_scale="RdYlGn",
                            title=f"Separación media en {point} (RECAT líder × seguidor)",
                            labels=dict(x="Seguidor", y="Líder", color="NM"))
            st.plotly_chart(fig, width="stretch", key="sep_heat")


# ──────────────────────────────────────────────────────────────────────────────
# Pestaña: Incumplimientos
# ──────────────────────────────────────────────────────────────────────────────
def _violations_by(df_any: pd.DataFrame, field: str, barmode: str, key: str, title: str, **layout):
    grouped = df_any.groupby(field)[INC_COLS].sum().reset_index()
    melted = grouped.melt(id_vars=field, var_name="Tipo", value_name="Casos")
    melted = melted[melted["Casos"] > 0]
    fig = px.bar(melted, x=field, y="Casos", color="Tipo", barmode=barmode, title=title)
    fig.update_layout(**layout)
    st.plotly_chart(fig, width="stretch", key=key)


def tab_incumplimientos(v: View):
    st.header("Análisis de incumplimientos")
    pairs = v.pairs
    total = len(pairs)
    if total == 0:
        st.info("No hay parejas en los datos seleccionados.")
        return

    counts = {c: int(pairs[c].sum()) for c in INC_COLS + SEP_OP_COLS}
    df_counts = (pd.DataFrame(list(counts.items()), columns=["Tipo incumplimiento", "Nº casos"])
                 .sort_values("Nº casos", ascending=True))
    df_counts["% sobre total"] = (df_counts["Nº casos"] / total * 100).round(1)

    c1, c2 = st.columns([2, 1])
    with c1:
        fig = px.bar(df_counts, x="Nº casos", y="Tipo incumplimiento", orientation="h", text="Nº casos",
                     color="Nº casos", color_continuous_scale="Reds",
                     title="Total incumplimientos por tipo (seguidor)")
        fig.update_traces(textposition="outside")
        fig.update_layout(showlegend=False, coloraxis_showscale=False, height=360)
        st.plotly_chart(fig, width="stretch", key="inc_total")
    with c2:
        st.dataframe(df_counts, width="stretch", hide_index=True)

    st.markdown("---")

    df_any = pairs[pairs[INC_COLS].any(axis=1)]
    if df_any.empty:
        st.success("No hay incumplimientos en los datos seleccionados.")
    else:
        st.subheader("Desglose por STAR (seguidor)")
        _violations_by(df_any, "STAR", "stack", "inc_by_STAR", "Incumplimientos por STAR",
                       xaxis_tickangle=-45, height=400)
        st.subheader("Desglose por pista")
        _violations_by(df_any, "Pista", "group", "inc_by_Pista", "Incumplimientos por Pista",
                       xaxis_tickangle=-45, height=400)
        c1, c2 = st.columns(2)
        for col, field in zip((c1, c2), ("Wake Cat", "Cat")):
            with col:
                st.subheader(f"Desglose por {field} (seguidor)")
                _violations_by(df_any, field, "group", f"inc_by_{field}", f"Incumplimientos por {field}")

    st.markdown("---")

    st.subheader("Separación operacional")
    n_op_thr, n_op_4nm = (int(pairs[c].sum()) for c in SEP_OP_COLS)
    st.metric("Parejas con separación operacional", int(pairs[SEP_OP_COLS].any(axis=1).sum()),
              delta=f"THR: {n_op_thr} | 4NM: {n_op_4nm}", delta_color="off")

    df_op = pairs[pairs[SEP_OP_COLS].any(axis=1)]
    if df_op.empty:
        st.success("No se han detectado separaciones operacionales.")
    else:
        show = (["Date", "Hora THR", "Pareja", "Pista", "STAR", "Par RECAT", "Prev Tipo Aeronave", "Tipo Aeronave"]
                + SEP_OP_COLS + ["Sep 4NM", "Alt 4NM", "Sep THR", "Alt THR"] + INC_COLS)
        st.dataframe(df_op[show].reset_index(drop=True), width="stretch", hide_index=True)


# ──────────────────────────────────────────────────────────────────────────────
# Pestañas: IAS / GS / Tiempo a THR
# ──────────────────────────────────────────────────────────────────────────────
def tab_metric(v: View, col: str, name: str, unit: str, key: str):
    """Análisis genérico de una métrica por distancia (IAS, GS o tiempo a THR)."""
    long = v.arr_long
    if long.empty or long[col].notna().sum() == 0:
        st.info("No hay datos en la selección actual.")
        return

    dist = st.selectbox("Distancia a THR (NM)", v.dists, index=min(1, len(v.dists) - 1), key=f"{key}_d")
    sub = long[long["dist"] == dist].dropna(subset=[col])
    if sub.empty:
        st.info(f"No hay datos a {dist} NM.")
        return

    k1, k2, k3, k4 = st.columns(4)
    k1.metric(f"Mínimo ({unit})", f"{sub[col].min():.0f}")
    k2.metric(f"Media ({unit})", f"{sub[col].mean():.0f}")
    k3.metric(f"Mediana ({unit})", f"{sub[col].median():.0f}")
    k4.metric(f"Máximo ({unit})", f"{sub[col].max():.0f}")
    st.markdown("---")

    c1, c2 = st.columns(2)
    with c1:
        fig = px.box(long.dropna(subset=[col]), x="dist_label", y=col, color="Pista",
                     color_discrete_map=RUNWAY_COLORS, category_orders={"dist_label": [f"{d} NM" for d in v.dists]},
                     points="outliers", labels={"dist_label": "Distancia", col: f"{name} ({unit})"},
                     title=f"{name} por distancia a THR")
        fig.update_layout(legend_title_text="Pista", height=380)
        st.plotly_chart(fig, width="stretch", key=f"{key}_box")
    with c2:
        profile = long.groupby(["Pista", "dist"])[col].mean().reset_index()
        fig = px.line(profile, x="dist", y=col, color="Pista", color_discrete_map=RUNWAY_COLORS, markers=True,
                      labels={"dist": "Distancia a THR (NM)", col: f"{name} media ({unit})"},
                      title=f"{name} medio vs distancia a THR")
        fig.update_layout(legend_title_text="Pista", height=380)
        fig.update_xaxes(autorange="reversed")   # de la distancia máxima (izquierda) a THR (derecha)
        st.plotly_chart(fig, width="stretch", key=f"{key}_perfil")

    st.subheader(f"Detalle a {dist} NM")
    c1, c2 = st.columns(2)
    with c1:
        fig = px.histogram(sub, x=col, color="Pista", color_discrete_map=RUNWAY_COLORS, nbins=40, barmode="overlay",
                           opacity=0.75, labels={col: f"{name} ({unit})", "count": "Nº aproximaciones"},
                           title=f"Distribución de {name} a {dist} NM")
        fig.update_layout(legend_title_text="Pista", height=380)
        st.plotly_chart(fig, width="stretch", key=f"{key}_hist")
    with c2:
        over_time = sub[sub["Hora llegada"].notna()].sort_values("Hora llegada")
        fig = px.scatter(over_time, x="Hora llegada", y=col, color="Pista", color_discrete_map=RUNWAY_COLORS,
                         hover_data=["Vuelo", "Tipo Aeronave", "STAR", "Wake Cat"],
                         labels={"Hora llegada": "Hora de llegada", col: f"{name} ({unit})"},
                         title=f"Evolución temporal de {name} a {dist} NM")
        fig.update_traces(marker=dict(size=6, opacity=0.7))
        fig.update_layout(legend_title_text="Pista", height=380)
        st.plotly_chart(fig, width="stretch", key=f"{key}_time")

    by_star = sub[sub["STAR"].notna()]
    star_order = by_star.groupby("STAR")[col].median().sort_values().index.tolist()
    fig = px.box(by_star, x="STAR", y=col, color="Pista", color_discrete_map=RUNWAY_COLORS,
                 category_orders={"STAR": star_order}, points="outliers", labels={col: f"{name} ({unit})"},
                 title=f"{name} a {dist} NM por STAR")
    fig.update_layout(legend_title_text="Pista", height=400, xaxis_tickangle=-45)
    st.plotly_chart(fig, width="stretch", key=f"{key}_star")

    if sub["Date"].nunique() > 1:
        sub = sub.assign(Date_str=sub["Date"].astype(str))
        fig = px.box(sub, x="Date_str", y=col, color="Pista", color_discrete_map=RUNWAY_COLORS,
                     category_orders={"Date_str": sorted(sub["Date_str"].unique())}, points="outliers",
                     labels={col: f"{name} ({unit})", "Date_str": "Fecha"},
                     title=f"Distribución de {name} a {dist} NM por día")
        fig.update_layout(legend_title_text="Pista", height=400, xaxis_tickangle=-30)
        st.plotly_chart(fig, width="stretch", key=f"{key}_date")


def tab_ias(v: View):
    st.header("Velocidad indicada (IAS) a distintas distancias de THR")
    tab_metric(v, "ias", "IAS", "kt", "ias")
    performance_buttons(v, "ias", time=False)


def tab_gs(v: View):
    st.header("Velocidad respecto al suelo (GS) a distintas distancias de THR")
    tab_metric(v, "gs", "GS", "kt", "gs")
    if not v.arr.empty:
        st.caption("El Excel de IAS incluye también la GS (IAS THR/GS THR y a cada distancia).")


def tab_tiempo(v: View):
    st.header("Tiempo hasta THR desde distintas distancias")
    tab_metric(v, "tiempo", "Tiempo a THR", "s", "time")

    long = v.arr_long
    if not long.empty and long["tiempo"].notna().any():
        dist = st.session_state.get("time_d", v.dists[min(1, len(v.dists) - 1)])
        sub = long[long["dist"] == dist].dropna(subset=["tiempo", "ias"])
        if not sub.empty:
            fig = px.scatter(sub, x="ias", y="tiempo", color="Pista", color_discrete_map=RUNWAY_COLORS,
                             hover_name="Vuelo", hover_data=["Tipo Aeronave", "STAR", "Wake Cat"],
                             labels={"ias": "IAS (kt)", "tiempo": "Tiempo a THR (s)"},
                             title=f"IAS vs tiempo a THR a {dist} NM")
            fig.update_layout(legend_title_text="Pista", height=380)
            st.plotly_chart(fig, width="stretch", key="time_ias_scatter")
    performance_buttons(v, "time", ias=False)


# ──────────────────────────────────────────────────────────────────────────────
# Pestaña: Trayectorias (KML generados con kml_export.py)
# ──────────────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _parse_kml_cached(data: bytes, name: str) -> Track:
    return parse_kml(data, name)


def _hhmmss(iso: str) -> str:
    return iso[11:19] if len(iso) >= 19 else ""


def _qc_row(track: Track) -> dict:
    recs = track.records
    jumps = [j["nm"] for j in track.jumps if j["nm"] is not None]
    return {
        "Vuelo": track.name, "Pista": track.runway, "Records": len(recs),
        "Sensores": ", ".join(sorted({r["sensor"] for r in recs})),
        "cum_dist máx (NM)": round(max(r["cum_dist"] for r in recs if r["cum_dist"] is not None), 1),
        "Saltos > umbral": len(jumps), "Mayor salto (NM)": round(max(jumps), 2) if jumps else 0.0,
    }


def tab_trayectorias(v: View):
    st.header("Trayectorias")
    files = st.file_uploader("Archivos KML de las trayectorias (generados con main.py)", type=["kml"],
                             accept_multiple_files=True, key="kml_files")
    if not files:
        st.info("Selecciona uno o varios archivos `.kml` para visualizar las trayectorias.")
        return

    tracks: dict[str, Track] = {}
    for f in files:
        try:
            track = _parse_kml_cached(f.getvalue(), f.name.rsplit(".", 1)[0])
        except Exception as exc:  # noqa: BLE001
            st.warning(f"{f.name}: no se pudo leer el KML ({exc}).")
            continue
        if not track.records:
            st.warning(f"{f.name}: no contiene records de trayectoria (¿está generado con kml_export.py?).")
            continue
        tracks[track.name] = track
    if not tracks:
        return

    names = list(tracks)
    c1, c2 = st.columns([4, 1])
    with c1:
        shown = st.multiselect(f"Aproximaciones a visualizar (máx. {MAX_TRAJ})", names, default=names[:3],
                               max_selections=MAX_TRAJ)
    with c2:
        by_sensor = st.checkbox("Colorear por sensor", value=False)
    if not shown:
        st.info("Selecciona al menos una aproximación.")
        return

    # ── Mapa ──────────────────────────────────────────────────────────────────
    palette = px.colors.qualitative.Plotly
    fig = go.Figure()
    thr_pts, nm4_pts = {"lat": [], "lon": []}, {"lat": [], "lon": []}
    sensor_pts = {}
    all_lat, all_lon = [], []
    for n, name in enumerate(shown):
        track, color = tracks[name], palette[n % len(palette)]
        recs = track.records
        lats, lons = [r["lat"] for r in recs], [r["lon"] for r in recs]
        texts = [f"{name}<br>{_hhmmss(r['time'])} · {r['sensor']}<br>Alt {r['alt']:.0f} ft · IAS {r['ias']:.0f} kt"
                 for r in recs]
        all_lat += lats
        all_lon += lons
        if by_sensor:
            fig.add_trace(go.Scattermap(lat=lats, lon=lons, mode="lines", line=dict(width=2, color=color),
                                        name=name, hoverinfo="skip"))
            for r, tx in zip(recs, texts):
                b = sensor_pts.setdefault(r["sensor"], {"lat": [], "lon": [], "text": []})
                b["lat"].append(r["lat"]); b["lon"].append(r["lon"]); b["text"].append(tx)
        else:
            fig.add_trace(go.Scattermap(lat=lats, lon=lons, mode="lines+markers", line=dict(width=3, color=color),
                                        marker=dict(size=4, color=color), name=name, text=texts, hoverinfo="text"))
        if track.idx_thr is not None:
            thr_pts["lat"].append(recs[track.idx_thr]["lat"]); thr_pts["lon"].append(recs[track.idx_thr]["lon"])
        near4 = [r for r in recs if r["cum_dist"] is not None]
        if near4:
            r4 = min(near4, key=lambda r: abs(r["cum_dist"] - 4))
            nm4_pts["lat"].append(r4["lat"]); nm4_pts["lon"].append(r4["lon"])
        for j in track.jumps:   # tramos con salto sospechoso
            fig.add_trace(go.Scattermap(lat=[p[0] for p in j["pts"]], lon=[p[1] for p in j["pts"]], mode="lines",
                                        line=dict(width=5, color="#ff8c00"), name=j["text"], hoverinfo="name",
                                        showlegend=False))
    for sensor, b in sensor_pts.items():
        fig.add_trace(go.Scattermap(lat=b["lat"], lon=b["lon"], mode="markers", text=b["text"], hoverinfo="text",
                                    marker=dict(size=6, color=SENSOR_COLORS.get(sensor, "#7f7f7f")), name=sensor))
    for label, pts, col in (("Record 4 NM", nm4_pts, "#6a1b9a"), ("Record THR", thr_pts, "black")):
        if pts["lat"]:
            fig.add_trace(go.Scattermap(lat=pts["lat"], lon=pts["lon"], mode="markers+text",
                                        text=[label.split()[-2] + " " + label.split()[-1] if "NM" in label else "THR"]
                                        * len(pts["lat"]), textposition="top right",
                                        marker=dict(size=11, color=col), name=label))
    rwys = sorted({tracks[n].runway for n in shown if tracks[n].runway in THR_LATLON})
    if rwys:
        fig.add_trace(go.Scattermap(lat=[THR_LATLON[r][0] for r in rwys], lon=[THR_LATLON[r][1] for r in rwys],
                                    mode="markers+text", text=rwys, textposition="bottom right",
                                    marker=dict(size=14, color="#e53935"), name="Umbral (Google Earth)"))
    fig.update_layout(
        map_style="open-street-map",
        map_center=dict(lat=sum(all_lat) / len(all_lat), lon=sum(all_lon) / len(all_lon)), map_zoom=9.5,
        height=680, margin=dict(l=0, r=0, t=10, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
    )
    st.plotly_chart(fig, width="stretch", key="traj_map")
    st.caption("Los tramos en naranja son saltos sospechosos entre records consecutivos (según el umbral de kml_export).")

    # ── Control de calidad ────────────────────────────────────────────────────
    st.subheader("Control de calidad de las trayectorias")
    st.dataframe(pd.DataFrame([_qc_row(tracks[n]) for n in shown]), width="stretch", hide_index=True)

    # ── Perfiles de altitud e IAS ─────────────────────────────────────────────
    # El slider se ajusta a los datos: no tiene sentido pedir más NM de las que tienen los records
    avail = max((r["cum_dist"] for n in shown for r in tracks[n].records[: tracks[n].idx_thr + 1]
                 if r["cum_dist"] is not None), default=0.0)
    slider_max = max(6, min(60, int(avail) + 1))
    max_dist = st.slider("Distancia máxima a THR en los perfiles (NM)", 1, slider_max, slider_max,
                         key=f"traj_maxd_{slider_max}")
    st.caption(f"Los vuelos seleccionados tienen records hasta {avail:.1f} NM antes de THR.")
    rows, diag = [], []
    for name in shown:
        track = tracks[name]
        until_thr = track.records[: track.idx_thr + 1]
        inside = [r for r in until_thr if r["cum_dist"] is not None and r["cum_dist"] <= max_dist]
        rows += [{"Vuelo": name, "cum_dist": r["cum_dist"], "alt": r["alt"], "ias": r["ias"], "gs": r["gs"]}
                 for r in inside]
        diag.append({
            "Vuelo": name, "Records totales": len(track.records), "Índice record THR": track.idx_thr,
            "Distancia máx. hasta THR (NM)": round(max((r["cum_dist"] for r in until_thr), default=0), 1),
            "Puntos en el perfil": len(inside),
        })
    perfil = pd.DataFrame(rows, columns=["Vuelo", "cum_dist", "alt", "ias", "gs"])

    short = [d["Vuelo"] for d in diag if d["Puntos en el perfil"] < 2]
    if short:
        st.warning(
            "Con esta distancia máxima hay menos de 2 puntos para: " + ", ".join(short) + ". Una línea necesita al "
            "menos 2 puntos para dibujarse; sube la distancia máxima o revisa la tabla de diagnóstico."
        )
    with st.expander("Diagnóstico de los perfiles"):
        st.dataframe(pd.DataFrame(diag), width="stretch", hide_index=True)
        st.caption("La distancia acumulada se mide a lo largo de la trayectoria hacia atrás desde el record más "
                   "cercano a THR; los saltos entre records (tramos naranjas del mapa) la inflan.")
    if perfil.empty:
        st.info("No hay records dentro de la distancia seleccionada.")
        return

    labels = {"cum_dist": "Distancia acumulada a THR (NM)", "alt": "Altitud (ft)", "ias": "IAS (kt)", "gs": "GS (kt)"}
    c1, c2 = st.columns(2)
    for col, (field, title) in zip((c1, c2), (("alt", f"Perfil vertical (últimas {max_dist} NM)"),
                                              ("ias", f"Perfil de IAS (últimas {max_dist} NM)"))):
        with col:
            f = go.Figure()
            for n, name in enumerate(shown):
                one = perfil[(perfil["Vuelo"] == name)].dropna(subset=["cum_dist", field]).sort_values("cum_dist")
                if one.empty:
                    continue
                f.add_trace(go.Scatter(x=one["cum_dist"], y=one[field], mode="lines+markers", name=name,
                                       line=dict(color=palette[n % len(palette)]), marker=dict(size=4)))
            f.update_layout(title=title, xaxis_title=labels["cum_dist"], yaxis_title=labels[field],
                            legend_title_text="Vuelo")
            f.update_xaxes(autorange="reversed")
            st.plotly_chart(f, width="stretch", key=f"traj_{field}")


# ──────────────────────────────────────────────────────────────────────────────
# Layout principal
# ──────────────────────────────────────────────────────────────────────────────
TABS = [
    ("📊 Resumen", tab_resumen),
    ("📋 Tablas", tab_tablas),
    ("↔️ Separación", tab_separacion),
    ("⚠️ Incumplimientos", tab_incumplimientos),
    ("💨 IAS", tab_ias),
    ("🌬️ GS", tab_gs),
    ("⏱️ Tiempo a THR", tab_tiempo),
    ("🗺️ Trayectorias", tab_trayectorias),
]
for container, (_, render) in zip(st.tabs([name for name, _ in TABS]), TABS):
    with container:
        render(VIEW)