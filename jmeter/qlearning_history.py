"""
Ambil dan cari data routing history Q-Learning dari Redis.
Dipakai saat generate CSV per-request untuk tahu backend mana yang dipilih
pada saat request itu terjadi.
"""

import json
from datetime import datetime

import redis
import config


def load_qlearning_history(app):
    # Coba routing_log dulu — ditulis setiap cycle terlepas dari training gate.
    # Kalau kosong, fallback ke qlearning_history yang hanya ditulis saat training aktif.
    try:
        client = redis.Redis(
            host=config.QLEARNING_REDIS_HOST,
            port=config.QLEARNING_REDIS_PORT,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2
        )
        raw_entries = client.lrange("qlearning_routing_log", 0, -1)
        if not raw_entries:
            raw_entries = client.lrange("qlearning_history", 0, -1)

        entries = []
        for raw in raw_entries:
            try:
                item = json.loads(raw)
                start_raw = item.get("cycle_started_at")
                end_raw   = item.get("cycle_ended_at")
                if not start_raw or not end_raw:
                    continue
                # Parse sekali di sini biar find_qlearning_decision tidak parse berulang
                item["_cycle_started_dt"] = datetime.fromisoformat(start_raw)
                item["_cycle_ended_dt"]   = datetime.fromisoformat(end_raw)
                entries.append(item)
            except Exception:
                continue
        return entries

    except Exception as e:
        app.logger.warning(f"⚠️ [REDIS] Gagal load qlearning history dari {config.QLEARNING_REDIS_HOST}:{config.QLEARNING_REDIS_PORT} — CSV tidak akan punya kolom Q-Learning: {e}")
        return []


def find_qlearning_decision(request_dt, history):
    # Cari cycle yang window-nya mencakup timestamp request ini.
    # Iterasi terbalik karena request terbaru lebih mungkin cocok dengan entry terbaru.
    for item in reversed(history):
        start_dt = item.get("_cycle_started_dt")
        end_dt   = item.get("_cycle_ended_dt")
        if start_dt and end_dt and start_dt <= request_dt < end_dt:
            return item
    return None
