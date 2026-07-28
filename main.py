from Fligths import read_bbdd, get_arrivals
from Distancias import LeaderFollower, export_pairs_to_excel
from geo_utils2 import latlon_to_xy

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

#Leer vuelos y separar en funcion si hay frustradas
lista_vuelos = read_bbdd()
print("Vuelos procesados")

arrivals = get_arrivals(lista_vuelos.values())
print("Arrivals procesadas")

pairs = LeaderFollower(arrivals, lista_vuelos, THR)
print("Parejas procesadas")

export_pairs_to_excel(pairs, "Separaciones_LELB.xlsx")