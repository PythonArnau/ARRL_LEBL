"""Lectura y normalización de los CSV diarios de LEBL (carpeta ``inputs``).

Por cada día se esperan dos ficheros generados por ``main.py``:

* ``DD_MM_YYYY_Results_LEBL.csv``        -> separaciones por pareja líder/seguidor
* ``DD_MM_YYYY_Airspeed_Time_LEBL.csv``  -> IAS / GS / tiempo a THR por aproximación

Este módulo los une en un único :class:`Dataset` con las columnas que espera ``app.py``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

INPUTS_DIR = Path(__file__).resolve().parent / "inputs"

FILE_RE = re.compile(r"^(\d{2})_(\d{2})_(\d{4})_(Results|Airspeed_Time)_([A-Za-z0-9]{4})\.csv$", re.IGNORECASE)
KIND_PAIRS, KIND_PERF = "results", "airspeed_time"

# Tolerancia para casar una aproximación (Hora llegada) con la hora de THR de una pareja
MATCH_TOLERANCE = pd.Timedelta(minutes=10)

# CSV de separaciones -> nombre interno
PAIR_RENAME = {
    "Estela Líder": "Prev Wake Cat",
    "RECAT Líder": "Prev Cat",
    "STAR Líder": "Prev STAR",
    "Tipo Aeronave Líder": "Prev Tipo Aeronave",
    "Estela Seguidor": "Wake Cat",
    "RECAT Seguidor": "Cat",
    "STAR Seguidor": "STAR",
    "Tipo Aeronave Seguidor": "Tipo Aeronave",
    "Sep. 4NM (NM)": "Sep 4NM",
    "Sep. Vertical 4NM (ft)": "Alt 4NM",
    "Sep. THR (NM)": "Sep THR",
    "Sep. Vertical THR (ft)": "Alt THR",
    "Incumplimiento Radar THR": "Inc radar THR",
    "Incumplimiento Radar 4NM": "Inc radar 4NM",
    "Incumplimiento LoA THR": "Inc LoA THR",
    "Incumplimiento LoA 4NM": "Inc LoA 4NM",
    "Incumplimiento Estela THR": "Inc estela THR",
    "Incumplimiento Estela 4NM": "Inc estela 4NM",
    "Separación Operacional THR": "Sep operacional THR",
    "Separación Operacional 4NM": "Sep operacional 4NM",
}
BOOL_COLS = [
    "Inc radar THR", "Inc radar 4NM", "Inc LoA THR", "Inc LoA 4NM", "Inc estela THR", "Inc estela 4NM",
    "Sep operacional THR", "Sep operacional 4NM",
]
NUM_PAIR_COLS = ["Sep 4NM", "Alt 4NM", "Sep THR", "Alt THR"]

PAIR_COLUMNS = [
    "Date", "Pareja", "Pista", "Líder", "Seguidor", "STAR", "Prev STAR", "Tipo Aeronave", "Prev Tipo Aeronave",
    "Wake Cat", "Cat", "Prev Wake Cat", "Prev Cat", "Par RECAT",
    "Frustrada líder", "Frustrada seguidor", "Tipo frustrada seguidor",
    "Hora 4NM", "Sep 4NM", "Alt 4NM", "Hora THR", "Sep THR", "Alt THR",
    "T4_dt", "THR_dt",
] + BOOL_COLS

ARR_META = [
    "Date", "Vuelo", "Callsign", "Frustrada", "Tipo frustrada", "Última", "Pista", "Tipo Aeronave",
    "STAR", "Wake Cat", "Cat", "Hora llegada",
]

ND = "N/D"


@dataclass
class Dataset:
    days: list = field(default_factory=list)            # list[date], ordenada
    distances: list = field(default_factory=list)       # distancias a THR (int/float), ordenadas
    pairs: pd.DataFrame = field(default_factory=pd.DataFrame)
    arrivals: pd.DataFrame = field(default_factory=pd.DataFrame)
    raw_pairs: pd.DataFrame = field(default_factory=pd.DataFrame)         # mismo índice que ``pairs``
    raw_performance: pd.DataFrame = field(default_factory=pd.DataFrame)   # mismo índice que ``arrivals``
    warnings: list = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# Descubrimiento de ficheros
# ──────────────────────────────────────────────────────────────────────────────
def _scan(folder: Path) -> dict:
    """{(date, kind): path} con los CSV que cumplen el patrón de nombre."""
    found, bad = {}, []
    if not folder.is_dir():
        return found
    for path in sorted(folder.iterdir()):
        m = FILE_RE.match(path.name)
        if not m:
            continue
        d, mth, y, kind, _airport = m.groups()
        try:
            day = date(int(y), int(mth), int(d))
        except ValueError:
            bad.append(path.name)
            continue
        found[(day, KIND_PAIRS if kind.lower() == "results" else KIND_PERF)] = path
    return found


def available_days(folder) -> list:
    """Días con algún CSV en la carpeta. Solo mira los nombres: no abre ningún fichero."""
    return sorted({day for day, _ in _scan(Path(folder))})


def _in_range(day: date, date_from, date_to) -> bool:
    return (date_from is None or day >= date_from) and (date_to is None or day <= date_to)


def folder_fingerprint(folder, date_from=None, date_to=None) -> tuple:
    """Huella (nombre, tamaño, mtime) de los CSV del rango; cambia si se añade/modifica uno de ellos."""
    items = []
    for (day, _kind), path in sorted(_scan(Path(folder)).items()):
        if _in_range(day, date_from, date_to):
            st = path.stat()
            items.append((path.name, st.st_size, st.st_mtime_ns))
    return tuple(items)


# ──────────────────────────────────────────────────────────────────────────────
# Utilidades
# ──────────────────────────────────────────────────────────────────────────────
def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep=";", decimal=",", encoding="utf-8-sig", na_values=["N/A", ""],
 skipinitialspace=True)


def _yes(series: pd.Series) -> pd.Series:
    """'Sí' / 'No' -> bool."""
    return series.astype(str).str.strip().str.lower().isin(["sí", "si", "true", "1", "yes"])


def _clean_text(series: pd.Series) -> pd.Series:
    s = series.astype("string").str.strip()
    return s.mask(s.isin(["", "N/A", "nan", "None"])).astype(object).where(s.notna(), np.nan)


def _to_dt(day: date, hhmmss: pd.Series) -> pd.Series:
    """Combina un día con una hora 'HH:MM:SS'."""
    td = pd.to_timedelta(hhmmss.astype("string").str.strip(), errors="coerce")
    return pd.Timestamp(day) + td


def _dist_value(text: str):
    value = float(text)
    return int(value) if value.is_integer() else value


def _distances_in(columns) -> list:
    found = set()
    for c in columns:
        m = re.fullmatch(r"IAS (\d+(?:\.\d+)?) NM", c)
        if m:
            found.add(_dist_value(m.group(1)))
    return sorted(found)


# ──────────────────────────────────────────────────────────────────────────────
# Parejas
# ──────────────────────────────────────────────────────────────────────────────
def _prepare_pairs(raw: pd.DataFrame, day: date) -> pd.DataFrame:
    df = raw.rename(columns=PAIR_RENAME).copy()

    for col in BOOL_COLS:
        df[col] = _yes(df[col]) if col in df else False
    for col in NUM_PAIR_COLS:
        df[col] = pd.to_numeric(df.get(col), errors="coerce")
    for col in ("Hora 4NM", "Hora THR"):
        df[col] = _clean_text(df[col]) if col in df else np.nan

    fr = df["Frustrada Seguidor"].astype(str).str.strip()
    df["Frustrada seguidor"] = fr.str.startswith("Sí")
    df["Tipo frustrada seguidor"] = np.where(
        df["Frustrada seguidor"], fr.str.replace(r"^Sí\s*-?\s*", "", regex=True).replace("", ND), "")
    df["Frustrada líder"] = False  # se completa al cruzar con las aproximaciones

    for col in ("Wake Cat", "Cat", "Prev Wake Cat", "Prev Cat"):
        df[col] = df[col].fillna(ND).astype(str)
    df["Par RECAT"] = df["Prev Cat"] + " → " + df["Cat"]

    df["Date"] = day
    df["T4_dt"] = _to_dt(day, df["Hora 4NM"])
    df["THR_dt"] = _to_dt(day, df["Hora THR"])
    # Si 4NM y THR quedan a un lado y otro de medianoche, THR es del día siguiente
    rollover = (df["THR_dt"] < df["T4_dt"] - pd.Timedelta(hours=12))
    df.loc[rollover, "THR_dt"] += pd.Timedelta(days=1)
    return df


# ──────────────────────────────────────────────────────────────────────────────
# Aproximaciones
# ──────────────────────────────────────────────────────────────────────────────
def _prepare_arrivals(raw: pd.DataFrame, day: date) -> pd.DataFrame:
    df = pd.DataFrame(index=raw.index)
    df["Date"] = day
    df["Vuelo"] = raw["Vuelo"].astype(str).str.strip()
    df["Callsign"] = df["Vuelo"]

    fr = raw["Frustrada"].astype(str).str.strip()
    is_ga = fr.str.startswith("Sí")
    df["Frustrada"] = fr
    df["Tipo frustrada"] = np.where(is_ga, fr.str.replace(r"^Sí\s*-?\s*", "", regex=True).replace("", ND), "")
    df["Última"] = ~is_ga  # True = aproximación que termina en aterrizaje

    df["Pista"] = raw["Pista"]
    df["Tipo Aeronave"] = raw["Tipo Aeronave"].fillna(ND).astype(str)
    df["Hora llegada"] = pd.to_datetime(raw["Hora llegada"], errors="coerce")

    # STAR / Wake / Cat se rellenan después a partir de las parejas
    df["STAR"], df["Wake Cat"], df["Cat"] = np.nan, ND, ND

    df["ias_THR"] = pd.to_numeric(raw.get("IAS THR"), errors="coerce")
    df["gs_THR"] = pd.to_numeric(raw.get("GS THR"), errors="coerce")
    for d in _distances_in(raw.columns):
        df[f"ias_{d}"] = pd.to_numeric(raw.get(f"IAS {d} NM"), errors="coerce")
        df[f"gs_{d}"] = pd.to_numeric(raw.get(f"GS {d} NM"), errors="coerce")
        df[f"t_{d}"] = pd.to_numeric(raw.get(f"Tiempo {d} NM (s)"), errors="coerce")
    return df


def _nearest(left: pd.DataFrame, right: pd.DataFrame, left_time: str, right_time: str) -> pd.DataFrame:
    """merge_asof por (callsign, pista) al instante más cercano dentro de la tolerancia.

    Devuelve ``right`` alineado con el índice de ``left`` (NaN donde no hay coincidencia).
    """
    lt = left[["Callsign", "Pista", left_time]].dropna(subset=[left_time]).rename(columns={left_time: "_t"})
    rt = right.dropna(subset=[right_time]).rename(columns={right_time: "_t"})
    if lt.empty or rt.empty:
        return right.iloc[0:0].reindex(left.index)
    lt = lt.assign(_i=lt.index).sort_values("_t")
    rt = rt.sort_values("_t")
    merged = pd.merge_asof(lt, rt, on="_t", by=["Callsign", "Pista"], direction="nearest", tolerance=MATCH_TOLERANCE)
    return merged.set_index("_i").drop(columns=["_t", "Callsign", "Pista"]).reindex(left.index)


def _enrich_day(pairs: pd.DataFrame, arrivals: pd.DataFrame):
    """Completa STAR / Wake / Cat en aproximaciones y 'Frustrada líder' en parejas."""
    if pairs.empty or arrivals.empty:
        return pairs, arrivals

    # 1) Datos de la aeronave desde las parejas: primero como líder (con hora), luego como seguidor.
    leaders = pairs.rename(columns={"Líder": "Callsign"})[
        ["Callsign", "Pista", "THR_dt", "Prev STAR", "Prev Wake Cat", "Prev Cat"]
    ].rename(columns={"Prev STAR": "STAR", "Prev Wake Cat": "Wake Cat", "Prev Cat": "Cat"})
    matched = _nearest(arrivals, leaders, "Hora llegada", "THR_dt")
    for col in ("STAR", "Wake Cat", "Cat"):
        arrivals[col] = matched[col].combine_first(arrivals[col].replace(ND, np.nan))

    # Los que no fueron líder (último de cada pista) se buscan como seguidor por indicativo + pista
    missing = arrivals["Cat"].isna() | arrivals["STAR"].isna()
    if missing.any():
        followers = (pairs.rename(columns={"Seguidor": "Callsign"})
                     [["Callsign", "Pista", "STAR", "Wake Cat", "Cat"]]
                     .drop_duplicates(["Callsign", "Pista"], keep="last"))
        keyed = arrivals.loc[missing, ["Callsign", "Pista"]].merge(followers, on=["Callsign", "Pista"], how="left")
        keyed.index = arrivals.index[missing]
        for col in ("STAR", "Wake Cat", "Cat"):
            arrivals.loc[missing, col] = arrivals.loc[missing, col].combine_first(keyed[col])
    for col in ("Wake Cat", "Cat"):
        arrivals[col] = arrivals[col].fillna(ND)

    # 2) ¿El líder de la pareja estaba en una frustrada?
    ga = arrivals.loc[~arrivals["Última"], ["Callsign", "Pista", "Hora llegada"]].assign(_ga=True)
    if not ga.empty:
        hit = _nearest(pairs.rename(columns={"Líder": "Callsign"}), ga, "THR_dt", "Hora llegada")
        pairs["Frustrada líder"] = hit["_ga"].fillna(False).astype(bool)
    return pairs, arrivals


# ──────────────────────────────────────────────────────────────────────────────
# Carga de la carpeta
# ──────────────────────────────────────────────────────────────────────────────
def load_folder(folder, date_from=None, date_to=None) -> Dataset:
    """Carga solo los días con ``date_from <= día <= date_to`` (ambos incluidos; None = sin límite)."""
    folder = Path(folder)
    warnings: list[str] = []
    files = _scan(folder)
    if not folder.is_dir():
        warnings.append(f"La carpeta {folder} no existe.")
    days = sorted({day for day, _ in files if _in_range(day, date_from, date_to)})

    pair_parts, arr_parts, raw_pair_parts, raw_perf_parts = [], [], [], []
    all_dists: set = set()
    loaded_days = []
    p_off = a_off = 0  # desplazamientos para que el índice sea global y único

    for day in days:
        p_path, a_path = files.get((day, KIND_PAIRS)), files.get((day, KIND_PERF))
        if p_path is None:
            warnings.append(f"{day:%d/%m/%Y}: falta el CSV de separaciones (Results).")
        if a_path is None:
            warnings.append(f"{day:%d/%m/%Y}: falta el CSV de IAS / tiempos (Airspeed_Time).")

        pairs_day = arr_day = None
        raw_p = raw_a = None
        try:
            if p_path is not None:
                raw_p = _read_csv(p_path)
                pairs_day = _prepare_pairs(raw_p, day)
        except Exception as exc:  # noqa: BLE001 - se informa al usuario y se continúa
            warnings.append(f"{p_path.name}: no se pudo leer ({exc}).")
        try:
            if a_path is not None:
                raw_a = _read_csv(a_path)
                arr_day = _prepare_arrivals(raw_a, day)
                all_dists |= set(_distances_in(raw_a.columns))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{a_path.name}: no se pudo leer ({exc}).")

        if pairs_day is None and arr_day is None:
            continue
        if pairs_day is None:
            pairs_day = pd.DataFrame(columns=PAIR_COLUMNS)
        if arr_day is None:
            arr_day = pd.DataFrame(columns=ARR_META)
        else:
            pairs_day, arr_day = _enrich_day(pairs_day, arr_day)

        pairs_day.index = pd.RangeIndex(p_off, p_off + len(pairs_day))
        arr_day.index = pd.RangeIndex(a_off, a_off + len(arr_day))
        p_off += len(pairs_day)
        a_off += len(arr_day)

        loaded_days.append(day)
        pair_parts.append(pairs_day)
        arr_parts.append(arr_day)
        if raw_p is not None:
            raw_pair_parts.append(raw_p.assign(Fecha=day).set_index(pairs_day.index))
        if raw_a is not None:
            raw_perf_parts.append(raw_a.assign(Fecha=day).set_index(arr_day.index))

    if not loaded_days:
        return Dataset(warnings=warnings)

    distances = sorted(all_dists)
    pairs = pd.concat(pair_parts)
    arrivals = pd.concat(arr_parts)

    raw_pairs = pd.concat(raw_pair_parts) if raw_pair_parts else pd.DataFrame()
    raw_perf = pd.concat(raw_perf_parts) if raw_perf_parts else pd.DataFrame()

    # Garantizar todas las columnas por distancia aunque algún día no las tenga
    for d in distances:
        for prefix in ("ias", "gs", "t"):
            if f"{prefix}_{d}" not in arrivals:
                arrivals[f"{prefix}_{d}"] = np.nan
    for col in BOOL_COLS + ["Frustrada líder", "Frustrada seguidor"]:
        pairs[col] = pairs[col].fillna(False).astype(bool)
    arrivals["Última"] = arrivals["Última"].fillna(True).astype(bool)

    # Columnas Fecha primero, como en el export original
    if not raw_pairs.empty:
        raw_pairs = raw_pairs[["Fecha"] + [c for c in raw_pairs.columns if c != "Fecha"]]
    if not raw_perf.empty:
        raw_perf = raw_perf[["Fecha"] + [c for c in raw_perf.columns if c != "Fecha"]]
        if "Hora llegada" in raw_perf:
            raw_perf["Hora llegada"] = pd.to_datetime(raw_perf["Hora llegada"], errors="coerce")

    return Dataset(
        days=sorted(loaded_days), distances=distances, pairs=pairs, arrivals=arrivals,
        raw_pairs=raw_pairs, raw_performance=raw_perf, warnings=warnings,
    )