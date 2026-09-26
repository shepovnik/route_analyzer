"""
Модель расхода топлива и адаптивной оптимальной скорости.

Формула расхода (физическая модель):
    Q(v, m, α) = a + b·v + c·v² + d·m·sin(α)·v     [л/ч]
    q(v, m, α) = Q / v = a/v + b + c·v + d·m·sin(α) [л/км]

Обоснование компонент:
    a — расход на холостом ходу.
    b·v — трение качения (линейно от скорости).
    c·v² — аэродинамика (квадратично от скорости).
    d·m·sin(α)·v — работа против гравитации (от массы, уклона и скорости).

Оптимальная скорость (минимум q по v):
    q'(v) = -a/v² + c = 0  →  v_base = √(a/c)

Адаптация оптимальной скорости:
    v_optimal = v_base - k·sin(α) - k·predicted_slope
    На подъёме — медленнее, на спуске — быстрее, перед подъёмом — готовимся заранее.
    predicted_slope — прогноз уклона от ИИ-модели (колонка slope_predicted_next_deg).

Добавляет колонки:
    fuel_rate_lph, fuel_rate_lpkm, fuel_rate_lp100km,
    v_base_kmh, v_optimal_kmh (адаптивная)
"""

from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# КОЭФФИЦИЕНТЫ МОДЕЛИ
# ============================================================

COEFF_A = 4.0        # л/ч (холостой ход)
COEFF_B = 0.10       # л/(ч·км/ч) (качение)
COEFF_C = 0.0007     # л/(ч·(км/ч)²) (аэродинамика)
COEFF_D = 2.2e-5     # л/(ч·кг) (уклон)

# Коэффициент адаптации скорости
K_SLOPE = 100.0      # км/ч на единицу sin(α) — на уклоне ±3° сдвиг ~±10 км/ч
K_AI = 30.0         # км/ч на градус прогноза уклона

# Границы скорости (реалистичные для грузовика)
V_MIN_KMH = 25.0
V_MAX_KMH = 100.0


# ============================================================
# ФОРМУЛЫ РАСХОДА
# ============================================================

def fuel_rate_lph(v_kmh, m_kg, slope_deg):
    """Расход в л/ч."""
    v = np.asarray(v_kmh, dtype=float)
    m = np.asarray(m_kg, dtype=float)
    alpha = np.radians(np.asarray(slope_deg, dtype=float))

    Q = (COEFF_A
         + COEFF_B * v
         + COEFF_C * v**2
         + COEFF_D * m * np.sin(alpha) * v)
    return np.maximum(Q, 0.5)


def fuel_rate_lpkm(v_kmh, m_kg, slope_deg):
    """Расход в л/км."""
    v = np.asarray(v_kmh, dtype=float)
    m = np.asarray(m_kg, dtype=float)
    alpha = np.radians(np.asarray(slope_deg, dtype=float))
    v_safe = np.maximum(v, 1.0)

    q = (COEFF_A / v_safe
         + COEFF_B
         + COEFF_C * v_safe
         + COEFF_D * m * np.sin(alpha))
    return np.maximum(q, 0.01)


def v_base_kmh():
    """Базовая оптимальная скорость из аналитической формулы v = √(a/c)."""
    return np.sqrt(COEFF_A / COEFF_C)


def v_optimal_adaptive(slope_deg, predicted_slope_deg):
    """
    Адаптивная оптимальная скорость:
    - учитывает текущий уклон (sin),
    - учитывает прогноз уклона от ИИ.
    Результат ограничен разумными рамками.
    """
    slope = np.asarray(slope_deg, dtype=float)
    pred = np.asarray(predicted_slope_deg, dtype=float)

    v_base = v_base_kmh()
    v = v_base - K_SLOPE * np.sin(np.radians(slope)) - K_AI * pred / 10.0

    return np.clip(v, V_MIN_KMH, V_MAX_KMH)


# ============================================================
# MAIN
# ============================================================

def add_fuel_columns(df):
    df = df.copy()
    v = df["speed_kmh"].values
    m = (df["vehicle_mass_kg"] + df["cargo_mass_kg"]).values
    alpha = df["slope_deg"].values

    df["fuel_rate_lph"] = fuel_rate_lph(v, m, alpha)
    df["fuel_rate_lpkm"] = fuel_rate_lpkm(v, m, alpha)
    df["fuel_rate_lp100km"] = df["fuel_rate_lpkm"] * 100

    df["v_base_kmh"] = v_base_kmh()

    # Адаптивная скорость — нужна колонка прогноза
    if "slope_predicted_next_deg" in df.columns:
        pred = df["slope_predicted_next_deg"].values
    else:
        pred = np.zeros(len(df))
        print("  ⚠ Колонка slope_predicted_next_deg не найдена — берём 0")
    df["v_optimal_kmh"] = df["v_optimal_kmh"].rolling(window=100, center=True, min_periods=1).mean()

    return df


def main():
    print("=" * 60)
    print("Модель расхода + адаптивная оптимальная скорость")
    print("=" * 60)

    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    INPUT = PROJECT_ROOT / "data" / "route_restored.csv"
    OUTPUT = PROJECT_ROOT / "data" / "route_restored.csv"

    print(f"→ Чтение {INPUT.name}...")
    df = pd.read_csv(INPUT)
    print(f"  ✓ {len(df)} строк")

    print(f"→ Базовая оптимальная скорость: {v_base_kmh():.1f} км/ч")

    print(f"→ Расчёт расхода и адаптивной скорости...")
    df = add_fuel_columns(df)

    print(f"  ✓ Расход л/100 км: "
          f"мин {df['fuel_rate_lp100km'].min():.1f}, "
          f"сред {df['fuel_rate_lp100km'].mean():.1f}, "
          f"макс {df['fuel_rate_lp100km'].max():.1f}")

    print(f"  ✓ v_optimal_kmh: "
          f"мин {df['v_optimal_kmh'].min():.1f}, "
          f"сред {df['v_optimal_kmh'].mean():.1f}, "
          f"макс {df['v_optimal_kmh'].max():.1f}")

    print(f"→ Сохранение в {OUTPUT.name}...")
    df.to_csv(OUTPUT, index=False, float_format="%.4f")
    print(f"  ✓ Готово")

    print("=" * 60)
    print("Готово!")
    print("=" * 60)


if __name__ == "__main__":
    main()