"""
Load dan simpan sesi multi-phase ke disk.
Sesi menyimpan kumpulan test_id yang termasuk dalam satu sesi pengujian multi-fase.
"""

import json
import logging
import os
import threading

import config

_sessions_lock = threading.Lock()


def _sessions_file():
    # Path file penyimpanan sesi — di dalam RESULTS_DIR supaya ikut ter-backup
    return os.path.join(config.RESULTS_DIR, 'multiphase_sessions.json')


def load_sessions():
    # Kembalikan list sesi dari disk, atau list kosong kalau file belum ada / rusak
    f = _sessions_file()
    if not os.path.exists(f):
        return []
    try:
        with open(f, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except Exception as e:
        logging.warning(f"⚠️ [SESSION] File sesi rusak atau tidak bisa dibaca, mulai dengan list kosong: {e}")
        return []


def save_sessions(sessions):
    # Tulis langsung, tidak perlu atomic rename karena data ini tidak kritis
    with open(_sessions_file(), 'w', encoding='utf-8') as fh:
        json.dump(sessions, fh, ensure_ascii=False, indent=2)
