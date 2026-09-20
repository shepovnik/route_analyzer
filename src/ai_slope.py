"""
ИИ-модель предсказания уклона (пункт ***).

Режимы обучения (переключатель TRAIN_SOURCE):
- "gappy"    — обучаемся на записанных точках из route.csv (без пропусков).
               Так система работает "в реальности" — только с тем, что пришло с датчиков.
- "restored" — обучаемся на всех 10 000 точках из route_restored.csv.

В любом случае:
- Предсказание делается для всех 10 000 точек.
- Метрики качества считаются на эталоне route_full.csv.

Добавляет в route_restored.csv колонки:
- slope_predicted_deg — предсказанный уклон в точке i (по 20 предыдущим)
- slope_predicted_next_deg — прогноз уклона в точке i+1
"""

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error


# ============================================================
# НАСТРОЙКИ
# ============================================================

TRAIN_SOURCE = "gappy"   # "gappy" (на дырявых) или "restored" (на восстановленных)
#TRAIN_SOURCE = "restored"   # "gappy" (на дырявых) или "restored" (на восстановленных)

WINDOW = 20              # размер скользящего окна
TRAIN_FRACTION = 0.8     # для режима "restored": первые 80% — train

GB_PARAMS = {
    "n_estimators": 200,
    "max_depth": 4,
    "learning_rate": 0.05,
    "random_state": 42,
}

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GAPPY_FILE = PROJECT_ROOT / "data" / "route.csv"
RESTORED_FILE = PROJECT_ROOT / "data" / "route_restored.csv"
FULL_FILE = PROJECT_ROOT / "data" / "route_full.csv"
METRICS_FILE = PROJECT_ROOT / "data" / "slope_metrics.csv"


# ============================================================
# Признаки
# ============================================================

