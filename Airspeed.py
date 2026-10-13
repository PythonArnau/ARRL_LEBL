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

def get_time_to_thr(arrivals, distances, thrs):
    #Busca el record a la distancia seleccionada. Calcula el tiempo (s) que tiene hasta llegar a la THR.
    #Se resta el tiempo que llega a THR con el tiempo del record a la distancia especificada 

    all_cum_dist(arrivals, thrs)

    segundos_dia = 24*3600

    for arr in arrivals:

        arr.time_to_thr_dict = {}
        thr_time = arr.thr_record.time

        for dist in distances:
            idx = min(range(len(arr.cum_dist)), key=lambda i: abs(arr.cum_dist[i] - dist))
            rec_time = arr.records[idx].time
            
            #Comprobar que no cruza medianoche
            if thr_time < rec_time:
                time_to_thr = (thr_time + segundos_dia) - rec_time
            else:
                time_to_thr = thr_time - rec_time
                
            arr.time_to_thr_dict[dist] = time_to_thr
    
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


def export_time_to_thr_excel(arrivals, distances, output_filename):
    """
    Exporta el tiempo restante hasta la THR para cada llegada y distancia.

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
            "Hora THR": arr.thr_time
        }

        for dist in distances:
            row[f"Tiempo {dist} NM (s)"] = arr.time_to_thr_dict.get(dist)

        data.append(row)

    df = pd.DataFrame(data)

    try:
        df.to_excel(
            output_filename,
            index=False,
            sheet_name="Tiempo_a_THR"
        )
        print(f"-> Datos exportados con éxito a '{output_filename}' ({len(arrivals)} arrivals).")
    except Exception as e:
        print(f"Error al exportar a Excel: {e}")