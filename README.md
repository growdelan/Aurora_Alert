# Aurora Alert (Miasto / PL) — NOAA Kp + Nowcast + Meteo Gate + Gmail (HTML)

Mały, “produkcyjny” skrypt w Pythonie do wysyłania **alertów o szansach na zorzę** dla konkretnej lokalizacji, z **profesjonalnym mailem HTML**.

Skrypt cyklicznie pobiera:
- **NOAA SWPC**: Kp (observed) + Kp (nowcast, 1-min)
- **Open-Meteo**: `is_day` + `cloud_cover` (teraz)

Następnie wysyła maila przez **Gmail SMTP** (App Password) jeśli warunki są sensowne do obserwacji.

---

## Funkcje

- ✅ **NOWCAST alert**: gdy *teraz* (NOWCAST) Kp ≥ próg **i** jest noc + chmury ≤ próg
- ✅ **Cool-down** dla NOWCAST (żeby nie spamować)
- ✅ Konfiguracja przez **`.env`**
- ✅ **HTML PRO** mail + fallback tekstowy
- ✅ “Semafor” w temacie: 🟢/🔴

---

## Jak działa logika alertów

### NOWCAST (teraz, est. 1-min)
Mail NOWCAST poleci, gdy spełnione są wszystkie:
- `NOWCAST_ENABLED=1`
- `Kp_nowcast >= NOWCAST_MIN_KP`
- **noc teraz** (`is_day == 0` w Open-Meteo)
- `cloud_cover <= MAX_CLOUDCOVER`
- minął `NOWCAST_COOLDOWN_SECONDS`

> Kp observed jest używany informacyjnie w mailu (kontekst), ale nie steruje wysyłką.

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

### 2) Środowisko (UV)

```bash
uv sync
```

Opcjonalnie aktywacja:
```bash
source .venv/bin/activate
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
NOWCAST_MIN_KP=7.0
MAX_CLOUDCOVER=70

# --- Częstotliwość / anty-spam ---
NOWCAST_COOLDOWN_SECONDS=7200
NOWCAST_ENABLED=1

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
uv run aurora_alert.py
```

Jeśli chcesz zapisać output do loga jak cron:

```bash
uv run aurora_alert.py >> aurora.log 2>&1
tail -n 50 aurora.log
```

### Test wysyłki maila (na chwilę)
Na czas testu możesz ustawić w `.env`:

```env
NOWCAST_MIN_KP=1
NOWCAST_ENABLED=1
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

*/15 18-23,0-6 * * * cd /home/user/app/aurora_alert && uv run aurora_alert.py >> aurora.log 2>&1
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
NOWCAST_MIN_KP=7.0
MAX_CLOUDCOVER=60
```

---

## Jak interpretować temat maila (semafor)

- 🟢 — “wyjdź teraz / warunki bardzo dobre” (NOWCAST + noc + chmury OK)
- 🔴 — fallback (nie powinno występować przy spełnionych warunkach wysyłki)

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
- używasz `uv run`

### NOWCAST nie wysyła mimo wysokiego Kp
Sprawdź:
- czy `NOWCAST_ENABLED=1`
- czy jest noc i `cloud_cover <= MAX_CLOUDCOVER`
- czy nie działa `NOWCAST_COOLDOWN_SECONDS`

---

## Źródła danych
- NOAA SWPC: planetary K-index (observed + nowcast)
- Open-Meteo: `is_day`, `cloud_cover` (current)

