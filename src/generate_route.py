"""
Генерация цифровой модели местности (ЦММ) для маршрута Миасс -> Екатеринбург.

Что делает скрипт:
1. Строит маршрут по реальным дорогам через OSRM API.
2. Интерполирует маршрут до ~10 000 равномерных точек.
3. Запрашивает высоты для каждой точки через Open-Meteo Elevation API.
4. Считает расстояние, уклон, азимут для каждой точки.
5. Генерирует переменную скорость (город / трасса / шум / торможения).
6. Считает время движения.
7. Сохраняет всё в data/route_full.csv (эталон, полный маршрут).

Результат: data/route_full.csv
"""

import csv
import math
import os
import time
from pathlib import Path

import numpy as np
import requests


# ============================================================
# НАСТРОЙКИ (можно менять)
# ============================================================

# Координаты: (широта, долгота)
START = (55.045, 60.108)   # Миасс
END   = (56.850, 60.600)   # Екатеринбург

N_POINTS = 10_000          # сколько точек хотим на полном маршруте
RANDOM_SEED = 42           # фиксируем seed, чтобы результат был воспроизводимым

# Пути
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_FILE = DATA_DIR / "route_full.csv"

# API
OSRM_URL = "http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"
ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"


# ============================================================
# 1. Получение маршрута от OSRM
# ============================================================

def fetch_route_osrm(start, end):
    """
    Запрашивает у OSRM маршрут между двумя точками.
    Возвращает список координат [(lat, lon), ...] и общую длину в метрах.
    """
    url = OSRM_URL.format(
        lat1=start[0], lon1=start[1],
        lat2=end[0],   lon2=end[1],
    )
    params = {
        "overview": "full",       # полная геометрия маршрута
        "geometries": "geojson",  # формат ответа
    }

    print("→ Запрос маршрута к OSRM...")
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM вернул ошибку: {data.get('code')}")

    route = data["routes"][0]
    coords_lonlat = route["geometry"]["coordinates"]  # [[lon, lat], ...]
    total_distance_m = route["distance"]

    # OSRM отдаёт [lon, lat], а нам привычнее [lat, lon]
    coords = [(lat, lon) for lon, lat in coords_lonlat]
    print(f"  ✓ Получено {len(coords)} точек, длина {total_distance_m/1000:.1f} км")
    return coords, total_distance_m


# ============================================================
# 2. Интерполяция до N_POINTS равномерных точек
# ============================================================

