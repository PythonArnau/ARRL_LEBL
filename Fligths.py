import mysql.connector
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from geo_utils2 import xy_to_latlon


class FlightRecord:
    def __init__(self):

        #Record
        self.time: int = 0          #ToD [s]
        self.day: int = 0           #Dia: 2025-01-14 -> 20250114
        self.pos_x: float = 0.0     #Coordenada estereografica [nm]
        self.pos_y: float = 0.0     #Coordenada estereografica [nm]
        self.fl: float = 0.0        #Flight Level
        self.alt: float = 0.0       #Altitud [ft]
        self.bp: float = 0.0        #Barometric pressure
        self.gs: float = 0.0        #Ground speed
        self.ias: float = 0.0       #Indicated airspeed
        self.lat: float = 0.0       #Latitud [º]
        self.lon: float = 0.0       #Longitud [º]
        self.sensor: str = ""       #ADSB-BCN/Radar-BCN
        self.cont: str = ""         #Contador
        self.numfr: int = 0         #Contador de frustrada

        self.cum_dist: float = None


    def date_to_ToD(date_str):
        dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S.%f")

        day = int(dt.strftime("%Y%m%d"))
        tod = dt.hour * 3600 + dt.minute * 60 + dt.second

        return day, tod
        
class Flight:
    #Corresponde a todos los records de un mismo vuelo
    def __init__(self):
        #Plan de vuelo
        self.callsign: str = ""
        self.departure: str = ""
        self.arrival: str = ""
        self.arr_hour: str = ""
        self.thr_hour: str = ""
        self.thr_time: int = 0
        self.route: str = ""
        self.aircraft: str = ""
        self.wake: str = ""
        self.wake_recat: str = ""
        self.star: str = ""
        self.arr_runway: str = ""

        self.records = []

class Arrival:
    def __init__(self):
        self.callsign: str = ""
        self.runway: str = ""
        self.numfr: int = 0
        self.last_arr: bool = True
        self.thr_time: int = 0
        self.arr_hour: str = ""

        self.records: list = []

        self.thr_reached: bool = False

        self.thr_record = None
        self.thr_dist = None
        self.mile4_record = None
        self.mile4_dist = None

        self.cum_dist: list = []
        self.ias_dict = {}
        self.time_to_thr_dict = {}



def read_bbdd(fecha):
    load_dotenv()
    connection = mysql.connector.connect(
        host = os.getenv("DB_HOST"),
        user = os.getenv("DB_USER"),
        password = os.getenv("DB_PASSWORD"),
        database = os.getenv("DB_NAME"),
        port=3306
    )

    if connection.is_connected():
        print("Conexion correcta")

    fecha_inicio = datetime.combine(fecha, datetime.min.time())
    fecha_fin = fecha_inicio + timedelta(days=1)

    cursor = connection.cursor(dictionary=True)

    query = "SELECT * FROM arribades WHERE HoraARR >= %s AND HoraARR < %s"
    cursor.execute(query, (fecha_inicio, fecha_fin))

    #cursor.execute("SELECT * FROM arribades WHERE HoraARR >= '2025-01-13 00:00:00' AND HoraARR < '2025-01-13 23:59:59'")
    #cursor.execute("SELECT * FROM arribades WHERE HoraARR >= '2025-01-14 00:00:00' AND HoraARR < '2025-01-14 23:59:59'")



    rows = cursor.fetchall()
    print("NUMERO FILAS: ", len(rows))
    vuelos = {}


    for row in rows:
        
        id = (row["Callsign"], row["HoraARR"])

        if id not in vuelos:

            
            flight = Flight()
            flight.callsign = row["Callsign"]
            flight.departure = row["Origen"]
            flight.arrival = row["Desti"]
            flight.arr_hour = row["HoraARR"]
            flight.thr_hour = row["HoraTHR"]
            flight.route = row["RutaSACTA"]
            flight.aircraft = row["Aeronau"]
            flight.wake = row["Estela"]
            flight.wake_recat = row["EstelaRecat"]
            flight.star = row["STAR"]
            flight.arr_runway = row["PistaARR"]

            thrday,thrtime = FlightRecord.date_to_ToD(row["HoraTHR"])
            flight.thr_time = thrtime
            vuelos[id] = flight

        rec = FlightRecord()
        rec.pos_x = row["X"]
        rec.pos_y = row["Y"]
        rec.fl = row["FL"]
        rec.alt = row["ALT"]
        rec.bp = row["BP"]
        rec.gs = row["GS"]
        rec.ias = row["IAS"]
        rec.lat = row["lat"]
        rec.lon = row["lon"]
        rec.sensor = row["Sensor"]
        rec.cont = row["Cont"]
        rec.numfr = row["NumFR"]
        day, time = FlightRecord.date_to_ToD(row["ToD"])
        rec.day = day
        rec.time = time

        vuelos[id].records.append(rec)

    cursor.close()
    connection.close()

    print(f"Número de vuelos creados: {len(vuelos)}")
    return vuelos


