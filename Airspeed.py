from Distancias import cumulative_dist, dist_to_thr
import pandas as pd

def all_cum_dist(arrivals, thresholds):
    #Hacer funcion que añada la cum_dist en el atributo cum_dist de Arrival
    
    for arr in arrivals:
        thr = thresholds.get(arr.runway)
        thr_x, thr_y = thr

        #Record del umbral
        direct_dist = dist_to_thr(arr.records,thr_x,thr_y)
        idx_thr = min(range(len(direct_dist)), key=lambda i: direct_dist[i])

        dists = cumulative_dist(arr.records,idx_thr)
        arr.cum_dist = dists

def get_ias(arrivals, distances, thrs):
    #Busca que record se encuentra la distancia seleccionada. Devuelve la IAS de ese record
    # Distances: lista de distancias al umbral

    #Calculamos todas las distancias acumuladas
    all_cum_dist(arrivals, thrs)

    for arr in arrivals:
        
        arr.ias_dict = {}

        for dist in distances:
            idx = min(range(len(arr.cum_dist)), key=lambda i: abs(arr.cum_dist[i] - dist))
            ias = arr.records[idx].ias
            arr.ias_dict[dist] = ias
    
    return arrivals



def export_ias_to_excel(arrivals, distances,
                         output_filename):
    """
    Exporta la IAS de cada llegada para las distancias solicitadas.

    Parameters
    ----------
    arrivals : list[Arrival]
    distances : list[float]
    output_filename : str
    """

    data = []

    for arr in arrivals:

        row = {
            "Vuelo": f"{arr.callsign}_FR{arr.numfr}",
            "Callsign": arr.callsign,
            "Pista": arr.runway,
            "Hora llegada": arr.arr_hour,
        }

        for dist in distances:
            row[f"IAS {dist} NM"] = arr.ias_dict.get(dist)

        data.append(row)

    df = pd.DataFrame(data)

    try:
        df.to_excel(output_filename,
                    index=False,
                    sheet_name="IAS")
        print(f"-> Datos exportados con éxito a '{output_filename}' ({len(arrivals)} arrivals).")
    except Exception as e:
        print(f"Error al exportar a Excel: {e}")