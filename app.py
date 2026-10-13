import streamlit as st
import pandas as pd
from Fligths import read_bbdd, get_arrivals
from Distancias import LeaderFollower, export_pairs_to_excel, radar_sparation, loa_separation, wake_separation
from geo_utils2 import latlon_to_xy
from Airspeed import get_ias, export_ias_to_excel, get_time_to_thr, export_time_to_thr_excel
from kml_export import export_callsign_kml

# Configuracion pagina
st.set_page_config(page_title = "Análisis de aproximaciones", layout="wide")
st.title("Análisis de aproximaciones")

#Barra lateral
st.sidebar.header("Configuración")

fecha = st.sidebar.date_input("Fecha")

#Umbrales de las pistas (posicion de google earth)
THR_24R = latlon_to_xy(41 + 18/60 + 20.37/3600, 2 + 6/60 + 12.68/3600)
THR_06L = latlon_to_xy(41 + 17/60 + 41.70/3600, 2 + 4/60 + 19.97/3600)
THR_02 = latlon_to_xy(41 + 17/60 + 16.66/3600, 2 + 5/60 + 5.76/3600)
THR_20 = latlon_to_xy(41 + 18/60 + 32.85/3600, 2 + 5/60 + 40.51/3600)

THR = {
    "LEBL-24R": THR_24R,
    "LEBL-06L": THR_06L,
    "LEBL-02": THR_02,
    "LEBL-20": THR_20,
}

distancias = st.sidebar.multiselect("Distancias (NM)", default=[2,4,6,8])

if st.sidebar.button("Ejecutar análisis"):
    with st.spinner("Procesando datos..."):

        #Cargar datos
        lista_vuelos = read_bbdd(fecha)
        arrivals = get_arrivals(lista_vuelos.values())
        pairs = LeaderFollower(arrivals, lista_vuelos, THR)

        #Comprobar separaciones
        radar_check = radar_sparation(pairs)
        loa_radar_check = loa_separation(radar_check)
        wake_loa_radar_check = wake_separation(loa_radar_check)

        #Calcular IAS y tiempo a THR
        ias_arrivals = get_ias(arrivals, distancias, THR)
        time_to_thr_arr = get_time_to_thr(arrivals, distancias, THR)


