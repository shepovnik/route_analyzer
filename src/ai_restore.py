"""
ИИ-восстановление пропущенных данных GPS/CAN.

Стратегия по полям:
- Гладкие простые поля (lat, time_s, vehicle_mass_kg, cargo_mass_kg) —
  линейная интерполяция.
- Сложные поля (lon, elevation_m, slope_deg, speed_kmh) —
  RandomForest с лагами/лидами.
- Азимут (azimuth_deg) — специальный метод: раскладываем на sin и cos,
  предсказываем их отдельно, собираем обратно через atan2.
  Это правильно для циклических величин (0°=360°).

Модель обучается ТОЛЬКО на записанных точках, эталон — только для проверки.
"""

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error


# ============================================================
# НАСТРОЙКИ
# ============================================================

FEATURE = "distance_m"
N_LAGS = 10

INTERP_FIELDS = ["lat", "time_s", "vehicle_mass_kg", "cargo_mass_kg"]
ML_FIELDS = ["lon", "elevation_m", "slope_deg", "speed_kmh"]
ANGLE_FIELDS = ["azimuth_deg"]  # специальная обработка через sin/cos

ALL_FIELDS = INTERP_FIELDS + ML_FIELDS + ANGLE_FIELDS

RF_PARAMS = {
    "n_estimators": 150,
    "max_depth": 20,
    "random_state": 42,
    "n_jobs": -1,
}

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GAPPY_FILE = PROJECT_ROOT / "data" / "route.csv"
FULL_FILE = PROJECT_ROOT / "data" / "route_full.csv"
OUTPUT_FILE = PROJECT_ROOT / "data" / "route_restored.csv"
METRICS_FILE = PROJECT_ROOT / "data" / "restore_metrics.csv"


# ============================================================
# Признаки с лагами/лидами
# ============================================================

def build_lag_lead_features(values, known_mask, n_lags=N_LAGS):
    """Лаги и лиды по значениям поля."""
    n = len(values)
    known_idx = np.where(known_mask)[0]
    pos = np.searchsorted(known_idx, np.arange(n), side="right")

    features = np.zeros((n, 2 * n_lags))
    for k in range(n_lags):
        left_pos = np.clip(pos - 1 - k, 0, len(known_idx) - 1)
        features[:, k] = values[known_idx[left_pos]]

        right_pos = np.clip(pos + k, 0, len(known_idx) - 1)
        features[:, n_lags + k] = values[known_idx[right_pos]]
    return features


# ============================================================
# Методы восстановления
# ============================================================

def restore_by_interpolation(df, target):
    x_all = df[FEATURE].values
    y_all = df[target].values
    mask_known = ~np.isnan(y_all)
    mask_unknown = np.isnan(y_all)
    if mask_unknown.sum() == 0:
        return np.array([])
    return np.interp(x_all[mask_unknown], x_all[mask_known], y_all[mask_known])


def restore_by_ml_with_lags(df, target, params=RF_PARAMS):
    y_all = df[target].values
    mask_known = ~np.isnan(y_all)
    mask_unknown = np.isnan(y_all)
    if mask_unknown.sum() == 0:
        return np.array([])

    x_dist = df[[FEATURE]].values
    x_lags = build_lag_lead_features(y_all, mask_known, N_LAGS)
    X_all = np.hstack([x_dist, x_lags])

    model = RandomForestRegressor(**params)
    model.fit(X_all[mask_known], y_all[mask_known])
    return model.predict(X_all[mask_unknown])


def restore_angle_by_sin_cos(df, target_deg, params=RF_PARAMS):
    """
    Азимут: раскладываем на sin/cos, учим две модели, собираем обратно atan2.
    """
    y_deg = df[target_deg].values
    mask_known = ~np.isnan(y_deg)
    mask_unknown = np.isnan(y_deg)

    if mask_unknown.sum() == 0:
        return np.array([])

    # Перевод в радианы
    y_rad = np.radians(y_deg)

    # Цели: sin и cos
    y_sin = np.sin(y_rad)
    y_cos = np.cos(y_rad)

    # Признаки: distance + лаги/лиды по sin и cos (не по углу!)
    x_dist = df[[FEATURE]].values
    # ВАЖНО: лаги строим по sin и cos, а не по градусам
    mask_sin_known = mask_known  # sin известен там же, где угол
    x_lags_sin = build_lag_lead_features(y_sin, mask_sin_known, N_LAGS)
    x_lags_cos = build_lag_lead_features(y_cos, mask_sin_known, N_LAGS)

    X_all = np.hstack([x_dist, x_lags_sin, x_lags_cos])

    # Две модели
    model_sin = RandomForestRegressor(**params)
    model_cos = RandomForestRegressor(**params)
    model_sin.fit(X_all[mask_known], y_sin[mask_known])
    model_cos.fit(X_all[mask_known], y_cos[mask_known])

    sin_pred = model_sin.predict(X_all[mask_unknown])
    cos_pred = model_cos.predict(X_all[mask_unknown])

    # Собираем обратно в углы
    angle_rad = np.arctan2(sin_pred, cos_pred)
    angle_deg = (np.degrees(angle_rad) + 360) % 360
    return angle_deg


