import mysql.connector
from dotenv import load_dotenv
import os

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
connection.close()