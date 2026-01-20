#!/usr/bin/env python3
# aurora_alert.py

import json
import os
import ssl
import smtplib
import urllib.request
from email.message import EmailMessage
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from dotenv import load_dotenv
from zoneinfo import ZoneInfo


# -------------------- helpers --------------------
def fetch_json(url: str):
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def parse_recipients(s: str) -> List[str]:
    return [p.strip() for p in (s or "").split(",") if p.strip()]


def utc_now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def load_state(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def save_state(path: str, state: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def parse_noaa_time_utc(time_tag: str) -> Optional[datetime]:
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(time_tag, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def utc_to_local_str(dt_utc: Optional[datetime], tz: str, fmt: str = "%d.%m.%Y, %H:%M") -> str:
    if dt_utc is None:
        return "—"
    return dt_utc.astimezone(ZoneInfo(tz)).strftime(fmt)


def local_time_str_from_openmeteo(t: Optional[str]) -> str:
    return t.replace("T", " ") if t else "—"


def kp_label(kp: float) -> Tuple[str, str]:
    if kp >= 8:
        return "EKSTREMALNA", "🔥"
    if kp >= 7:
        return "BARDZO DUŻA", "🚀"
    if kp >= 6:
        return "DUŻA", "✨"
    if kp >= 5:
        return "ŚREDNIA", "🌙"
    return "NISKA", "🫥"


def cloud_badge(cloud: Optional[int], max_cloud: int) -> Tuple[str, str]:
    if cloud is None:
        return "—", "⚪"
    if cloud <= max_cloud:
        return f"{cloud}%", "✅"
    return f"{cloud}%", "❌"


def night_badge(is_night: Optional[bool]) -> Tuple[str, str]:
    if is_night is None:
        return "—", "⚪"
    return ("NOC", "✅") if is_night else ("DZIEŃ", "❌")


def html_escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# -------------------- SMTP --------------------
def send_gmail(
    gmail_user: str,
    gmail_app_password: str,
    to_addrs: List[str],
    subject: str,
    text_body: str,
    html_body: str,
):
    if not to_addrs:
        raise ValueError("Brak odbiorców (ALERT_TO).")

    msg = EmailMessage()
    msg["From"] = gmail_user
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = subject

    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(gmail_user, gmail_app_password)
        server.send_message(msg, to_addrs=to_addrs)


# -------------------- NOAA data sources --------------------
KP_NOW_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
KP_FORECAST_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json"


def kp_now() -> Tuple[float, str]:
    data = fetch_json(KP_NOW_URL)
    last = data[-1]
    return float(last[1]), str(last[0])


def kp_forecast_max_next_hours(hours: int = 24) -> Tuple[float, str, Optional[datetime]]:
    data = fetch_json(KP_FORECAST_URL)
    rows = data[1:] if isinstance(data[0], list) else data

    now = datetime.now(timezone.utc)
    best_kp = -1.0
    best_time = "unknown"
    best_dt = None

    for row in rows:
        if not row or len(row) < 2:
            continue
        time_tag = str(row[0])
        dt = parse_noaa_time_utc(time_tag)
        if dt is None:
            continue

        delta_h = (dt - now).total_seconds() / 3600.0
        if delta_h < 0 or delta_h > hours:
            continue

        try:
            kp = float(row[1])
        except Exception:
            continue

        if kp > best_kp:
            best_kp = kp
            best_time = time_tag
            best_dt = dt

    return best_kp, best_time, best_dt


# -------------------- Open-Meteo gates --------------------
def meteo_gate_now(lat: float, lon: float, tz: str) -> Tuple[bool, int, Optional[str]]:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&current=cloud_cover,is_day"
        f"&timezone={tz}"
    )
    data = fetch_json(url)
    cur = data.get("current", {})
    is_day = int(cur.get("is_day", 1))
    cloud = int(cur.get("cloud_cover", 100))
    cur_time = cur.get("time")
    return (is_day == 0), cloud, cur_time


def meteo_best_slot_around_peak(
    lat: float,
    lon: float,
    tz: str,
    peak_dt_utc: datetime,
    window_hours: int,
    max_cloud: int,
) -> Tuple[bool, Optional[int], Optional[str]]:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&hourly=cloud_cover,is_day"
        f"&forecast_days=2"
        f"&timezone={tz}"
    )
    data = fetch_json(url)
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    clouds = hourly.get("cloud_cover", [])
    is_days = hourly.get("is_day", [])

    if not times or len(times) != len(clouds) or len(times) != len(is_days):
        return False, None, None

    offset_sec = int(data.get("utc_offset_seconds", 0))
    peak_local_ts = int(peak_dt_utc.timestamp()) + offset_sec

    start_ts = peak_local_ts - window_hours * 3600
    end_ts = peak_local_ts + window_hours * 3600

    best_cloud = None
    best_time = None

    for i, tstr in enumerate(times):
        try:
            dt_local_naive = datetime.strptime(tstr, "%Y-%m-%dT%H:%M")
        except ValueError:
            continue

        ts = int(dt_local_naive.replace(tzinfo=timezone.utc).timestamp()) + offset_sec

        if ts < start_ts or ts > end_ts:
            continue

        is_day = int(is_days[i])
        cloud = int(clouds[i])

        if is_day != 0:
            continue
        if cloud > max_cloud:
            continue

        if best_cloud is None or cloud < best_cloud:
            best_cloud = cloud
            best_time = tstr

    if best_cloud is None:
        return False, None, None

    return True, best_cloud, best_time


# -------------------- cooldown & dedupe --------------------
def can_send_now(state: dict, key: str, cooldown_seconds: int, now_ts: int) -> bool:
    last_ts = int(state.get("last_sent", {}).get(key, 0))
    return (now_ts - last_ts) >= cooldown_seconds


def mark_sent(state: dict, key: str, now_ts: int) -> None:
    state.setdefault("last_sent", {})
    state["last_sent"][key] = now_ts


def should_send_forecast(state: dict, peak_time: str, now_ts: int, cooldown_seconds: int) -> bool:
    last_peak = state.get("forecast", {}).get("last_peak_time")
    if last_peak != peak_time:
        return can_send_now(state, "FORECAST", cooldown_seconds, now_ts)
    return can_send_now(state, "FORECAST", cooldown_seconds, now_ts)


def mark_forecast_peak(state: dict, peak_time: str) -> None:
    state.setdefault("forecast", {})
    state["forecast"]["last_peak_time"] = peak_time


# -------------------- PRO email (HTML + subject traffic light) --------------------
def pick_priority_emoji(
    *,
    send_now_flag: bool,
    send_forecast_flag: bool,
    now_gate_ok: bool,
    best_ok: bool,
) -> str:
    # 🟢: right-now + good conditions
    if send_now_flag and now_gate_ok:
        return "🟢"
    # 🟡: forecast + best window available
    if (not send_now_flag) and send_forecast_flag and best_ok:
        return "🟡"
    # fallback
    return "🔴"


def build_email_pro(
    *,
    lat: float,
    lon: float,
    tz: str,
    max_cloud: int,
    forecast_window_h: int,
    peak_window_h: int,
    send_now_flag: bool,
    send_forecast_flag: bool,
    kp_current: float,
    kp_current_time_utc_str: str,
    is_night_now: bool,
    cloud_now: int,
    meteo_time_now: Optional[str],
    kp_fc_max: float,
    kp_fc_time_utc_str: str,
    kp_fc_dt_utc: Optional[datetime],
    best_cloud: Optional[int],
    best_time_local: Optional[str],
) -> Tuple[str, str, str]:
    now_level, now_emoji = kp_label(kp_current)
    fc_level, fc_emoji = kp_label(kp_fc_max if kp_fc_max >= 0 else 0.0)

    kp_now_dt = parse_noaa_time_utc(kp_current_time_utc_str)
    kp_now_local = utc_to_local_str(kp_now_dt, tz)
    kp_now_utc = kp_current_time_utc_str.replace(".000", "")

    kp_peak_local = utc_to_local_str(kp_fc_dt_utc, tz)
    kp_peak_utc = kp_fc_time_utc_str

    meteo_now_local = local_time_str_from_openmeteo(meteo_time_now)

    night_now_txt, night_now_badge_txt = night_badge(is_night_now)
    cloud_now_txt, cloud_now_badge_txt = cloud_badge(cloud_now, max_cloud)

    best_time_local_txt = local_time_str_from_openmeteo(best_time_local)
    best_cloud_txt, best_cloud_badge_txt = cloud_badge(best_cloud, max_cloud)

    now_gate_ok = (is_night_now and cloud_now <= max_cloud)
    best_ok = (best_time_local is not None and best_cloud is not None and best_cloud <= max_cloud)

    priority = pick_priority_emoji(
        send_now_flag=send_now_flag,
        send_forecast_flag=send_forecast_flag,
        now_gate_ok=now_gate_ok,
        best_ok=best_ok,
    )

    # Subject with traffic light + key numbers
    if send_now_flag and send_forecast_flag:
        subject = f"{priority} Zorza Wałbrzych — NOW Kp{kp_current:.1f} · Fc Kp{kp_fc_max:.1f}"
    elif send_now_flag:
        subject = f"{priority} Zorza Wałbrzych — NOW Kp{kp_current:.1f}"
    else:
        subject = f"{priority} Zorza Wałbrzych — Forecast Kp{kp_fc_max:.1f}"

    # Recommendation
    rec_lines = []
    if send_now_flag and now_gate_ok:
        rec_lines.append("Wyjdź teraz: warunki są sprzyjające.")
    if send_forecast_flag and best_ok:
        rec_lines.append(f"Najlepsze okno: {best_time_local_txt} (chmury {best_cloud_txt}).")
    if not rec_lines:
        rec_lines.append("Sprawdź północne niebo z dala od świateł miasta.")
    recommendation = " ".join(rec_lines)

    # Plain-text fallback
    text_body = f"""\
🌌 ALERT ZORZA POLARNA — WAŁBRZYCH

Priorytet: {priority}

📍 Lokalizacja: Wałbrzych ({lat:.2f} N, {lon:.2f} E)

⚡ SYTUACJA TERAZ
- Kp: {kp_current:.1f} ({now_level})
- Czas pomiaru: {kp_now_local} (UTC: {kp_now_utc})
- Warunki: {night_now_txt} {night_now_badge_txt}, chmury {cloud_now_txt} {cloud_now_badge_txt} (meteo: {meteo_now_local})

🔮 PROGNOZA ({forecast_window_h}h)
- Max Kp: {kp_fc_max:.1f} ({fc_level})
- Peak: {kp_peak_local} (UTC: {kp_peak_utc})
- Najlepsze okno (±{peak_window_h}h): {best_time_local_txt} | chmury {best_cloud_txt} {best_cloud_badge_txt}

✨ REKOMENDACJA
{recommendation}

Źródła: NOAA SWPC (Kp), Open-Meteo (noc/chmury).
"""

    # HTML (inline CSS)
    def pill(text: str, bg: str, fg: str = "#111827") -> str:
        return f"""<span style="display:inline-block;padding:6px 10px;border-radius:999px;background:{bg};color:{fg};font-weight:600;font-size:12px;line-height:1;">{html_escape(text)}</span>"""

    now_pill = pill(f"{now_emoji} {now_level}", "#DCFCE7") if kp_current >= 6 else pill(f"{now_emoji} {now_level}", "#E5E7EB")
    fc_pill = pill(f"{fc_emoji} {fc_level}", "#DBEAFE") if kp_fc_max >= 6 else pill(f"{fc_emoji} {fc_level}", "#E5E7EB")
    prio_pill = pill(f"{priority} PRIORYTET", "#111827", "#ffffff")

    now_gate_pill = pill("WARUNKI OK", "#DCFCE7") if now_gate_ok else pill("WARUNKI SŁABE", "#FEE2E2")
    best_pill = pill("IDEALNE OKNO", "#DCFCE7") if best_ok else pill("BRAK OKNA", "#FEE2E2")

    html_body = f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f6f7fb;font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Arial;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f6f7fb;padding:24px 0;">
      <tr>
        <td align="center">
          <table role="presentation" width="640" cellspacing="0" cellpadding="0" style="width:640px;max-width:92vw;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 8px 30px rgba(15,23,42,0.08);">
            <tr>
              <td style="padding:22px 24px;background:linear-gradient(135deg,#0b1220,#111b36);color:#fff;">
                <div style="font-size:12px;letter-spacing:0.14em;text-transform:uppercase;opacity:0.8;">Aurora Alert</div>
                <div style="font-size:22px;font-weight:800;margin-top:6px;line-height:1.2;">🌌 Zorza — Wałbrzych</div>
                <div style="margin-top:10px;">
                  {prio_pill}&nbsp; {now_pill}&nbsp; {fc_pill}&nbsp; {now_gate_pill}
                </div>
                <div style="margin-top:14px;font-size:13px;opacity:0.85;">
                  Lokalizacja: <b>{lat:.2f} N</b>, <b>{lon:.2f} E</b> · Strefa: <b>{html_escape(tz)}</b>
                </div>
              </td>
            </tr>

            <tr>
              <td style="padding:18px 24px;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:separate;border-spacing:0 12px;">
                  <tr>
                    <td style="padding:16px;border:1px solid #e5e7eb;border-radius:14px;background:#ffffff;">
                      <div style="display:flex;justify-content:space-between;align-items:center;">
                        <div style="font-size:14px;font-weight:800;color:#111827;">⚡ Sytuacja teraz</div>
                        <div style="font-size:12px;color:#6b7280;">aktualny odczyt</div>
                      </div>

                      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:10px;">
                        <tr>
                          <td style="padding:8px 0;color:#6b7280;font-size:12px;width:42%;">Indeks Kp</td>
                          <td style="padding:8px 0;color:#111827;font-size:14px;font-weight:800;">
                            {kp_current:.1f} <span style="font-size:12px;font-weight:700;color:#6b7280;">({html_escape(now_level)})</span>
                          </td>
                        </tr>
                        <tr>
                          <td style="padding:8px 0;color:#6b7280;font-size:12px;">Czas pomiaru</td>
                          <td style="padding:8px 0;color:#111827;font-size:13px;">
                            <b>{html_escape(kp_now_local)}</b>
                            <span style="color:#6b7280;">&nbsp;· UTC: {html_escape(kp_now_utc)}</span>
                          </td>
                        </tr>
                        <tr>
                          <td style="padding:8px 0;color:#6b7280;font-size:12px;">Warunki (teraz)</td>
                          <td style="padding:8px 0;color:#111827;font-size:13px;">
                            {night_now_badge_txt} <b>{night_now_txt}</b>
                            &nbsp;&nbsp;|&nbsp;&nbsp;
                            {cloud_now_badge_txt} <b>Chmury {cloud_now_txt}</b>
                            <span style="color:#6b7280;">&nbsp;· {html_escape(meteo_now_local)}</span>
                          </td>
                        </tr>
                      </table>
                    </td>
                  </tr>

                  <tr>
                    <td style="padding:16px;border:1px solid #e5e7eb;border-radius:14px;background:#ffffff;">
                      <div style="display:flex;justify-content:space-between;align-items:center;">
                        <div style="font-size:14px;font-weight:800;color:#111827;">🔮 Prognoza</div>
                        <div style="font-size:12px;color:#6b7280;">okno: {forecast_window_h}h</div>
                      </div>

                      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:10px;">
                        <tr>
                          <td style="padding:8px 0;color:#6b7280;font-size:12px;width:42%;">Maksymalny Kp</td>
                          <td style="padding:8px 0;color:#111827;font-size:14px;font-weight:800;">
                            {kp_fc_max:.1f} <span style="font-size:12px;font-weight:700;color:#6b7280;">({html_escape(fc_level)})</span>
                          </td>
                        </tr>
                        <tr>
                          <td style="padding:8px 0;color:#6b7280;font-size:12px;">Peak burzy</td>
                          <td style="padding:8px 0;color:#111827;font-size:13px;">
                            <b>{html_escape(kp_peak_local)}</b>
                            <span style="color:#6b7280;">&nbsp;· UTC: {html_escape(kp_peak_utc)}</span>
                          </td>
                        </tr>
                        <tr>
                          <td style="padding:8px 0;color:#6b7280;font-size:12px;">Okno obserwacyjne</td>
                          <td style="padding:8px 0;color:#111827;font-size:13px;">
                            {best_pill}
                            <span style="display:inline-block;margin-left:10px;">
                              🕒 <b>{html_escape(best_time_local_txt)}</b>
                              &nbsp;&nbsp;|&nbsp;&nbsp;
                              ☁️ <b>{html_escape(best_cloud_txt)}</b> {best_cloud_badge_txt}
                              <span style="color:#6b7280;">&nbsp;(±{peak_window_h}h)</span>
                            </span>
                          </td>
                        </tr>
                      </table>

                      <div style="margin-top:12px;padding:12px 14px;border-radius:12px;background:#f8fafc;border:1px solid #e5e7eb;">
                        <div style="font-size:12px;color:#6b7280;margin-bottom:6px;">✨ Rekomendacja</div>
                        <div style="font-size:14px;color:#111827;font-weight:700;line-height:1.35;">
                          {html_escape(recommendation)}
                        </div>
                        <div style="margin-top:8px;font-size:12px;color:#6b7280;line-height:1.35;">
                          Wskazówka: patrz na północ, najlepiej z dala od świateł miasta. Daj oczom 10–15 min adaptacji.
                        </div>
                      </div>
                    </td>
                  </tr>

                  <tr>
                    <td style="padding:14px 16px;border-radius:14px;background:#0b1220;color:#dbeafe;">
                      <div style="font-size:12px;opacity:0.9;">Źródła</div>
                      <div style="font-size:12px;opacity:0.85;line-height:1.35;margin-top:4px;">
                        NOAA SWPC (Kp) · Open-Meteo (noc/chmury)
                      </div>
                      <div style="font-size:11px;opacity:0.75;margin-top:10px;">
                        Uwaga: prognozy zorzy są probabilistyczne. Najlepszy efekt uzyskasz w miejscach z ciemnym niebem.
                      </div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""

    return subject, text_body, html_body


# -------------------- main --------------------
def main():
    load_dotenv()

    gmail_user = os.getenv("GMAIL_USER", "").strip()
    gmail_app_password = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    recipients = parse_recipients(os.getenv("ALERT_TO", ""))

    lat = float(os.getenv("LAT", "50.77"))
    lon = float(os.getenv("LON", "16.28"))
    tz = os.getenv("TZ", "Europe/Warsaw")

    now_min_kp = float(os.getenv("NOW_MIN_KP", "6.0"))
    forecast_min_kp = float(os.getenv("FORECAST_MIN_KP", "6.0"))
    max_cloud = int(os.getenv("MAX_CLOUDCOVER", "70"))

    now_cd = int(os.getenv("NOW_COOLDOWN_SECONDS", "7200"))
    forecast_cd = int(os.getenv("FORECAST_COOLDOWN_SECONDS", "21600"))
    forecast_window_h = int(os.getenv("FORECAST_WINDOW_HOURS", "24"))
    peak_window_h = int(os.getenv("PEAK_WINDOW_HOURS", "2"))

    state_file = os.getenv("STATE_FILE", "alert_state.json")

    if not gmail_user or not gmail_app_password:
        raise RuntimeError("Brak GMAIL_USER lub GMAIL_APP_PASSWORD w .env")
    if not recipients:
        raise RuntimeError("Brak ALERT_TO w .env")

    state = load_state(state_file)
    now_ts = utc_now_ts()

    # NOW gate
    is_night_now, cloud_now, meteo_time_now = meteo_gate_now(lat, lon, tz)

    # NOAA Kp
    kp_current, kp_current_time = kp_now()
    kp_fc_max, kp_fc_time, kp_fc_dt = kp_forecast_max_next_hours(forecast_window_h)

    send_now_flag = False
    send_forecast_flag = False
    best_cloud: Optional[int] = None
    best_time_local: Optional[str] = None

    # NOW decision
    if kp_current >= now_min_kp:
        if is_night_now and cloud_now <= max_cloud:
            if can_send_now(state, "NOW", now_cd, now_ts):
                send_now_flag = True
            else:
                print(f"NOW: spełnione (Kp={kp_current:.1f}), cooldown aktywny.")
        else:
            print(f"NOW: Kp spełnione (Kp={kp_current:.1f}), ale gate blokuje (dzień/chmury).")

    # FORECAST decision
    if kp_fc_max >= forecast_min_kp and kp_fc_dt is not None:
        ok, best_cloud, best_time_local = meteo_best_slot_around_peak(
            lat=lat,
            lon=lon,
            tz=tz,
            peak_dt_utc=kp_fc_dt,
            window_hours=peak_window_h,
            max_cloud=max_cloud,
        )
        if ok:
            if should_send_forecast(state, kp_fc_time, now_ts, forecast_cd):
                send_forecast_flag = True
            else:
                print(f"FORECAST: spełnione (peak {kp_fc_time}), cooldown/dedupe aktywne.")
        else:
            print(f"FORECAST: brak okna noc+chmury<= {max_cloud}% w ±{peak_window_h}h (peak {kp_fc_time} UTC).")

    if not (send_now_flag or send_forecast_flag):
        print("✅ Brak nowych alertów do wysłania.")
        return

    subject, text_body, html_body = build_email_pro(
        lat=lat,
        lon=lon,
        tz=tz,
        max_cloud=max_cloud,
        forecast_window_h=forecast_window_h,
        peak_window_h=peak_window_h,
        send_now_flag=send_now_flag,
        send_forecast_flag=send_forecast_flag,
        kp_current=kp_current,
        kp_current_time_utc_str=kp_current_time,
        is_night_now=is_night_now,
        cloud_now=cloud_now,
        meteo_time_now=meteo_time_now,
        kp_fc_max=kp_fc_max,
        kp_fc_time_utc_str=kp_fc_time,
        kp_fc_dt_utc=kp_fc_dt,
        best_cloud=best_cloud,
        best_time_local=best_time_local,
    )

    send_gmail(
        gmail_user=gmail_user,
        gmail_app_password=gmail_app_password,
        to_addrs=recipients,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )

    if send_now_flag:
        mark_sent(state, "NOW", now_ts)
    if send_forecast_flag:
        mark_sent(state, "FORECAST", now_ts)
        mark_forecast_peak(state, kp_fc_time)

    save_state(state_file, state)
    print(f"📧 Wysłano alert do: {', '.join(recipients)} | Subject: {subject}")


if __name__ == "__main__":
    main()
