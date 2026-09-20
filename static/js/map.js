/* ============================================================
   Route Analyzer — карта и базовое отображение
   ============================================================ */

// Инициализация карты (центр — между Миассом и Екатеринбургом)
const map = L.map('map', {
    zoomControl: true,
    attributionControl: true,
}).setView([55.95, 60.35], 8);

// Слой карты — OpenStreetMap (бесплатно, без ключей)
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap',
    maxZoom: 18,
}).addTo(map);

// Переменные для маршрута
let routeData = null;
let routeLine = null;
let startMarker = null;
let endMarker = null;

let vehicleMarker = null;
let currentIndex = 0;

let traveledLine = null;      // пройденный путь
let isPlaying = false;        // идёт ли анимация
let playbackSpeed = 10;       // ×10 по умолчанию
let timer = null;             // интервал

/* ============================================================
   Загрузка данных с сервера
   ============================================================ */

async function loadRoute() {
    try {
        const resp = await fetch('/api/route');
        if (!resp.ok) throw new Error('Ошибка загрузки: ' + resp.status);
        routeData = await resp.json();

        console.log(`Загружено ${routeData.points.length} точек`);
        console.log(`Длина: ${(routeData.total_distance_m / 1000).toFixed(1)} км`);
        console.log(`Время: ${(routeData.total_time_s / 3600).toFixed(2)} ч`);
        console.log(`Топливо: ${routeData.total_fuel_l.toFixed(1)} л`);

        drawRoute();
        updateSidebar();
    } catch (err) {
        console.error('Ошибка:', err);
        document.querySelector('.loading').textContent = 'Ошибка загрузки данных';
    }
}

/* ============================================================
   Отрисовка маршрута
   ============================================================ */

function drawRoute() {
    const coords = routeData.points.map(p => [p.lat, p.lon]);

    // Линия маршрута
    routeLine = L.polyline(coords, {
        color: '#6B8E23',
        weight: 4,
        opacity: 0.8,
    }).addTo(map);

    // Маркеры старта и финиша
    const start = coords[0];
    const end = coords[coords.length - 1];

    startMarker = L.circleMarker(start, {
        radius: 8,
        color: '#FFFFFF',
        fillColor: '#6B8E23',
        fillOpacity: 1,
        weight: 2,
    }).addTo(map).bindPopup('Старт: Миасс');

    endMarker = L.circleMarker(end, {
        radius: 8,
        color: '#FFFFFF',
        fillColor: '#3A3A2E',
        fillOpacity: 1,
        weight: 2,
    }).addTo(map).bindPopup('Финиш: Екатеринбург');

    // Подгоняем карту под маршрут
    map.fitBounds(routeLine.getBounds(), { padding: [40, 40] });
    // Маркер ТС
    createVehicleMarker();
}



/* ============================================================
   Утилиты
   ============================================================ */

function formatTime(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return `${h} ч ${m} мин`;
}

/* ============================================================
   Маркер ТС — круг со стрелкой, поворачивается по азимуту
   ============================================================ */

function createVehicleMarker() {
    const p = routeData.points[currentIndex];

    // Создаём HTML-элемент: круг + стрелка внутри
    const html = `
        <div class="vehicle-marker">
            <div class="vehicle-arrow" style="transform: rotate(${p.azimuth}deg)">
                ▲
            </div>
        </div>
    `;

    const icon = L.divIcon({
        className: 'vehicle-marker-wrap',
        html: html,
        iconSize: [40, 40],
        iconAnchor: [20, 20],
    });

    vehicleMarker = L.marker([p.lat, p.lon], { icon }).addTo(map);
}


/* ============================================================
   УПРАВЛЕНИЕ АНИМАЦИЕЙ
   ============================================================ */

function startAnimation() {
    if (isPlaying) return;
    if (currentIndex >= routeData.points.length - 1) {
        resetAnimation();
    }
    isPlaying = true;
    document.getElementById('btn-start').disabled = true;
    document.getElementById('btn-pause').disabled = false;
    timer = setInterval(tick, 50);  // 20 раз в секунду
}

function pauseAnimation() {
    isPlaying = false;
    document.getElementById('btn-start').disabled = false;
    document.getElementById('btn-pause').disabled = true;
    if (timer) {
        clearInterval(timer);
        timer = null;
    }
}

