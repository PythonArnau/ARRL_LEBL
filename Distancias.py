import math
import pandas as pd
from Fligths import get_tipo_frustrada

class Pair:
    def __init__(self):
        self.pair: str = ""
        self.runway: str = ""
        self.frustrada_leader = False
        self.frustrada_follower = False
        self.arr_hour_follower = ""

        self.leader: str = ""
        self.star_leader: str = ""
        self.wake_leader: str = ""
        self.wake_recat_leader: str = ""
        self.aircraft_leader: str = ""


        self.follower: str = ""
        self.star_follower: str = ""
        self.wake_follower: str = ""
        self.wake_recat_follower: str = ""
        self.aircraft_follower: str = ""

        #Separaciones
        self.separation_thr: float = None
        self.tod_thr: int = None
        self.separation_4mile: float = None
        self.tod_4mile: int = None
        self.alt_thr: float = None
        self.alt_4mile: float = None

        self.radar_thr: bool = False
        self.radar_4mile: bool = False
        self.estela_thr: bool = False
        self.estela_4mile: bool = False
        self.loa_thr: bool = False
        self.loa_4mile: bool = False
        self.sep_op_thr: bool = False
        self.sep_op_4mile: bool = False

        


def marcar_frustradas(arr_list):
    """Todas las arrivals de un callsign salvo la última (por hora de umbral) son frustradas."""
    def t(a):
        return a.thr_record.time if a.thr_record is not None else a.thr_time

    por_callsign = {}
    for a in arr_list:
        por_callsign.setdefault(a.callsign, []).append(a)

    for lista in por_callsign.values():
        lista.sort(key=t)
        for a in lista[:-1]:
            a.last_arr = False


def LeaderFollower(arrivals, flights_dict, thresholds):
    runways = {}
    pairs = []

    for arr in arrivals:
        runways.setdefault(arr.runway, []).append(arr)

    for rwy, arr_list in runways.items():

        # Marcar en qué momento cruza el umbral y la milla 4
        thr_xy = thresholds.get(rwy) if thresholds else None
        if thr_xy is not None:
            for arr in arr_list:
                marcar_records(arr, thr_xy)

        # Detectar frustradas (independiente de NumFR)
        marcar_frustradas(arr_list)

        # Ordenar por el instante real de paso por umbral
        arr_list_sort = sorted(
            arr_list,
            key=lambda x: x.thr_record.time if x.thr_record is not None else x.thr_time
        )
        for i in range(len(arr_list_sort)-1):
            arr_leader = arr_list_sort[i]
            arr_follower = arr_list_sort[i+1]

            flight_leader = flights_dict.get((arr_leader.callsign, arr_leader.arr_hour)) if flights_dict else None
            flight_follower = flights_dict.get((arr_follower.callsign, arr_follower.arr_hour)) if flights_dict else None
            
            p = Pair()
            p.runway = rwy

            leader_id = arr_leader.callsign
            follower_id = arr_follower.callsign
            
            p.pair = f"{leader_id} - {follower_id}"

            p.leader = leader_id
            p.star_leader = flight_leader.star
            p.wake_leader = flight_leader.wake
            p.wake_recat_leader = flight_leader.wake_recat

            p.follower = follower_id
            p.arr_hour_follower = flight_follower.arr_hour
            p.star_follower = flight_follower.star
            p.wake_follower = flight_follower.wake
            p.wake_recat_follower = flight_follower.wake_recat

            # Indica si la pareja contiene alguna aproximación frustrada
            p.frustrada_leader = not arr_leader.last_arr
            p.frustrada_follower = not arr_follower.last_arr
            
            if arr_leader.thr_record is not None:
                tod_leader_thr = arr_leader.thr_record.time
                rec_follower_thr = get_record_time(arr_follower.records, tod_leader_thr)
                p.separation_thr, p.alt_thr = get_separation(arr_leader.thr_record, rec_follower_thr)
                p.tod_thr = tod_leader_thr
                
                
            
            if arr_leader.mile4_record is not None:
                tod_leader_4nm = arr_leader.mile4_record.time
                rec_follower_4nm = get_record_time(arr_follower.records, tod_leader_4nm)
                p.separation_4mile, p.alt_4mile = get_separation(arr_leader.mile4_record, rec_follower_4nm)
                p.tod_4mile = tod_leader_4nm


            pairs.append(p)

    return pairs

def dist_to_thr(records, thr_x, thr_y):
    dists = []
    for r in records:
        d = math.hypot(r.pos_x - thr_x, r.pos_y - thr_y)
        dists.append(d)
    return dists

def cumulative_dist(records, ref_idx):
    
    n = len(records)
    dists = [0.0]*n
    dists[ref_idx] = 0.0

    for i in range(ref_idx-1, -1, -1):
        tramo = math.hypot(records[i].pos_x - records[i+1].pos_x, records[i].pos_y - records[i+1].pos_y)
        dists[i] = dists[i+1] + tramo

    
    return dists