# ============================================================
# Общий цикл
# ============================================================

def train_and_restore(gappy_df, full_df):
    restored = gappy_df.copy()
    metrics = []

    print(f"{'Поле':<18} {'Метод':<24} {'MAE':>10} {'RMSE':>10} {'Пропусков':>10}")
    print("-" * 78)

    for target in ALL_FIELDS:
        if target in INTERP_FIELDS:
            method = "интерполяция"
            y_pred = restore_by_interpolation(gappy_df, target)
        elif target in ANGLE_FIELDS:
            method = "RF (sin/cos)"
            y_pred = restore_angle_by_sin_cos(gappy_df, target)
        else:
            method = f"RF + лаги (N={N_LAGS})"
            y_pred = restore_by_ml_with_lags(gappy_df, target)

        mask_predict = gappy_df[target].isna()
        n_predict = mask_predict.sum()
        if n_predict == 0:
            continue

        restored.loc[mask_predict, target] = y_pred

        y_true = full_df.loc[mask_predict, target].values
        mae = mean_absolute_error(y_true, y_pred)
        rmse = np.sqrt(mean_squared_error(y_true, y_pred))

        # Для углов MAE может быть неадекватной (0°≈360°), добавим циклическую MAE
        if target in ANGLE_FIELDS:
            diff = np.abs(y_true - y_pred)
            circ_diff = np.minimum(diff, 360 - diff)
            circ_mae = circ_diff.mean()
            metrics.append({
                "field": target, "method": method,
                "mae": mae, "rmse": rmse,
                "cyclic_mae": circ_mae,
                "n_predict": n_predict,
            })
            print(f"{target:<18} {method:<24} {mae:>10.4f} {rmse:>10.4f} {n_predict:>10}")
            print(f"{'':<18} {'циклическая MAE:':<24} {circ_mae:>10.4f}")
        else:
            metrics.append({
                "field": target, "method": method,
                "mae": mae, "rmse": rmse,
                "n_predict": n_predict,
            })
            print(f"{target:<18} {method:<24} {mae:>10.4f} {rmse:>10.4f} {n_predict:>10}")

    return restored, pd.DataFrame(metrics)


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 78)
    print("ИИ-восстановление пропусков (интерполяция + RF + sin/cos для углов)")
    print("=" * 78)

    print(f"→ Чтение дырявого файла {GAPPY_FILE.name}...")
    gappy_df = pd.read_csv(GAPPY_FILE)
    print(f"  ✓ {len(gappy_df)} строк")

    print(f"→ Чтение эталона {FULL_FILE.name}...")
    full_df = pd.read_csv(FULL_FILE)
    print(f"  ✓ {len(full_df)} строк")

    print("\n→ Восстановление пропусков...")
    restored_df, metrics_df = train_and_restore(gappy_df, full_df)

    print(f"\n→ Сохранение восстановленного файла в {OUTPUT_FILE.name}...")
    restored_df.to_csv(OUTPUT_FILE, index=False, float_format="%.4f")
    print(f"  ✓ Готово")

    print(f"→ Сохранение метрик в {METRICS_FILE.name}...")
    metrics_df.to_csv(METRICS_FILE, index=False, float_format="%.6f")
    print(f"  ✓ Готово")

    print("\n" + "=" * 78)
    print(f"  Средний MAE (без азимута): "
          f"{metrics_df[metrics_df['field'] != 'azimuth_deg']['mae'].mean():.4f}")
    if 'cyclic_mae' in metrics_df.columns:
        az_row = metrics_df[metrics_df['field'] == 'azimuth_deg']
        if len(az_row) > 0 and not pd.isna(az_row['cyclic_mae'].iloc[0]):
            print(f"  Азимут — циклическая MAE: {az_row['cyclic_mae'].iloc[0]:.4f}")
    print("=" * 78)


if __name__ == "__main__":
    main()