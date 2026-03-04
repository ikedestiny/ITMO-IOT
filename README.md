# 🏢 Coworking Occupancy Monitor

> IoT-система мониторинга занятости коворкинга / аудитории в реальном времени.  
> Курс «Сетевые технологии интернета вещей» | ФПИЭТ

[![Status](https://img.shields.io/badge/status-active-brightgreen)]()
[![Platform](https://img.shields.io/badge/platform-ESP8266%20NodeMCU-blue)]()
[![Protocol](https://img.shields.io/badge/protocol-MQTT%20%2B%20REST-orange)]()

---

## 📋 Описание

Система определяет, есть ли люди в помещении, используя датчик движения **HC-SR501** и датчик шума **FC-04**. Статус «свободно» / «занято» отображается на **RGB-светодиоде WS2812B** у входа и транслируется в сеть через **MQTT**. История занятости хранится в **InfluxDB** и визуализируется в **Grafana**. **Telegram-бот** позволяет проверить статус и забронировать место.

### Как определяется занятость

Помещение считается **занятым**, если за последние **5 минут** зафиксировано хотя бы одно срабатывание датчика движения **ИЛИ** датчика шума.

---

## 🔧 Компоненты

| Компонент | Модель | Назначение |
|-----------|--------|------------|
| Микроконтроллер | NodeMCU v3 Lolin | Центральный узел, Wi-Fi |
| Датчик движения | HC-SR501 | Обнаружение присутствия |
| Датчик шума | FC-04 | Дополнительный признак активности |
| RGB-светодиод | WS2812B | Индикатор у входа (🟢/🔴) |
| Дисплей | TM1638 LED&KEY | Локальный вывод «FREE» / «BUSY» |
| Расширитель I2C | PCF8574 | Доп. GPIO при масштабировании |

---

## 🏗️ Архитектура

```
HC-SR501 ──┐
           ├─→ [Логика занятости] ─→ MQTT ─→ Mosquitto ─→ Node-RED
FC-04    ──┘         ↑ (booking sync)              ↙         ↘
                                             InfluxDB      FastAPI
WS2812B  ←── [LED Driver] ←── статус            ↓              ↓
TM1638   ←── [Display Driver]               Grafana    Telegram Bot
```

**Слои прошивки:**
- `drivers/` — работа с железом (HC-SR501, FC-04, WS2812B, TM1638)
- `services/` — логика скользящего окна занятости
- `network/` — MQTT-клиент, Wi-Fi, переподключение
- `main.ino` — оркестрация, главный цикл

---

## 📡 MQTT-топики

| Топик | QoS | Retain | Описание |
|-------|-----|--------|----------|
| `coworking/status` | 1 | ✅ | `"free"` / `"busy"` |
| `coworking/sensors/motion` | 0 | ❌ | Raw значение HC-SR501 |
| `coworking/sensors/noise` | 0 | ❌ | Raw значение FC-04 |
| `coworking/booking/sync` | 1 | ✅ | Расписание бронирований |
| `coworking/device/health` | 1 | ✅ | LWT + heartbeat |

---

## 🚀 Быстрый старт

### 1. Устройство (Arduino IDE)

```bash
# Установить зависимости через Arduino Library Manager:
# - PubSubClient (MQTT)
# - FastLED (WS2812B)
# - TM1638 library
# - DHT sensor library (опционально)

# Скопировать конфиг:
cp firmware/config.example.h firmware/config.h

# Заполнить в config.h:
# - WIFI_SSID / WIFI_PASSWORD
# - MQTT_HOST / MQTT_USER / MQTT_PASSWORD
# - ROOM_ID

# Прошить через Arduino IDE: firmware/main.ino
```

### 2. Сервер (Docker)

```bash
git clone https://github.com/<your-username>/coworking-monitor
cd coworking-monitor/server

# Настройка переменных окружения
cp .env.example .env
# Отредактировать .env (пароли, токен бота, и т.д.)

# Запуск всех сервисов
docker-compose up -d

# Проверить статус
docker-compose ps
```

**Сервисы после запуска:**

| Сервис | URL |
|--------|-----|
| Grafana | http://localhost:3000 |
| Node-RED | http://localhost:1880 |
| REST API | http://localhost:8000/docs |
| MQTT Broker | localhost:1883 (MQTT) / 8883 (TLS) |

---

## 📊 Grafana Dashboard

После запуска импортировать дашборд:  
`Grafana → Import → Upload grafana/coworking-dashboard.json`

Доступные панели:
- Текущий статус (free/busy) в реальном времени
- Тепловая карта занятости по часам и дням недели
- График занятости за последние 7 дней
- Health-панель устройства (RSSI, uptime, last seen)

---

## 🤖 Telegram-бот

Команды:

| Команда | Описание |
|---------|----------|
| `/status` | Текущий статус помещения |
| `/schedule` | Расписание на сегодня |
| `/book HH:MM HH:MM` | Забронировать время |
| `/cancel` | Отменить бронирование |
| `/stats` | Статистика за неделю |

---

## 🔌 REST API

Документация: `http://localhost:8000/docs` (Swagger UI)

```http
GET  /api/status              # Текущий статус
GET  /api/bookings?date=today # Список бронирований
POST /api/bookings            # Создать бронирование
DELETE /api/bookings/{id}     # Отменить бронирование
GET  /api/stats?period=week   # Статистика занятости
```

---

## 📁 Структура репозитория

```
.
├── firmware/
│   ├── main.ino             # Главный файл прошивки
│   ├── config.example.h     # Шаблон конфигурации
│   ├── drivers/             # Работа с железом
│   ├── services/            # Бизнес-логика устройства
│   └── network/             # MQTT, Wi-Fi
├── server/
│   ├── docker-compose.yml   # Оркестрация сервисов
│   ├── mosquitto/           # Конфиг MQTT-брокера
│   ├── nodered/             # Экспорт потоков Node-RED
│   ├── api/                 # FastAPI-приложение
│   ├── bot/                 # Telegram-бот
│   └── grafana/             # Dashboard JSON
├── docs/
│   ├── architecture.docx    # Архитектурное описание
│   └── report.docx          # Отчёт по проекту
└── README.md
```

---

## 📅 Контрольные точки

| КТ | Дата | Статус |
|----|------|--------|
| КТ1: Этапы 1–2 (автономное устройство) | 04.03 | ✅ |
| КТ2: Этап 3 (MQTT, сеть) | 18.03 | 🔄 |
| КТ3: Этап 4 (InfluxDB, Grafana) | 15.04 | ⏳ |
| КТ4: Этап 5 (API, Telegram-бот) | 29.04 | ⏳ |
| КТ5: Финальная демонстрация | 13.05 | ⏳ |

---

## 👤 Команда

- **Преподаватель:** Гончаров А.А. ([@Aleshka_Goncharov](https://t.me/Aleshka_Goncharov))
- **Курс:** Сетевые технологии интернета вещей | ФПИЭТ

---

## 📄 Лицензия

MIT
