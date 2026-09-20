"""
Flask-приложение для визуализации маршрута ТС.

Отдаёт:
- GET /             — HTML-страницу с картой
- GET /api/route    — JSON с данными маршрута (route_restored.csv)
"""

from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, render_template


# ============================================================
# НАСТРОЙКИ
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = PROJECT_ROOT / "data" / "route_restored.csv"

app = Flask(__name__,
            template_folder=str(PROJECT_ROOT / "templates"),
            static_folder=str(PROJECT_ROOT / "static"))


# ============================================================
# МАРШРУТЫ
# ============================================================

@app.route("/")
def index():
    """Главная страница с картой."""
    return render_template("index.html")


@app.route("/api/route")
def api_route():
    """
    Отдаёт весь маршрут в JSON.
    Все NaN заменяются на 0 (JSON не поддерживает NaN).
    """
    df = pd.read_csv(DATA_FILE)

    # Заменяем все NaN на 0 — иначе JSON падает
    df = df.fillna(0)

    data = {
        "points": [
            {
                "id": int(row.point_id),
                "lat": round(float(row.lat), 6),
                "lon": round(float(row.lon), 6),
                "elevation": round(float(row.elevation_m), 1),
                "slope": round(float(row.slope_deg), 2),
                "slope_pred": round(float(row.slope_predicted_next_deg), 2),
                "azimuth": round(float(row.azimuth_deg), 1),
                "speed": round(float(row.speed_kmh), 1),
                "v_opt": round(float(row.v_optimal_kmh), 1),
                "fuel_lp100km": round(float(row.fuel_rate_lp100km), 2),
                "distance_m": round(float(row.distance_m), 1),
                "time_s": round(float(row.time_s), 1),
            }
            for row in df.itertuples()
        ],
        "total_distance_m": float(df["distance_m"].max()),
        "total_time_s": float(df["time_s"].max()),
        "total_fuel_l": float(
        (df["fuel_rate_lpkm"] * (df["distance_m"].diff().fillna(0) / 1000)).sum()   
        ),
    }

    return jsonify(data)


# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Flask-сервер запускается...")
    print("Открой в браузере: http://127.0.0.1:5000")
    print("=" * 60)
    app.run(debug=True, host="127.0.0.1", port=5000)