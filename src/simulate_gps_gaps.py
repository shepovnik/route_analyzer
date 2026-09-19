"""
Имитация перебоев GPS-сигнала.

Берём полный маршрут (route_full.csv) и "вырезаем" из него окна,
как будто в эти периоды GPS-приёмник терял сигнал.

Схема окон (по времени в пути):
    30 мин — запись идёт
    10 мин — пропуск (мёртвая зона)
    30 мин — запись
    10 мин — пропуск
    ...

В окнах пропуска значения всех полей, кроме point_id и distance_m,
заменяются на NaN — их потом будет восстанавливать ИИ.

Результат: data/route.csv
"""

from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# НАСТРОЙКИ
# ============================================================

RECORD_MIN = 30   # минут записи
GAP_MIN = 10      # минут пропуска

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_FILE = PROJECT_ROOT / "data" / "route_full.csv"
OUTPUT_FILE = PROJECT_ROOT / "data" / "route.csv"

# Какие поля "теряются" при пропадании GPS
FIELDS_TO_DROP = [
    "lat", "lon", "elevation_m", "slope_deg",
    "azimuth_deg", "speed_kmh", "time_s",
]


# ============================================================
# Основная логика
# ============================================================

def mark_gaps(df, record_min=RECORD_MIN, gap_min=GAP_MIN):
    """
    Помечает строки как "пропуск", если время точки попадает в мёртвую зону.
    Возвращает DataFrame с добавленной колонкой is_gap (True/False).
    """
    print(f"→ Разметка окон: {record_min} мин запись / {gap_min} мин пропуск")

    period_s = (record_min + gap_min) * 60  # длина одного цикла в секундах

    # Время точки в секундах
    times = df["time_s"].values
    # Позиция внутри цикла: [0, record_min*60) — запись; [record_min*60, period_s) — пропуск
    pos_in_cycle = times % period_s

    is_gap = pos_in_cycle >= record_min * 60

    df = df.copy()
    df["is_gap"] = is_gap

    n_gap = is_gap.sum()
    print(f"  ✓ Точек в мёртвых зонах: {n_gap} из {len(df)} ({100*n_gap/len(df):.1f}%)")
    return df


def apply_gaps(df, fields_to_drop=FIELDS_TO_DROP):
    """
    В строках, где is_gap=True, заменяет указанные поля на NaN.
    Колонку is_gap затем удаляет (она была служебной).
    """
    print(f"→ Замена полей на NaN в мёртвых зонах...")
    df = df.copy()
    gap_mask = df["is_gap"]

    for col in fields_to_drop:
        if col in df.columns:
            df.loc[gap_mask, col] = np.nan

    df = df.drop(columns=["is_gap"])
    print(f"  ✓ Готово")
    return df


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("Имитация перебоев GPS")
    print("=" * 60)

    print(f"→ Чтение {INPUT_FILE}...")
    df = pd.read_csv(INPUT_FILE)
    print(f"  ✓ Загружено {len(df)} строк")

    # 1. Разметка
    df = mark_gaps(df)

    # 2. Замена на NaN
    df = apply_gaps(df)

    # 3. Сохранение
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    print(f"→ Сохранение в {OUTPUT_FILE}...")
    df.to_csv(OUTPUT_FILE, index=False, float_format="%.4f")
    print(f"  ✓ Готово")

    # 4. Краткая статистика
    print("\nСтатистика по файлу с пропусками:")
    print(df.describe().round(2))

    print("=" * 60)
    print("Готово!")
    print("=" * 60)


if __name__ == "__main__":
    main()