def marcar_records(arrival, thr):
    "Marca los records correspondientes a la milla 4 y al cruce del umbral de cada llegada"

    records = arrival.records
    thr_x, thr_y = thr

    #Miramos el punto de cruce con el umbral
    direct_dists = dist_to_thr(records, thr_x, thr_y)
    idx_thr = min(range(len(direct_dists)), key=lambda i: direct_dists[i])
    arrival.thr_record = records[idx_thr]
    arrival.thr_dist = direct_dists[idx_thr]

    #Distncia acumulada desde umbral
    dists = cumulative_dist(records, idx_thr)


    if min(dists) <= 4.0:
        idx_4nm = min(range(len(dists)), key=lambda i: abs(dists[i] - 4.0))
        arrival.mile4_record = records[idx_4nm]
        arrival.mile4_dist = dists[idx_4nm]

    return arrival

def get_record_time(records, tod):
    #Devuelve el record correspondiente a un tiempo especifico. (Records cada 1s)
    for rec in records:
        if rec.time == tod:
            return rec

def get_separation(rec_leader, rec_follower):
    #Distancia entre el record del leader y el del follower en ese mismo instante de tiempo
    if rec_leader is None or rec_follower is None:
        return None, None 
    dist = math.hypot(rec_leader.pos_x - rec_follower.pos_x, rec_leader.pos_y - rec_follower.pos_y)
    alt = abs(rec_leader.alt - rec_follower.alt)
    return dist, alt


import pandas as pd