def build_sliding_window(values, window):
    """X: (n-window, window), y: (n-window,), idx: исходные индексы."""
    n = len(values)
    X = np.zeros((n - window, window))
    y = np.zeros(n - window)
    idx = np.arange(window, n)

    for k in range(n - window):
        i = window + k
        X[k] = values[i - window:i]
        y[k] = values[i]

    return X, y, idx


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print(f"ИИ-предсказание уклона (GradientBoosting, окно {WINDOW})")
    print(f"Режим обучения: {TRAIN_SOURCE}")
    print("=" * 70)

    # 1. Эталон (нужен всегда — для оценки)
    print(f"→ Чтение эталона {FULL_FILE.name}...")
    full_df = pd.read_csv(FULL_FILE)

    # 2. Данные для обучения + восстановленный файл (куда писать предсказание)
    print(f"→ Чтение {RESTORED_FILE.name} (для записи предсказания)...")
    restored_df = pd.read_csv(RESTORED_FILE)

    if TRAIN_SOURCE == "gappy":
        print(f"→ Чтение дырявого {GAPPY_FILE.name} (для обучения)...")
        train_df = pd.read_csv(GAPPY_FILE)
        # Только записанные точки (где уклон известен)
        mask_known = train_df["slope_deg"].notna()
        slopes_for_train = train_df.loc[mask_known, "slope_deg"].values
        print(f"  ✓ Из {len(train_df)} строк доступно для обучения: {mask_known.sum()}")

        # Признаки строим на последовательных записанных точках
        X, y, idx_rel = build_sliding_window(slopes_for_train, WINDOW)
        # idx_rel — индексы внутри массива slopes_for_train. Чтобы понять,
        # на какие строки restored_df они соответствуют, нам нужно
        # знать исходные индексы в train_df:
        known_indices = np.where(mask_known)[0]
        idx_abs = known_indices[idx_rel]  # исходные индексы в train_df (== в restored_df)

        print(f"  ✓ Сформировано {len(X)} примеров для обучения")
    else:  # "restored"
        print(f"→ Используем все точки {RESTORED_FILE.name} для обучения...")
        slopes_for_train = restored_df["slope_deg"].values
        X, y, idx_rel = build_sliding_window(slopes_for_train, WINDOW)
        idx_abs = idx_rel  # индексы в restored_df совпадают
        print(f"  ✓ Сформировано {len(X)} примеров")

    # 3. Обучение
    print(f"→ Обучение GradientBoosting...")
    model = GradientBoostingRegressor(**GB_PARAMS)

    if TRAIN_SOURCE == "gappy":
        # Обучение на всех доступных примерах, оценка — на пропущенных точках
        model.fit(X, y)
        y_pred_train = model.predict(X)
        train_mae = mean_absolute_error(y, y_pred_train)
        train_rmse = np.sqrt(mean_squared_error(y, y_pred_train))

        # Оценка на пропущенных точках (test)
        gap_mask_full = full_df["slope_deg"].values  # для формы
        gap_in_gappy = ~pd.read_csv(GAPPY_FILE)["slope_deg"].notna().values  # True = пропуск
        gap_indices = np.where(gap_in_gappy)[0]

        # Для этих индексов нужны предсказания — получим их, предсказав для всех точек
        # (см. шаг 5). Пока просто считаем train MAE.
        test_mae = np.nan
        test_rmse = np.nan
    else:  # restored
        split = int(len(X) * TRAIN_FRACTION)
        X_train, y_train = X[:split], y[:split]
        X_test, y_test = X[split:], y[split:]
        print(f"→ Train: {len(X_train)}, Test: {len(X_test)}")

        model.fit(X_train, y_train)
        y_pred_train = model.predict(X_train)
        y_pred_test = model.predict(X_test)
        train_mae = mean_absolute_error(y_train, y_pred_train)
        train_rmse = np.sqrt(mean_squared_error(y_train, y_pred_train))
        test_mae = mean_absolute_error(y_test, y_pred_test)
        test_rmse = np.sqrt(mean_squared_error(y_test, y_pred_test))

    print(f"\n  Метрики:")
    print(f"    Train MAE: {train_mae:.4f}°, RMSE: {train_rmse:.4f}°")
    if not np.isnan(test_mae):
        print(f"    Test  MAE: {test_mae:.4f}°, RMSE: {test_rmse:.4f}°")

    # 4. Предсказание для ВСЕХ 10 000 точек restored_df
    print(f"\n→ Предсказание уклона для всех {len(restored_df)} точек...")
    # Строим скользящее окно по всем точкам restored_df
    slopes_all = restored_df["slope_deg"].values
    X_all, _, idx_all = build_sliding_window(slopes_all, WINDOW)
    y_pred_all = model.predict(X_all)

    # 5. Записываем в restored_df
    restored_df["slope_predicted_deg"] = np.nan
    restored_df["slope_predicted_next_deg"] = np.nan
    restored_df.loc[idx_all, "slope_predicted_deg"] = y_pred_all

    # Заполняем первые WINDOW точек значением из первой доступной
    restored_df["slope_predicted_deg"] = restored_df["slope_predicted_deg"].bfill()

    # Сдвиг на 1 вперёд — прогноз следующей точки
    restored_df["slope_predicted_next_deg"] = restored_df["slope_predicted_deg"].shift(-1).bfill()

    # 6. Оценка на пропущенных точках (для режима "gappy")
    if TRAIN_SOURCE == "gappy":
        print(f"\n→ Оценка на пропущенных точках (сравнение с эталоном)...")
        gappy_df = pd.read_csv(GAPPY_FILE)
        gap_mask = gappy_df["slope_deg"].isna().values
        y_true_gap = full_df.loc[gap_mask, "slope_deg"].values
        y_pred_gap = restored_df.loc[gap_mask, "slope_predicted_deg"].values

        test_mae = mean_absolute_error(y_true_gap, y_pred_gap)
        test_rmse = np.sqrt(mean_squared_error(y_true_gap, y_pred_gap))
        print(f"    Test (на пропусках) MAE: {test_mae:.4f}°, RMSE: {test_rmse:.4f}°")

    # 7. Корреляция
    corr = restored_df[["slope_deg", "slope_predicted_deg"]].corr().iloc[0, 1]
    print(f"\n→ Correlation (реальный vs предсказанный уклон): {corr:.4f}")

    # 8. Сохранение
    print(f"\n→ Сохранение в {RESTORED_FILE.name}...")
    restored_df.to_csv(RESTORED_FILE, index=False, float_format="%.4f")
    print(f"  ✓ Готово")

    # 9. Метрики
    metrics_rows = [
        {"mode": TRAIN_SOURCE, "split": "train", "mae": train_mae,
         "rmse": train_rmse, "n": len(X)},
    ]
    if not np.isnan(test_mae):
        metrics_rows.append({
            "mode": TRAIN_SOURCE, "split": "test",
            "mae": test_mae, "rmse": test_rmse, "n": -1,
        })

    metrics_df = pd.DataFrame(metrics_rows)

    # Если файл уже есть — добавляем строки
    if METRICS_FILE.exists():
        old = pd.read_csv(METRICS_FILE)
        # Удаляем старые строки с тем же режимом
        old = old[old["mode"] != TRAIN_SOURCE]
        metrics_df = pd.concat([old, metrics_df], ignore_index=True)

    metrics_df.to_csv(METRICS_FILE, index=False, float_format="%.6f")
    print(f"→ Метрики сохранены в {METRICS_FILE.name}")

    print("=" * 70)
    print("Готово!")
    print("=" * 70)


if __name__ == "__main__":
    main()