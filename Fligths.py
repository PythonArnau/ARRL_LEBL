import mysql.connector
from dotenv import load_dotenv
import os
from datetime import datetime

class FlightRecord:
    def __init__(self):

        #Plan de vuelo
        self.callsign: str = ""
        self.departure: str = ""
        self.arrival: str = ""
        self.arr_hour: str = ""
        self.thr_hour: str = ""
        self.route: str = ""
        self.aircraft: str = ""
        self.wake: str = ""
        self.wake_recat: str = ""
        self.star: str = ""
        self.arr_runway: str = ""

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
        self.cont: str = ""         #Contador?
        self.numfr: int = 0         #Contador de frustrada


    def date_to_ToD(date_str):
        dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S.%f")

        day = int(dt.strftime("%Y%m%d"))
        tod = dt.hour * 3600 + dt.minute * 60 + dt.second

        return day, tod
        

def read_bbdd():
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

    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT * FROM arribades")

    vuelos = []

    for row in cursor.fetchall():
        flight = FlightRecord()
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
        flight.pos_x = row["X"]
        flight.pos_y = row["Y"]
        flight.fl = row["FL"]
        flight.alt = row["ALT"]
        flight.bp = row["BP"]
        flight.gs = row["GS"]
        flight.ias = row["IAS"]
        flight.lat = row["lat"]
        flight.lon = row["lon"]
        flight.sensor = row["Sensor"]
        flight.cont = row["Cont"]
        flight.numfr = row["NumFR"]
        day, time = FlightRecord.date_to_ToD(row["ToD"])
        flight.day = day
        flight.time = time

        vuelos.append(flight)

    cursor.close()
    connection.close()

    return vuelos