function resetAnimation() {
    pauseAnimation();
    currentIndex = 0;
    updateVehicleMarker();
    updateTraveledLine();
    updateSidebarLive();
    document.getElementById('btn-pause').disabled = true;
}

function tick() {
    if (!isPlaying) return;

    // Сколько точек пройти за тик. Базовая скорость — 1 точка за тик,
    // умножается на playbackSpeed/10, чтобы ×1..×200 давали 0.1x..20x.
    const step = Math.max(1, Math.round(playbackSpeed / 10));
    currentIndex = Math.min(currentIndex + step, routeData.points.length - 1);

    updateVehicleMarker();
    updateTraveledLine();
    updateSidebarLive();

    if (currentIndex >= routeData.points.length - 1) {
        pauseAnimation();
        console.log('Маршрут завершён');
    }
}

/* ============================================================
   ОБНОВЛЕНИЕ МАРКЕРА ТС
   ============================================================ */

function updateVehicleMarker() {
    const p = routeData.points[currentIndex];

    if (!vehicleMarker) {
        createVehicleMarker();
        return;
    }

    vehicleMarker.setLatLng([p.lat, p.lon]);

    // Поворачиваем стрелку по азимуту
    const arrow = vehicleMarker.getElement().querySelector('.vehicle-arrow');
    if (arrow) {
        arrow.style.transform = `rotate(${p.azimuth}deg)`;
    }
}

/* ============================================================
   ОБНОВЛЕНИЕ ПРОЙДЕННОГО ПУТИ
   ============================================================ */

function updateTraveledLine() {
    // Берём точки от 0 до currentIndex
    const coords = [];
    for (let i = 0; i <= currentIndex; i++) {
        const p = routeData.points[i];
        coords.push([p.lat, p.lon]);
    }

    if (!traveledLine) {
        traveledLine = L.polyline(coords, {
            color: '#3A3A2E',
            weight: 5,
            opacity: 0.9,
        }).addTo(map);
    } else {
        traveledLine.setLatLngs(coords);
    }
}

/* ============================================================
   ОБНОВЛЕНИЕ БОКОВОЙ ПАНЕЛИ В РЕАЛЬНОМ ВРЕМЕНИ
   ============================================================ */

function updateSidebarLive() {
    const p = routeData.points[currentIndex];

    document.getElementById('m-speed').textContent = `${p.speed.toFixed(1)} км/ч`;
    document.getElementById('m-time').textContent = formatTime(p.time_s);
    document.getElementById('m-fuel').textContent = `${p.fuel_lp100km.toFixed(1)} л/100км`;
    document.getElementById('m-vopt').textContent = `${p.v_opt.toFixed(1)} км/ч`;
}

/* ============================================================
   ОБРАБОТЧИКИ КНОПОК
   ============================================================ */

document.getElementById('btn-start').addEventListener('click', startAnimation);
document.getElementById('btn-pause').addEventListener('click', pauseAnimation);
document.getElementById('btn-reset').addEventListener('click', resetAnimation);

document.getElementById('speed-slider').addEventListener('input', (e) => {
    playbackSpeed = parseInt(e.target.value);
    document.getElementById('speed-value').textContent = '×' + playbackSpeed;
});

/* ============================================================
   Старт
   ============================================================ */

function updateSidebar() {
    // Заполняем карточку "Маршрут" (вторая карточка в сайдбаре)
    const cards = document.querySelectorAll('.sidebar .card');
    const routeCard = cards[1];  // вторая карточка — "Маршрут"

    routeCard.innerHTML = `
        <h2>Маршрут</h2>
        <div class="metric">
            <span class="metric-label">Длина</span>
            <span class="metric-value">${(routeData.total_distance_m / 1000).toFixed(1)} км</span>
        </div>
        <div class="metric">
            <span class="metric-label">Время</span>
            <span class="metric-value">${formatTime(routeData.total_time_s)}</span>
        </div>
        <div class="metric">
            <span class="metric-label">Топливо</span>
            <span class="metric-value">${routeData.total_fuel_l.toFixed(1)} л</span>
        </div>
    `;
}

/* ============================================================
   ЗАПУСК
   ============================================================ */

loadRoute().then(() => {
    updateSidebarLive();
});