def get_arrivals(flights):
    arrivals = []

    for flight in flights:
        rec_for_arr = {}
        order = []


        #Mirar crear arrival si existe frustrada o no
        for rec in flight.records:

            fr_index = rec.numfr

            if fr_index not in rec_for_arr:
                rec_for_arr[fr_index] = []
                order.append(fr_index)
            rec_for_arr[fr_index].append(rec)
        
        for i, fr_index in enumerate(order):
            arr = Arrival()
            arr.callsign = flight.callsign
            arr.arr_hour = flight.arr_hour
            arr.runway = flight.arr_runway
            arr.numfr = fr_index
            arr.last_arr = (i == len(order) - 1)
            arr.thr_time = flight.thr_time
            arr.records = rec_for_arr[fr_index]
            arrivals.append(arr)

    #Eliminar vuelos con fallos ADS-B
    arrivals = remove_adsb(arrivals, "CCA845")

    #Interpolamos valores vacios en las arrivals
    for arr in arrivals:
        arr.records = interpolate_records(arr)
    
    print("Arrivals interpoladas")
    return arrivals

def interpolate_records(flights):
    
    records = flights.records
    #Si no hay suficientes records no interpolar
    if len(records) < 2:
        return list(records)
    
    #Interpolar IAS que tienen valor 0.0
    ias_originales = [rec.ias if rec.ias != 0.0 else np.nan for rec in records]
    ias_filtradas = pd.Series(ias_originales).interpolate(method='linear').bfill().ffill().values


    for idx, nueva_ias in enumerate(ias_filtradas):
        records[idx].ias = float(nueva_ias)

    #Crear nuevos records interpolados
    new_record_list = []

    for i in range(len(records) - 1):
        r = records[i]
        r_next = records[i+1]

        new_record_list.append(r)

        diff = int(r_next.time - r.time)
        if diff > 1:

            dx_per_sec = (r_next.pos_x - r.pos_x)/diff
            dy_per_sec = (r_next.pos_y - r.pos_y)/diff
            dh_per_sec = (r_next.alt - r.alt)/diff
            dias_per_sec = (r_next.ias - r.ias)/diff

            for s in range(1, diff):
                new_rec = FlightRecord()

                new_rec.pos_x = r.pos_x + (dx_per_sec*s)
                new_rec.pos_y = r.pos_y + (dy_per_sec*s)
                new_rec.alt = r.alt + (dh_per_sec*s)
                new_rec.ias = r.ias + (dias_per_sec*s)

                new_rec.time = r.time + s
                new_rec.sensor = "INTERPOLATED"

                new_rec.day = r.day
                new_rec.numfr = r.numfr
                new_rec.cont = r.cont
                new_rec.bp = r.bp

                new_rec.lat, new_rec.lon = xy_to_latlon(new_rec.pos_x, new_rec.pos_y)

                new_record_list.append(new_rec)

    new_record_list.append(records[-1])

    return new_record_list

def remove_adsb(arrivals, callsign):
    
    #Elimina los records ADS-B de los vuelos con fallos en esos records

    for arr in arrivals:
        if arr.callsign == callsign:          
            new_rec = []
            
            for rec in arr.records:
                if rec.sensor != "ADSB-BCN":
                    new_rec.append(rec)
            
            arr.records = new_rec

    return arrivals
