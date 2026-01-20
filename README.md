# Aurora Alert (Miasto / PL) — NOAA Kp + Forecast + Meteo Gate + Gmail (HTML)

Mały, “produkcyjny” skrypt w Pythonie do wysyłania **alertów o szansach na zorzę** dla konkretnej lokalizacji, z **profesjonalnym mailem HTML**.

Skrypt cyklicznie pobiera:
- **NOAA SWPC**: Kp (observed) + Kp (forecast)
- **Open-Meteo**: `is_day` + `cloud_cover` (teraz oraz prognoza godzinowa pod peak)

Następnie wysyła maila przez **Gmail SMTP** (App Password) jeśli warunki są sensowne do obserwacji.

---

## Funkcje

- ✅ **NOW alert**: gdy *burza już trwa* (Kp ≥ próg) **i** jest noc + chmury ≤ próg
- ✅ **FORECAST alert**: gdy *prognoza w oknie X godzin* ma Kp ≥ próg **i** istnieje **najlepsze okno obserwacyjne** w zakresie **±N godzin wokół peaku** (noc + chmury OK)
- ✅ **Cool-down** osobno dla NOW i FORECAST (żeby nie spamować)
- ✅ **Dedupe forecast**: nie powtarza tego samego peaku (o ile działa cooldown)
- ✅ Konfiguracja przez **`.env`**
- ✅ **HTML PRO** mail + fallback tekstowy
- ✅ “Semafor” w temacie: 🟢/🟡/🔴

---

## Jak działa logika alertów

### NOW (burza trwa teraz)
Mail NOW poleci, gdy spełnione są wszystkie:
- `Kp_now >= NOW_MIN_KP`
- **noc teraz** (`is_day == 0` w Open-Meteo)
- `cloud_cover <= MAX_CLOUDCOVER`
- minął `NOW_COOLDOWN_SECONDS`

### FORECAST (szansa w prognozie)
Mail FORECAST poleci, gdy spełnione są wszystkie:
- w prognozie NOAA: `max(Kp_forecast w oknie FORECAST_WINDOW_HOURS) >= FORECAST_MIN_KP`
- dla czasu peaku istnieje **co najmniej jedna godzina w ±PEAK_WINDOW_HOURS**, w której:
  - jest noc (`is_day == 0`)
  - `cloud_cover <= MAX_CLOUDCOVER`
- minął `FORECAST_COOLDOWN_SECONDS`
- deduplikacja peaku pozwala na wysyłkę (peak time się zmienił albo minął cooldown)

---

## Wymagania

- Python **3.10+** (zalecane 3.11+)
- Konto Gmail z włączonym 2FA i **App Password** (do SMTP)
- Dostęp do internetu (NOAA + Open-Meteo)

---

## Instalacja

### 1) Klon / katalog projektu

Przykład:
```bash
mkdir -p /home/user/app/aurora_alert
cd /home/user/app/aurora_alert
# wrzuć tu aurora_alert.py + README.md
```

### 2) Virtualenv

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install python-dotenv
```

---

## Konfiguracja `.env`

Utwórz plik `.env` w katalogu projektu:

```env
# --- Gmail (SMTP) ---
GMAIL_USER=twojmail@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx

# Jeden lub wiele odbiorców (comma-separated)
ALERT_TO=adres1@domena.pl,adres2@domena.pl

# --- Lokalizacja ---
LAT=51.06
LON=17.02
TZ=Europe/Warsaw

# --- Progi ---
NOW_MIN_KP=6.0
FORECAST_MIN_KP=6.0
MAX_CLOUDCOVER=70

# --- Częstotliwość / anty-spam ---
NOW_COOLDOWN_SECONDS=7200
FORECAST_COOLDOWN_SECONDS=21600

# --- Okna czasowe forecastu ---
FORECAST_WINDOW_HOURS=24
PEAK_WINDOW_HOURS=2

