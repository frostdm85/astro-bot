/**
 * АСТРО-БОТ MINI APP
 * Интерактивный прогноз дня
 */

// Telegram WebApp
const tg = window.Telegram?.WebApp;

// Символы планет
const planetSymbols = {
    'Солнце': '☉', 'Луна': '☽', 'Меркурий': '☿', 'Венера': '♀',
    'Марс': '♂', 'Юпитер': '♃', 'Сатурн': '♄', 'Уран': '♅',
    'Нептун': '♆', 'Плутон': '♇', 'Лилит': '⚸', 'Северный узел': '☊'
};

// Эмодзи настроений
const moodEmoji = { good: '😊', neutral: '😌', difficult: '🌊' };
const moodTitle = { good: 'Хороший день', neutral: 'Обычный день', difficult: 'Непростой день' };

// Запуск
document.addEventListener('DOMContentLoaded', init);

async function init() {
    // Telegram
    if (tg) {
        tg.ready();
        tg.expand();
    }

    // Загрузка прогноза
    await loadForecast();
}

async function loadForecast() {
    try {
        const response = await fetch('/api/demo/forecast/today');
        const data = await response.json();
        renderForecast(data);
    } catch (e) {
        document.getElementById('loading').innerHTML = `
            <p style="color: #ef4444;">Ошибка загрузки: ${e.message}</p>
        `;
    }
}

function renderForecast(data) {
    // Скрываем загрузку
    document.getElementById('loading').classList.remove('active');
    document.getElementById('main').classList.add('active');

    // Дата
    document.getElementById('dayName').textContent = data.day_name;
    document.getElementById('dateText').textContent = data.date;

    // Настроение
    const moodCard = document.getElementById('moodCard');
    moodCard.className = `mood-card ${data.mood}`;
    document.getElementById('moodEmoji').textContent = moodEmoji[data.mood] || '😌';
    document.getElementById('moodTitle').textContent = moodTitle[data.mood] || 'День';
    document.getElementById('moodSubtitle').textContent =
        data.mood === 'good' ? 'Благоприятные влияния' :
        data.mood === 'difficult' ? 'Требует внимательности' : 'Нет особых указаний';

    // Прогноз
    document.getElementById('forecastText').textContent = data.summary;

    // Транзиты
    renderTransits(data.transits);

    // Навигация
    document.getElementById('prevDay').onclick = () => alert('Навигация будет доступна в полной версии');
    document.getElementById('nextDay').onclick = () => alert('Навигация будет доступна в полной версии');
    document.getElementById('openCalendar').onclick = () => {
        document.getElementById('main').classList.remove('active');
        document.getElementById('calendar').classList.add('active');
    };
    document.getElementById('backFromCalendar').onclick = () => {
        document.getElementById('calendar').classList.remove('active');
        document.getElementById('main').classList.add('active');
    };
}

function renderTransits(transits) {
    const container = document.getElementById('transitsList');
    container.innerHTML = '';

    if (!transits || transits.length === 0) {
        container.innerHTML = '<p class="empty-state-text">Нет активных транзитов</p>';
        return;
    }

    transits.forEach((tr, i) => {
        // Время действия (2 часа ДО аспекта)
        const [h, m] = tr.time.split(':').map(Number);
        const startH = Math.max(0, h - 2);
        const timeRange = `${String(startH).padStart(2, '0')}:00 — ${tr.time}`;

        // Символы планет
        const tSym = planetSymbols[tr.transit_planet] || tr.transit_planet;
        const nSym = planetSymbols[tr.natal_planet] || tr.natal_planet;

        const item = document.createElement('div');
        item.className = `timeline-item ${tr.nature}`;
        item.style.animationDelay = `${i * 0.1}s`;

        item.innerHTML = `
            <div class="timeline-time">${timeRange}</div>
            <div class="timeline-planets">
                <span class="planet-symbol">${tSym}</span>
                <span class="aspect-symbol">${tr.aspect_symbol}</span>
                <span class="planet-symbol">${nSym}</span>
            </div>
            <div class="timeline-meaning">${tr.aspect} — ${tr.formula}</div>
            <div class="timeline-details">
                ${tr.meanings.map(m => `<div class="detail-row"><span class="detail-value">• ${m}</span></div>`).join('')}
            </div>
        `;

        // Раскрытие по клику
        item.onclick = () => {
            item.classList.toggle('expanded');
            if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
        };

        container.appendChild(item);
    });
}
