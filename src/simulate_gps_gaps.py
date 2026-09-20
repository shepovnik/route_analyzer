"""
Имитация перебоев GPS-сигнала (финальная версия).

Состав пропусков:
- 2 БОЛЬШИЕ дыры (8-12 мин каждая) — в лесах/горах Урала.
- Много КОРОТКИХ дыр (1-4 мин) — тоннели, мосты, застройка.
- Между ЛЮБЫМИ дырами — запись 3-8 минут (опорные точки).
- Никаких наложений.

Цель: ~20% потерянных точек (2000 из 10000).
В окнах пропуска поля (кроме point_id и distance_m) → NaN.

Результат: data/route.csv
"""

from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# НАСТРОЙКИ
# ============================================================

RANDOM_SEED = 42

SHORT_GAP_MIN = 0.5    # минут
SHORT_GAP_MAX = 1.5

N_BIG_GAPS = 2
BIG_GAP_MIN = 8.0
BIG_GAP_MAX = 12.0

REC_MIN_MIN = 8.0      # запись между дырами
REC_MAX_MIN = 15.0

TARGET_LOSS_FRACTION = 0.20   # цель: 20%

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_FILE = PROJECT_ROOT / "data" / "route_full.csv"
OUTPUT_FILE = PROJECT_ROOT / "data" / "route.csv"

FIELDS_TO_DROP = [
    "lat", "lon", "elevation_m", "slope_deg",
    "azimuth_deg", "speed_kmh", "time_s",
    "vehicle_mass_kg", "cargo_mass_kg",
]


# ============================================================
# Построение маски пропусков (без наложений)
# ============================================================

def build_gap_mask(times, seed=RANDOM_SEED):
    """
    Идём по таймлайну. На каждом шаге:
    1. Записываем 3-8 минут (rec_len).
    2. Решаем, какую дыру сделать — короткую или большую.
       Больших — ровно N_BIG_GAPS, они распределены по маршруту.
    3. Пропускаем дыру (1-4 мин, либо 8-12 мин для большой).
    4. Повторяем, пока не дойдём до конца.

    Никаких наложений: следующая дыра начинается после конца предыдущей.
    """
    rng = np.random.default_rng(seed)
    n = len(times)
    total_time = times[-1]

    # Заранее выберем позиции больших дыр (по времени старта)
    # Распределим их примерно на 30% и 70% маршрута.
    if N_BIG_GAPS > 0:
        big_positions = np.linspace(0.3, 0.7, N_BIG_GAPS) * total_time
        big_lengths = rng.uniform(BIG_GAP_MIN, BIG_GAP_MAX, N_BIG_GAPS) * 60
        big_starts = big_positions - big_lengths / 2
    else:
        big_starts = np.array([])
        big_lengths = np.array([])

    print(f"  Больших дыр: {N_BIG_GAPS}")
    for i in range(N_BIG_GAPS):
        print(f"    №{i+1}: старт ~{big_starts[i]/60:.1f} мин, "
              f"длина {big_lengths[i]/60:.1f} мин")

    big_used = np.zeros(N_BIG_GAPS, dtype=bool)
    is_gap = np.zeros(n, dtype=bool)

    t = 0.0  # текущее время
    short_count = 0

    while t < total_time:
        # 1. Запись
        rec_len = rng.uniform(REC_MIN_MIN, REC_MAX_MIN) * 60
        t += rec_len
        if t >= total_time:
            break

        # 2. Дыра — большая или короткая?
        #    Если текущий момент попал в диапазон большой дыры, которую ещё не использовали — делаем её.
        big_idx = -1
        for i in range(N_BIG_GAPS):
            if not big_used[i] and t >= big_starts[i] - 60:  # допуск ±1 мин
                big_idx = i
                break

        if big_idx >= 0:
            gap_len = big_lengths[big_idx]
            big_used[big_idx] = True
        else:
            gap_len = rng.uniform(SHORT_GAP_MIN, SHORT_GAP_MAX) * 60

        # 3. Помечаем точки в этой дыре
        gap_start = t
        gap_end = t + gap_len
        mask = (times >= gap_start) & (times < gap_end)
        is_gap |= mask

        if big_idx < 0 and mask.any():
            short_count += 1

        t = gap_end

    print(f"  Коротких дыр: {short_count}")
    return is_gap


def apply_gaps(df, fields_to_drop=FIELDS_TO_DROP):
    """Заменяет поля на NaN в мёртвых зонах."""
    df = df.copy()
    gap_mask = df["is_gap"]

    for col in fields_to_drop:
        if col in df.columns:
            df.loc[gap_mask, col] = np.nan

    df = df.drop(columns=["is_gap"])
    return df


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("Имитация перебоев GPS (финальная схема)")
    print("=" * 60)

    print(f"→ Чтение {INPUT_FILE}...")
    df = pd.read_csv(INPUT_FILE)
    print(f"  ✓ Загружено {len(df)} строк")

    times = df["time_s"].values
    print(f"  Время в пути: {times[-1]/60:.1f} мин")

    print(f"→ Генерация мёртвых зон...")
    is_gap = build_gap_mask(times)
    df["is_gap"] = is_gap

    n_gap = is_gap.sum()
    print(f"  ✓ Точек в мёртвых зонах: {n_gap} из {len(df)} ({100*n_gap/len(df):.1f}%)")

    if abs(n_gap / len(df) - TARGET_LOSS_FRACTION) > 0.05:
        print(f"  ⚠ Целевая доля {100*TARGET_LOSS_FRACTION:.0f}%, "
              f"получилось {100*n_gap/len(df):.1f}%.")

    print(f"→ Замена полей на NaN в мёртвых зонах...")
    df = apply_gaps(df)
    print(f"  ✓ Готово")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    print(f"→ Сохранение в {OUTPUT_FILE}...")
    df.to_csv(OUTPUT_FILE, index=False, float_format="%.4f")
    print(f"  ✓ Готово")

    print("\nСтатистика по файлу с пропусками:")
    print(df.describe().round(2))

    print("=" * 60)
    print("Готово!")
    print("=" * 60)


if __name__ == "__main__":
    main()