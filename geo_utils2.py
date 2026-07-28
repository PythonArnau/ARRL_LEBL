import math
import numpy as np
import pandas as pd
from typing import Tuple, Union

# --- VALORES EXTRAÍDOS DE CONSTANTS.PY ---
_TMA_CENTER_LAT = 41 + 6/60 + 56.560/3600  # 41.1157111...
_TMA_CENTER_LON = 1 + 41/60 + 33.010/3600  # 1.6925027...
_RADIO_NM = 3438.954
_E = 0.0818191908426

def geodetic_to_conformal_lat(lat_rad: float) -> float:
    """
    Convierte latitud geodésica (WGS84) a latitud conforme.
    e = 0.0818191908426 (Excentricidad WGS84)
    """
    e = _E
    sin_lat = math.sin(lat_rad)
    term1 = ((1 - e * sin_lat) / (1 + e * sin_lat)) ** (e / 2)
    term2 = math.tan(math.pi / 4 + lat_rad / 2)
    
    chi = 2 * math.atan(term1 * term2) - math.pi / 2
    return chi

def geodetic_to_stereographic(lat: float, lon: float,
                              lat0: float = _TMA_CENTER_LAT,
                              lon0: float = _TMA_CENTER_LON,
                              R: float = _RADIO_NM) -> Tuple[float, float]:
    # Validación de rangos
    if not (-90 <= lat <= 90):
        raise ValueError(f"Latitud fuera de rango: {lat}. Debe estar entre -90 y 90")
    if not (-180 <= lon <= 180):
        raise ValueError(f"Longitud fuera de rango: {lon}. Debe estar entre -180 y 180")

    # A radianes
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    lat0_rad = math.radians(lat0)
    lon0_rad = math.radians(lon0)
    
    # Convertir a latitud conforme
    chi = geodetic_to_conformal_lat(lat_rad)
    chi0 = geodetic_to_conformal_lat(lat0_rad)

    # Estereográfica Esférica usando Latitud Conforme
    dlon = lon_rad - lon0_rad
    
    denominator = 1 + math.sin(chi0) * math.sin(chi) + \
                  math.cos(chi0) * math.cos(chi) * math.cos(dlon)
                  
    if abs(denominator) < 1e-10:
        raise ValueError(f"Denominador muy pequeño en proyección: {denominator}")

    k = (2 * R) / denominator
    x = k * math.cos(chi) * math.sin(dlon)
    y = k * (math.cos(chi0) * math.sin(chi) -
             math.sin(chi0) * math.cos(chi) * math.cos(dlon))
    return x, y

def calculate_distance_2d(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.sqrt((x2 - x1)**2 + (y2 - y1)**2)

def calculate_distance_to_threshold(lat: float, lon: float,
                                    thr_lat: float, thr_lon: float) -> float:
    x1, y1 = geodetic_to_stereographic(lat, lon)
    x2, y2 = geodetic_to_stereographic(thr_lat, thr_lon)
    return calculate_distance_2d(x1, y1, x2, y2)

def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(lat2_rad)
    x = (math.cos(lat1_rad) * math.sin(lat2_rad) -
         math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon))
    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360) % 360

def conformal_to_geodetic_lat(chi_rad: float, max_iter: int = 20, tol: float = 1e-12) -> float:
    e = _E
    e2 = e * e
    e4 = e2 * e2
    e6 = e4 * e2
    e8 = e4 * e4
    
    c1 = e2/2 + 5*e4/24 + e6/12 + 13*e8/360
    c2 = 7*e4/48 + 29*e6/240 + 811*e8/11520
    c3 = 7*e6/120 + 81*e8/1120
    c4 = 4279*e8/161280
    
    chi = chi_rad
    sin_2chi = math.sin(2 * chi)
    sin_4chi = math.sin(4 * chi)
    sin_6chi = math.sin(6 * chi)
    sin_8chi = math.sin(8 * chi)
    
    lat_rad = chi + c1*sin_2chi + c2*sin_4chi + c3*sin_6chi + c4*sin_8chi
    return lat_rad

def stereographic_to_geodetic(x: float, y: float,
                              lat0: float = _TMA_CENTER_LAT,
                              lon0: float = _TMA_CENTER_LON,
                              R: float = _RADIO_NM) -> Tuple[float, float]:
    lat0_rad = math.radians(lat0)
    lon0_rad = math.radians(lon0)
    chi0 = geodetic_to_conformal_lat(lat0_rad)
    rho = math.sqrt(x**2 + y**2)
    
    if rho < 1e-10:
        return lat0, lon0
    
    c = 2 * math.atan(rho / (2 * R))
    chi = math.asin(math.cos(c) * math.sin(chi0) + (y * math.sin(c) * math.cos(chi0)) / rho)
    lon_rad = lon0_rad + math.atan2(x * math.sin(c), 
                                    rho * math.cos(chi0) * math.cos(c) - y * math.sin(chi0) * math.sin(c))
    
    lat_rad = conformal_to_geodetic_lat(chi)
    return math.degrees(lat_rad), math.degrees(lon_rad)

