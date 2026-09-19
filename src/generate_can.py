"""
Добавление CAN-данных (масс) в файл route.csv.

Что делает:
1. Читает data/route.csv (ЦММ с пропусками + скорость + время).
2. Добавляет колонку vehicle_mass_kg — масса ТС с учётом сгорания топлива.
3. Добавляет колонку cargo_mass_kg — масса груза (константа).
4. В окнах пропуска GPS (там где speed_kmh = NaN) ставит NaN и в массах.
5. Перезаписывает data/route.csv.

Результат: data/route.csv с полным набором полей ЦММ + CAN.
"""

from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# НАСТРОЙКИ
# ============================================================

# Массы, кг
VEHICLE_DRY_MASS_KG = 8000.0   # снаряжённая масса ТС (без топлива)
FUEL_MASS_START_KG  = 500.0    # топливо в начале маршрута
CARGO_MASS_KG       = 12000.0  # масса груза (константа)

# Расход топлива (упрощённо) — сколько кг топлива сгорает на 1 км
# 25 л/100 км * 0.85 кг/л = ~21.25 кг/100 км = 0.2125 кг/км
FUEL_BURN_KG_PER_KM = 0.2125

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_FILE = PROJECT_ROOT / "data" / "route.csv"
OUTPUT_FILE = PROJECT_ROOT / "data" / "route.csv"


# ============================================================
# Основная логика
# ============================================================

def add_can_data(df):
    """
    Добавляет колонки vehicle_mass_kg и cargo_mass_kg.
    Пропуски (NaN) ставит там же, где пропуски в speed_kmh.
    """
    df = df.copy()

    # 1. Масса ТС = сухая масса + остаток топлива
    #    Топливо убывает линейно по пройденному расстоянию
    dist_km = df["distance_m"] / 1000.0
    fuel_remaining = FUEL_MASS_START_KG - dist_km * FUEL_BURN_KG_PER_KM
    fuel_remaining = np.clip(fuel_remaining, 0, None)  # не даём уйти в минус

    vehicle_mass = VEHICLE_DRY_MASS_KG + fuel_remaining
    df["vehicle_mass_kg"] = vehicle_mass

    # 2. Масса груза — константа
    df["cargo_mass_kg"] = CARGO_MASS_KG

    # 3. Ставим NaN там, где пропуск GPS (speed_kmh = NaN)
    gap_mask = df["speed_kmh"].isna()
    df.loc[gap_mask, "vehicle_mass_kg"] = np.nan
    df.loc[gap_mask, "cargo_mass_kg"] = np.nan

    print(f"  ✓ Добавлены колонки vehicle_mass_kg и cargo_mass_kg")
    print(f"    vehicle_mass_kg: {vehicle_mass.min():.0f}–{vehicle_mass.max():.0f} кг")
    print(f"    cargo_mass_kg:   {CARGO_MASS_KG:.0f} кг (константа)")
    print(f"    Пропусков в массах: {gap_mask.sum()}")

    return df


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("Добавление CAN-данных (массы ТС и груза)")
    print("=" * 60)

    print(f"→ Чтение {INPUT_FILE}...")
    df = pd.read_csv(INPUT_FILE)
    print(f"  ✓ Загружено {len(df)} строк, {len(df.columns)} колонок")

    # Добавляем CAN
    df = add_can_data(df)

    # Сохраняем
    print(f"→ Сохранение в {OUTPUT_FILE}...")
    df.to_csv(OUTPUT_FILE, index=False, float_format="%.4f")
    print(f"  ✓ Готово")

    print("\nИтоговые колонки файла:")
    print(list(df.columns))

    print("\nСтатистика по новым колонкам:")
    print(df[["vehicle_mass_kg", "cargo_mass_kg"]].describe().round(2))

    print("=" * 60)
    print("Готово!")
    print("=" * 60)


if __name__ == "__main__":
    main()