# --- Plik stanu (pamięć wysłanych alertów) ---
STATE_FILE=alert_state.json
```

> `ALERT_TO` może być jedną wartością lub listą rozdzieloną przecinkami.

### Gmail App Password
W Gmailu użyj **App Password** zamiast normalnego hasła:
- włącz 2-step verification
- wygeneruj hasło aplikacji (16 znaków)
- wpisz do `GMAIL_APP_PASSWORD`

---

## Uruchomienie ręczne

```bash
cd /home/user/app/aurora_alert
/home/user/app/aurora_alert/.venv/bin/python aurora_alert.py
```

Jeśli chcesz zapisać output do loga jak cron:

```bash
/home/user/app/aurora_alert/.venv/bin/python aurora_alert.py >> aurora.log 2>&1
tail -n 50 aurora.log
```

### Test wysyłki maila (na chwilę)
Na czas testu możesz ustawić w `.env`:

```env
NOW_MIN_KP=1
FORECAST_MIN_KP=1
MAX_CLOUDCOVER=100
```

Odpal skrypt — powinien wysłać maila (jeśli cooldown tego nie blokuje). Po teście przywróć wartości.

---

## Uruchamianie cykliczne (cron)

Rekomendacja: **co 15 minut**, tylko wieczorem/nocą.

Edytuj crontab:
```bash
crontab -e
```

Dodaj:

```cron
SHELL=/bin/bash
PATH=/usr/bin:/bin

*/15 18-23,0-6 * * * cd /home/user/app/aurora_alert && /home/user/app/aurora_alert/.venv/bin/python aurora_alert.py >> aurora.log 2>&1
0 7 * * * > /home/user/app/aurora_alert/aurora.log
```

- linia 1: uruchamia skrypt co 15 min między 18:00–06:59
- linia 2: czyści log codziennie o 07:00

---

## Pliki i stan

- `aurora_alert.py` — główny skrypt
- `.env` — konfiguracja (sekrety + progi)
- `alert_state.json` — **stan cooldown/dedupe** (tworzy się automatycznie)
- `aurora.log` — log uruchomień (jeśli używasz cron + redirect)

> Nie usuwaj `alert_state.json`, jeśli chcesz zachować “pamięć” i uniknąć ponownych alertów po restarcie.

---

## Personalizacja

### Zmiana lokalizacji
Ustaw w `.env`:
```env
LAT=...
LON=...
TZ=...
```

### Twardsze progi dla Polski
Często sensowne:
```env
NOW_MIN_KP=6.5
FORECAST_MIN_KP=6.5
MAX_CLOUDCOVER=60
```

### Zmiana “okna” obserwacyjnego wokół peaku
```env
PEAK_WINDOW_HOURS=3
```

---

## Jak interpretować temat maila (semafor)

- 🟢 — “wyjdź teraz / warunki bardzo dobre” (NOW + noc + chmury OK)
- 🟡 — “przygotuj się” (forecast + znalezione okno obserwacyjne)
- 🔴 — fallback (zwykle nie występuje przy obecnych gate’ach; zostawione na wypadek zmian)

---

## Troubleshooting

### Nie wysyła maili
- sprawdź czy masz `GMAIL_USER` i `GMAIL_APP_PASSWORD`
- upewnij się, że to **App Password** (a nie normalne hasło)
- sprawdź log:
  ```bash
  tail -n 200 aurora.log
  ```

### Cron nie widzi `.env`
Upewnij się, że w cronie jest:
- `cd /home/user/app/aurora_alert`
- używasz `.venv/bin/python`

### Brak forecast “okna obserwacyjnego”
To oznacza, że w ±`PEAK_WINDOW_HOURS` od peaku:
- jest dzień lub
- zachmurzenie przekracza `MAX_CLOUDCOVER`

---

## Źródła danych
- NOAA SWPC: planetary K-index (observed + forecast)
- Open-Meteo: `is_day`, `cloud_cover` (current + hourly)
