from Fligths import read_bbdd, get_arrivals, read_sql, read_frustrades
from Distancias import LeaderFollower, export_pairs_to_excel, radar_sparation, loa_separation, wake_separation
from geo_utils2 import latlon_to_xy
from Airspeed import get_ias, export_ias_to_excel, get_time_to_thr, export_time_to_thr_excel
import math
from kml_export import export_callsign_kml
from datetime import date


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

fecha = date(2025, 1, 13)
fecha_str = fecha.strftime("%d_%m_%Y")

#Leer vuelos y separar en funcion si hay frustradas
lista_vuelos = read_bbdd(fecha)
#lista_vuelos = read_sql("arribades.sql", fecha)
tipos_frustrada = read_frustrades("frustrades.sql")
print("Vuelos procesados")

arrivals = get_arrivals(lista_vuelos.values())
print("Arrivals procesadas")

pairs = LeaderFollower(arrivals, lista_vuelos, THR)
print("Parejas procesadas")

#Comprobar separaciones por prioridad (Estela, Radar, LoA)
wake_check = wake_separation(pairs)
radar_wake_check = radar_sparation(wake_check)
loa_wake_radar_check = loa_separation(radar_wake_check)

#Calcular IAS a distintas distancias
dists = [1, 2, 2.5, 3, 4, 5, 6, 7, 8, 9, 10]
ias_arrivals = get_ias(arrivals, dists, THR)
time_to_thr_arr = get_time_to_thr(arrivals, dists, THR)

export_pairs_to_excel(loa_wake_radar_check, f"{fecha_str}_Results_LEBL.xlsx", tipos_frustrada)
export_ias_to_excel(ias_arrivals,dists,f"{fecha_str}_IAS.xlsx", tipos_frustrada)
export_time_to_thr_excel(time_to_thr_arr, dists, f"{fecha_str}_Time_to_THR.xlsx", tipos_frustrada)

# THR_xx_latlon: las coordenadas que ya usas para THR (lat, lon en grados decimales)
#thr_latlon = (41 + 17/60 + 16.66/3600, 2 + 5/60 + 5.76/3600)   # LEBL-02

#export_callsign_kml(arrivals, "VLG11K", thr_latlon=thr_latlon)
# genera CCA845_FR0.kml (uno por cada aproximación/frustrada)