def tod_to_hhmmss(tod):
    """Convierte segundos del día (ToD) a un string en formato HH:MM:SS"""
    if tod is None:
        return "N/A"
    horas = int(tod // 3600)
    minutos = int((tod % 3600) // 60)
    segundos = int(tod % 60)
    return f"{horas:02d}:{minutos:02d}:{segundos:02d}"


def radar_sparation(pairs):
    #Comprobar separación radar por cada pareja en THR y 4NM
    for pair in pairs:
        if pair.estela_thr is False:
            if pair.separation_thr is not None and pair.separation_thr < 2.4:
                pair.radar_thr = True

                if pair.alt_thr < 1000:
                    pair.sep_op_thr = True
            
        if pair.estela_4mile is False:
            if pair.separation_4mile is not None and pair.separation_4mile < 2.4:
                pair.radar_4mile = True

                if pair.alt_4mile < 1000:
                    pair.sep_op_4mile = True
    return pairs

def loa_separation(pairs):
    #Comprobar LoA por cada pareja en THR y 4NM. 

    for pair in pairs:
        lead_recat = pair.wake_recat_leader
        follow_recat = pair.wake_recat_follower
        
        sep = get_loa_sep_4mile(lead_recat, follow_recat)
        sep_thr = get_loa_sep_thr(lead_recat, follow_recat)

        if pair.radar_4mile is False or pair.estela_4mile is False:
            if sep is True:
                if pair.separation_4mile is not None and pair.separation_4mile < 2.9:
                    pair.loa_4mile = True 
        
        if pair.radar_thr is False or pair.estela_thr is False:
            if sep_thr is True:
                if pair.separation_thr is not None and pair.separation_thr < 2.9:
                    pair.loa_thr = True

    return pairs

def get_loa_sep_4mile(wake_lead, wake_follow):
    # Devuelve True si hay que tener en cuenta LoA, False en caso contrario

    if wake_lead == "M+":
        if wake_follow == "M+": return True
        elif wake_follow == "M-": return True
        elif wake_follow == "J": return True
        elif wake_follow == "H+": return True
        elif wake_follow == "H-": return True

    elif wake_lead == "M-":
        if wake_follow == "M+": return True
        elif wake_follow == "M-": return True
        elif wake_follow == "J": return True
        elif wake_follow == "H+": return True
        elif wake_follow == "H-": return True

    elif wake_lead == "L+":
        if wake_follow == "J": return True
        elif wake_follow == "H+": return True
        elif wake_follow == "H-": return True
        elif wake_follow == "M+": return True
        elif wake_follow == "M-": return True

    return False

def get_loa_sep_thr(wake_lead, wake_follow):
    # Devuelve separación LoA en THR. Devuelve None si no aplica.

    if wake_lead == "H+":
        if wake_follow == "J": return True

    elif wake_lead == "H-":
        if wake_follow == "J": return True
        elif wake_follow == "H+": return True

    elif wake_lead == "L+":
        if wake_follow == "J": return True
        elif wake_follow == "H+": return True
        elif wake_follow == "H-": return True
        elif wake_follow == "M+": return True
        elif wake_follow == "M-": return True

    return False


def wake_separation(pairs):
    #Comprobar si se cumple separacion por estela
    e = 0.1

    for pair in pairs:
        lead_recat = pair.wake_recat_leader
        follow_recat = pair.wake_recat_follower

        separation = get_wake_sep(lead_recat,follow_recat)

        if separation is not None:

            if pair.separation_thr is not None and pair.separation_thr < (separation-e):
                pair.estela_thr = True
                if pair.alt_thr < 1000:
                    pair.sep_op_thr = True

            if pair.separation_4mile is not None and pair.separation_4mile < (separation-e):
                pair.estela_4mile = True
                if pair.alt_4mile < 1000:
                    pair.sep_op_4mile = True
    
    return pairs


def get_wake_sep(wake_lead, wake_follow):
    #Devuelve separacion minima en funcion de estela, devuelve None si no esta especificado

    if wake_lead == "J":
        if wake_follow == "J": return 3
        elif wake_follow == "H+": return 4
        elif wake_follow == "H-": return 5
        elif wake_follow == "M+": return 5
        elif wake_follow == "M-": return 6
        elif wake_follow == "L+": return 8

    elif wake_lead == "H+":
        if wake_follow == "H+": return 3
        elif wake_follow == "H-": return 4
        elif wake_follow == "M+": return 4
        elif wake_follow == "M-": return 5
        elif wake_follow == "L+": return 7

    elif wake_lead == "H-":
        if wake_follow == "H-": return 3
        elif wake_follow == "M+": return 3
        elif wake_follow == "M-": return 4
        elif wake_follow == "L+": return 6
    
    elif wake_lead == "M+":
        if wake_follow == "L+": return 5

    elif wake_lead == "M-":
        if wake_follow == "L+": return 4

    elif wake_lead == "L+":
        if wake_follow == "L+": return 3
    
    else: return None
    
    
       

def export_pairs_to_excel(pairs, output_filename="Separaciones_LEBL.xlsx", tipos_frustrada=None):

    if not pairs:
        print("No hay parejas para exportar.")
        return

    if tipos_frustrada is None:
        tipos_frustrada = {}

    data = []

    for p in pairs:
        if p.frustrada_follower:
            tipo = tipos_frustrada.get(p.follower)
            tipo = get_tipo_frustrada(p.follower, p.arr_hour_follower, tipos_frustrada)

            
            if tipo:
                frustrada_txt = f"Sí - {tipo}"
            else:
                frustrada_txt = "Sí"
        else:
            frustrada_txt = "No"

        row = {
            "Pareja": p.pair,
            "Pista": p.runway,
            "Frustrada Seguidor": frustrada_txt,

            "Líder": p.leader,
            "STAR Líder": p.star_leader,
            "Estela Líder": p.wake_leader,
            "RECAT Líder": p.wake_recat_leader,
            "Tipo Aeronave Líder": p.aircraft_leader,

            "Seguidor": p.follower,
            "STAR Seguidor": p.star_follower,
            "Estela Seguidor": p.wake_follower,
            "RECAT Seguidor": p.wake_recat_follower,
            "Tipo Aeronave Seguidor": p.aircraft_follower,

            # 4 NM
            "Hora 4NM": tod_to_hhmmss(p.tod_4mile),
            "Sep. 4NM (NM)": round(p.separation_4mile, 3) if p.separation_4mile is not None else "N/A",
            "Sep. Vertical 4NM (ft)": round(p.alt_4mile, 0) if p.alt_4mile is not None else "N/A",
            "Incumplimiento Radar 4NM": "Sí" if p.radar_4mile else "No",
            "Incumplimiento LoA 4NM": "Sí" if p.loa_4mile else "No",
            "Incumplimiento Estela 4NM": "Sí" if p.estela_4mile else "No",

            # THR
            "Hora THR": tod_to_hhmmss(p.tod_thr),
            "Sep. THR (NM)": round(p.separation_thr, 3) if p.separation_thr is not None else "N/A",
            "Sep. Vertical THR (ft)": round(p.alt_thr, 0) if p.alt_thr is not None else "N/A",
            "Incumplimiento Radar THR": "Sí" if p.radar_thr else "No",
            "Incumplimiento LoA THR": "Sí" if p.loa_thr else "No",
            "Incumplimiento Estela THR": "Sí" if p.estela_thr else "No",

            # Resultado global
            "Separación Operacional THR": "Sí" if p.sep_op_thr else "No",
            "Separación Operacional 4NM": "Sí" if p.sep_op_4mile else "No",

        }

        data.append(row)

    df = pd.DataFrame(data)

    try:
        df.to_excel(output_filename, index=False, sheet_name="Separaciones")
        print(f"-> Datos exportados con éxito a '{output_filename}' ({len(pairs)} parejas).")
    except Exception as e:
        print(f"Error al exportar a Excel: {e}")