def latlon_to_xy(lat: Union[float, np.ndarray], lon: Union[float, np.ndarray]) -> Tuple[Union[float, np.ndarray], Union[float, np.ndarray]]:
    if isinstance(lat, (list, np.ndarray)) or isinstance(lon, (list, np.ndarray)):
        lat_arr = np.asarray(lat, dtype=float)
        lon_arr = np.asarray(lon, dtype=float)
        
        lat0_rad = np.radians(_TMA_CENTER_LAT)
        lon0_rad = np.radians(_TMA_CENTER_LON)
        R = _RADIO_NM
        e = _E
        
        lat_rad = np.radians(lat_arr)
        lon_rad = np.radians(lon_arr)
        
        sin_lat = np.sin(lat_rad)
        term1 = ((1 - e * sin_lat) / (1 + e * sin_lat)) ** (e / 2)
        term2 = np.tan(np.pi / 4 + lat_rad / 2)
        chi = 2 * np.arctan(term1 * term2) - np.pi / 2
        
        sin_lat0 = np.sin(lat0_rad)
        term1_0 = ((1 - e * sin_lat0) / (1 + e * sin_lat0)) ** (e / 2)
        term2_0 = np.tan(np.pi / 4 + lat0_rad / 2)
        chi0 = 2 * np.arctan(term1_0 * term2_0) - np.pi / 2
        
        dlon = lon_rad - lon0_rad
        denominator = 1 + np.sin(chi0) * np.sin(chi) + np.cos(chi0) * np.cos(chi) * np.cos(dlon)
        
        k = (2 * R) / denominator
        x_arr = k * np.cos(chi) * np.sin(dlon)
        y_arr = k * (np.cos(chi0) * np.sin(chi) - np.sin(chi0) * np.cos(chi) * np.cos(dlon))
        
        return x_arr, y_arr
    else:
        return geodetic_to_stereographic(lat, lon)

def xy_to_latlon(x: Union[float, np.ndarray], y: Union[float, np.ndarray]) -> Tuple[Union[float, np.ndarray], Union[float, np.ndarray]]:
    if isinstance(x, (list, np.ndarray)) or isinstance(y, (list, np.ndarray)):
        x_arr = np.asarray(x, dtype=float)
        y_arr = np.asarray(y, dtype=float)
        
        lat0_rad = np.radians(_TMA_CENTER_LAT)
        lon0_rad = np.radians(_TMA_CENTER_LON)
        R = _RADIO_NM
        e = _E
        
        sin_lat0 = np.sin(lat0_rad)
        term1_0 = ((1 - e * sin_lat0) / (1 + e * sin_lat0)) ** (e / 2)
        term2_0 = np.tan(np.pi / 4 + lat0_rad / 2)
        chi0 = 2 * np.arctan(term1_0 * term2_0) - np.pi / 2
        
        rho = np.sqrt(x_arr**2 + y_arr**2)
        c = 2 * np.arctan(rho / (2 * R))
        
        chi = np.where(rho < 1e-10,
                       chi0,
                       np.arcsin(np.cos(c) * np.sin(chi0) + (y_arr * np.sin(c) * np.cos(chi0)) / rho))
        
        lon_rad = np.where(rho < 1e-10,
                           lon0_rad,
                           lon0_rad + np.arctan2(x_arr * np.sin(c),
                                                 rho * np.cos(chi0) * np.cos(c) - y_arr * np.sin(chi0) * np.sin(c)))
        
        e2, e4, e6, e8 = e**2, e**4, e**6, e**8
        c1 = e2/2 + 5*e4/24 + e6/12 + 13*e8/360
        c2 = 7*e4/48 + 29*e6/240 + 811*e8/11520
        c3 = 7*e6/120 + 81*e8/1120
        c4 = 4279*e8/161280
        
        lat_rad = chi + c1*np.sin(2*chi) + c2*np.sin(4*chi) + c3*np.sin(6*chi) + c4*np.sin(8*chi)
        return np.degrees(lat_rad), np.degrees(lon_rad)
    else:
        return stereographic_to_geodetic(x, y)