import mysql.connector
from dotenv import load_dotenv
import os
import folium

"""
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

cursor = connection.cursor()

cursor.execute("SELECT * FROM arribades")

filas = cursor.fetchall()

for fila in filas:
    print(fila)

cursor.close()
connection.close()"""

# Crear mapa centrado en España
m = folium.Map(location=[40.4, -3.7], zoom_start=5)

# Trayectoria Madrid -> París -> Londres
ruta = [
    [40.4168, -3.7038],
    [48.8566, 2.3522],
    [51.5074, -0.1278]
]

folium.PolyLine(
    ruta,
    color="red",
    weight=3
).add_to(m)

m.save("vuelos.html")