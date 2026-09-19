"""
Постобработка route_full.csv:
1. Чистка выбросов высот (артефакты Open-Elevation).
2. Добавление синтетических холмов (маршрут "условный", рельеф оживляем).
3. Пересчёт уклона по сглаженным высотам — без ступенек и выбросов.

Перезаписывает data/route_full.csv.
"""

from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# НАСТРОЙКИ
# ============================================================

# Чистка выбросов
MEDIAN_WINDOW = 5         # окно для медианного фильтра (в точках)
OUTLIER_THRESHOLD_M = 15  # если высота отличается от медианы окна больше чем на это — выброс

# Синтетические холмы
HILLS = [
    # (амплитуда_м, период_м, фаза_рад)
    (20.0, 8000.0, 0.0),
    (12.0, 3500.0, 1.3),
    (6.0,  1200.0, 2.7),
]

# Сглаживание уклона
SLOPE_WINDOW = 10         # уклон считается по разнице высот на расстоянии 2*SLOPE_WINDOW точек

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_FILE = PROJECT_ROOT / "data" / "route_full.csv"
OUTPUT_FILE = PROJECT_ROOT / "data" / "route_full.csv"


# ============================================================
# 1. Чистка выбросов высот
# ============================================================

def clean_elevation_outliers(df, window=MEDIAN_WINDOW, threshold=OUTLIER_THRESHOLD_M):
    """
    Заменяет выбросы высот на медиану локального окна.
    """
    print(f"→ Чистка выбросов высот (окно {window}, порог {threshold} м)...")
    elev = df["elevation_m"].values.copy()
    n = len(elev)

    # Медианный фильтр
    median_filtered = np.copy(elev)
    for i in range(n):
        lo = max(0, i - window)
        hi = min(n, i + window + 1)
        median_filtered[i] = np.median(elev[lo:hi])

    # Где отклонение от медианы больше порога — там выброс
    diff = np.abs(elev - median_filtered)
    outliers = diff > threshold
    n_out = outliers.sum()

    elev[outliers] = median_filtered[outliers]
    print(f"  ✓ Найдено выбросов: {n_out} ({100*n_out/n:.2f}%)")

    df = df.copy()
    df["elevation_m"] = elev
    return df


# ============================================================
# 2. Добавление синтетических холмов
# ============================================================

def add_synthetic_hills(df, hills=HILLS):
    """
    Накладывает поверх реального рельефа сумму синусоид.
    """
    print(f"→ Добавление синтетических холмов ({len(hills)} компонент)...")
    dist = df["distance_m"].values
    hills_signal = np.zeros_like(dist)

    for amp, period, phase in hills:
        hills_signal += amp * np.sin(2 * np.pi * dist / period + phase)

    df = df.copy()
    df["elevation_m"] = df["elevation_m"] + hills_signal

    print(f"  ✓ Размах холмов: ±{np.abs(hills_signal).max():.1f} м")
    return df


# ============================================================
# 3. Пересчёт уклона (сглаженный)
# ============================================================

def recompute_slope(df, window=SLOPE_WINDOW):
    """
    Уклон считаем по разнице высот на окне ±window точек,
    делённой на горизонтальное расстояние между этими точками.
    Так уклон получается плавным (без ступенек и выбросов).
    """
    print(f"→ Пересчёт уклона (окно ±{window} точек)...")
    elev = df["elevation_m"].values
    dist = df["distance_m"].values
    n = len(elev)

    slope = np.zeros(n)
    for i in range(n):
        lo = max(0, i - window)
        hi = min(n - 1, i + window)
        dh = elev[hi] - elev[lo]
        ds = dist[hi] - dist[lo]
        slope[i] = np.degrees(np.arctan2(dh, ds)) if ds > 0 else 0.0

    df = df.copy()
    df["slope_deg"] = slope

    print(f"  ✓ Уклон: мин {slope.min():.2f}°, макс {slope.max():.2f}°, "
          f"среднее {slope.mean():.2f}°")
    return df


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("Постобработка route_full.csv")
    print("=" * 60)

    print(f"→ Чтение {INPUT_FILE}...")
    df = pd.read_csv(INPUT_FILE)
    print(f"  ✓ Загружено {len(df)} строк")

    df = clean_elevation_outliers(df) # 1. Чистка выбросов
    df = add_synthetic_hills(df) # 2. Холмы
    df = recompute_slope(df) # 3. Уклон

    print(f"→ Сохранение в {OUTPUT_FILE}...") # 4. Сохранение
    df.to_csv(OUTPUT_FILE, index=False, float_format="%.4f")
    print(f"  ✓ Готово")

    print("\nНовая статистика:")
    print(df[["elevation_m", "slope_deg"]].describe().round(2))

    print("=" * 60)
    print("Готово!")
    print("=" * 60)


if __name__ == "__main__":
    main()