def haversine_m(p1, p2):
    """
    Расстояние между двумя точками (lat, lon) в метрах по формуле гаверсинуса.
    """
    R = 6_371_000  # радиус Земли, м
    lat1, lon1 = math.radians(p1[0]), math.radians(p1[1])
    lat2, lon2 = math.radians(p2[0]), math.radians(p2[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def interpolate_route(coords, total_distance_m, n_points):
    """
    Равномерно интерполирует маршрут до n_points точек.
    Идём вдоль ломаной линии, расставляя точки через равные расстояния.
    """
    print(f"→ Интерполяция до {n_points} точек...")

    # 1) Накопленные расстояния между исходными точками OSRM
    seg_lengths = [0.0]
    for i in range(1, len(coords)):
        seg_lengths.append(seg_lengths[-1] + haversine_m(coords[i-1], coords[i]))

    total = seg_lengths[-1]
    # Целевые расстояния от старта для новых точек
    targets = np.linspace(0, total, n_points)

    # 2) Для каждой цели находим, между какими исходными точками она лежит,
    #    и линейно интерполируем координаты
    result = []
    j = 0
    for t in targets:
        while j < len(seg_lengths) - 2 and seg_lengths[j+1] < t:
            j += 1
        # Отрезок от coords[j] до coords[j+1]
        seg_start = seg_lengths[j]
        seg_end = seg_lengths[j+1]
        seg_len = seg_end - seg_start
        frac = 0.0 if seg_len == 0 else (t - seg_start) / seg_len

        lat = coords[j][0] + frac * (coords[j+1][0] - coords[j][0])
        lon = coords[j][1] + frac * (coords[j+1][1] - coords[j][1])
        result.append((lat, lon, t))

    print(f"  ✓ Интерполировано {len(result)} точек")
    return result  # [(lat, lon, distance_m), ...]


# ============================================================
# 3. Получение высот через Open-Meteo Elevation API
# ============================================================

def fetch_elevations(points, batch_size=100, pause=1.5, max_retries=3):
    """
    Запрашивает высоты через Open-Elevation (POST-запрос).
    Если после нескольких попыток не получается — использует синтетический рельеф.

    Open-Elevation принимает POST с JSON вида {"locations": [{"latitude":.., "longitude":..}, ...]}.
    """
    print(f"→ Запрос высот для {len(points)} точек (батчи по {batch_size})...")

    OPEN_ELEVATION_URL = "https://api.open-elevation.com/api/v1/lookup"
    elevations = []
    total_batches = (len(points) + batch_size - 1) // batch_size

    use_synthetic = False  # если API не сработает — переключимся на синтетику

    for i in range(0, len(points), batch_size):
        batch = points[i:i+batch_size]
        locations = [{"latitude": p[0], "longitude": p[1]} for p in batch]

        success = False
        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    OPEN_ELEVATION_URL,
                    json={"locations": locations},
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
                # Open-Elevation возвращает {"results": [{"latitude":.., "longitude":.., "elevation":..}, ...]}
                elevations.extend([r["elevation"] for r in data["results"]])
                success = True
                break
            except Exception as e:
                print(f"  батч {i//batch_size+1}/{total_batches}, попытка {attempt+1} — ошибка: {e}")
                time.sleep(pause * 2)

        if not success:
            print("  ⚠ API высот недоступен. Переключаюсь на синтетический рельеф.")
            use_synthetic = True
            break

        batch_num = i // batch_size + 1
        if batch_num % 10 == 0 or batch_num == total_batches:
            print(f"  батч {batch_num}/{total_batches} — ок")
        time.sleep(pause)

    # Если API так и не ответил — генерируем синтетические высоты
    if use_synthetic:
        print("→ Генерация синтетического рельефа (Урал)...")
        elevations = generate_synthetic_elevation(points)

    print(f"  ✓ Получено {len(elevations)} высот")
    return elevations

def generate_synthetic_elevation(points):
    """
    Синтетический рельеф: гладкие холмы + случайные колебания.
    Высоты в районе 200–500 м (как на Урале).
    """
    rng = np.random.default_rng(42)
    n = len(points)
    # Базовая высота + несколько синусоид разных частот
    base = 300.0
    h = np.full(n, base)
    h += 80 * np.sin(np.linspace(0, 6 * np.pi, n))
    h += 30 * np.sin(np.linspace(0, 20 * np.pi, n))
    h += 10 * rng.normal(0, 1, n)
    h = np.convolve(h, np.ones(20)/20, mode="same")  # сглаживание
    return h.tolist()
# ============================================================
# 4. Расчёт уклона и азимута
# ============================================================

def compute_slope_azimuth(points, elevations):
    """
    Для каждой точки считает уклон (в градусах) и азимут (направление).
    Уклон = arctan(Δh / Δs).
    """
    slopes = [0.0]
    azimuths = [0.0]

    for i in range(1, len(points)):
        lat1, lon1, _ = points[i-1]
        lat2, lon2, _ = points[i]

        # Горизонтальное расстояние между точками
        ds = haversine_m((lat1, lon1), (lat2, lon2))
        # Перепад высот
        dh = elevations[i] - elevations[i-1]

        slope = math.degrees(math.atan2(dh, ds)) if ds > 0 else 0.0

        # Азимут
        dlon = math.radians(lon2 - lon1)
        y = math.sin(dlon) * math.cos(math.radians(lat2))
        x = (math.cos(math.radians(lat1)) * math.sin(math.radians(lat2))
             - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(dlon))
        azimuth = (math.degrees(math.atan2(y, x)) + 360) % 360

        slopes.append(slope)
        azimuths.append(azimuth)

    return slopes, azimuths


# ============================================================
# 5. Генерация переменной скорости
# ============================================================

def generate_speed(points, seed=42):
    """
    Генерирует реалистичную скорость (км/ч) для каждой точки:
    - первые/последние 15 км — городской режим (30-60 км/ч)
    - середина — трасса (80-110 км/ч)
    - плюс шум ±8 км/ч
    - плюс редкие "торможения" до 20-40 км/ч на 1-3 минуты
    """
    print("→ Генерация переменной скорости...")
    rng = np.random.default_rng(seed)
    n = len(points)
    speeds = np.zeros(n)

    total_dist = points[-1][2]
    city_zone = 15_000  # 15 км от старта и до финиша — город

    # Базовая скорость по расстоянию
    for i, (_, _, dist) in enumerate(points):
        if dist < city_zone or dist > total_dist - city_zone:
            base = 45.0   # город
        else:
            base = 95.0   # трасса
        # Плавное изменение базы в зависимости от уклона (в горку медленнее)
        speeds[i] = base

    # Добавляем шум (сглаженный)
    noise = rng.normal(0, 6, n)
    # Простое сглаживание скользящим средним окном 50
    kernel = np.ones(50) / 50
    noise_smooth = np.convolve(noise, kernel, mode="same")
    speeds = speeds + noise_smooth

    # Добавляем редкие торможения
    n_brakes = 8
    for _ in range(n_brakes):
        start_idx = rng.integers(0, n - 500)
        length = rng.integers(200, 500)  # длина "торможения" в точках
        speeds[start_idx:start_idx+length] *= rng.uniform(0.3, 0.6)

    # Ограничиваем разумными рамками
    speeds = np.clip(speeds, 15.0, 120.0)

    print(f"  ✓ Скорость: мин {speeds.min():.0f}, макс {speeds.max():.0f}, средняя {speeds.mean():.0f} км/ч")
    return speeds


# ============================================================
# 6. Расчёт времени
# ============================================================

def compute_time(points, speeds_kmh):
    """
    Время от старта до каждой точки (в секундах).
    Δt = Δs / v.
    """
    times = [0.0]
    for i in range(1, len(points)):
        ds = points[i][2] - points[i-1][2]                 # приращение расстояния, м
        v_ms = max(speeds_kmh[i] / 3.6, 0.1)               # км/ч -> м/с
        dt = ds / v_ms
        times.append(times[-1] + dt)
    return times


# ============================================================
# 7. Сохранение CSV
# ============================================================

def save_csv(points, elevations, slopes, azimuths, speeds, times, path):
    """
    Сохраняет всё в CSV.
    Колонки: point_id, lat, lon, distance_m, elevation_m, slope_deg,
             azimuth_deg, speed_kmh, time_s
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"→ Сохранение в {path}...")

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "point_id", "lat", "lon", "distance_m", "elevation_m",
            "slope_deg", "azimuth_deg", "speed_kmh", "time_s"
        ])
        for i, (lat, lon, dist) in enumerate(points):
            writer.writerow([
                i,
                f"{lat:.6f}",
                f"{lon:.6f}",
                f"{dist:.2f}",
                f"{elevations[i]:.2f}",
                f"{slopes[i]:.4f}",
                f"{azimuths[i]:.2f}",
                f"{speeds[i]:.2f}",
                f"{times[i]:.2f}",
            ])

    print(f"  ✓ Готово: {path}")


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("Генерация маршрута Миасс → Екатеринбург")
    print("=" * 60)

    # 1. Маршрут
    coords, total_dist = fetch_route_osrm(START, END)

    # 2. Интерполяция
    points = interpolate_route(coords, total_dist, N_POINTS)

    # 3. Высоты
    elevations = fetch_elevations(points)

    # 4. Уклон и азимут
    print("→ Расчёт уклонов и азимутов...")
    slopes, azimuths = compute_slope_azimuth(points, elevations)
    print("  ✓ Готово")

    # 5. Скорость
    speeds = generate_speed(points, seed=RANDOM_SEED)

    # 6. Время
    print("→ Расчёт времени...")
    times = compute_time(points, speeds)
    total_time_h = times[-1] / 3600
    print(f"  ✓ Общее время в пути: {total_time_h:.2f} ч")

    # 7. Сохранение
    save_csv(points, elevations, slopes, azimuths, speeds, times, OUTPUT_FILE)

    print("=" * 60)
    print("Готово!")
    print("=" * 60)


if __name__ == "__main__":
    main()