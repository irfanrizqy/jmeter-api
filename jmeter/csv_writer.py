"""
Generate CSV dari hasil test — baik summary (per-test) maupun per-request.
CSV per-request di-join ke qlearning history supaya tiap baris tahu
backend mana yang dipilih Q-Learning saat request itu dikirim.
"""

import csv
import io
import os
from datetime import datetime

from jmeter.formatting import _fmt, _safe_int, _to_iso
from jmeter.qlearning_history import load_qlearning_history, find_qlearning_decision

# Kolom tetap untuk summary CSV (satu baris per titik waktu)
SUMMARY_FIELDNAMES = [
    "test_id", "status", "target_url", "num_threads", "ramp_time",
    "duration_seconds", "http_path", "timestamp_seconds",
    "timeline_response_time_ms", "timeline_request_throughput_rps",
    "total_requests", "success_requests", "error_requests",
    "error_rate_pct", "success_rate_pct", "request_throughput_avg_rps",
    "data_throughput_received_KBps", "data_throughput_sent_KBps",
    "response_time_avg_ms", "response_time_min_ms", "response_time_max_ms",
    "response_time_median_ms", "response_time_90th_ms", "response_time_95th_ms",
    "start_time", "end_time",
]

# Kolom tetap untuk CSV per-request
REQUEST_FIELDNAMES = [
    "test_id", "request_no", "timestamp", "elapsed_ms",
    "target_url", "http_path", "label", "thread_name",
    "selected_cycle", "selected_mode", "selected_server", "selected_server_ip",
    "qlearning_window_start", "qlearning_window_end",
    "response_time_ms", "latency_ms", "connect_time_ms",
    "bytes_received", "bytes_sent",
    "response_code", "response_message", "success",
]

# Kolom yang nilainya float dan perlu diformat koma-desimal untuk Excel Indonesia
FLOAT_FIELDS = {
    "timeline_response_time_ms", "error_rate_pct", "success_rate_pct",
    "request_throughput_avg_rps",
    "data_throughput_received_KBps", "data_throughput_sent_KBps",
    "response_time_avg_ms", "response_time_min_ms", "response_time_max_ms",
    "response_time_median_ms", "response_time_90th_ms", "response_time_95th_ms",
}


def build_tidy_csv_rows(test_id, test):
    # Susun baris-baris CSV summary. Kalau ada timeline, satu baris per detik.
    # Kalau tidak ada (mode no_jtl), cukup satu baris berisi aggregat saja.
    params  = test.get('parameters', {})
    results = test.get('results', {})

    total_requests   = results.get('total_requests')
    success_requests = results.get('success_requests')

    success_rate = None
    if total_requests not in (None, 0) and success_requests is not None:
        success_rate = round((success_requests / total_requests) * 100, 4)

    common = {
        "test_id":                  test_id,
        "status":                   test.get("status"),
        "target_url":               params.get("target_url"),
        "num_threads":              params.get("num_threads"),
        "ramp_time":                params.get("ramp_time"),
        "duration_seconds":         params.get("duration"),
        "http_path":                params.get("http_path"),
        "total_requests":           total_requests,
        "success_requests":         success_requests,
        "error_requests":           results.get('error_requests'),
        "error_rate_pct":           results.get('error_rate'),
        "success_rate_pct":         success_rate,
        "request_throughput_avg_rps":      results.get('throughput'),
        "data_throughput_received_KBps":   results.get('bandwidth_received'),
        "data_throughput_sent_KBps":       results.get('bandwidth_sent'),
        "response_time_avg_ms":     results.get('response_time_avg'),
        "response_time_min_ms":     results.get('response_time_min'),
        "response_time_max_ms":     results.get('response_time_max'),
        "response_time_median_ms":  results.get('response_time_median'),
        "response_time_90th_ms":    results.get('response_time_90percentile'),
        "response_time_95th_ms":    results.get('response_time_95percentile'),
        "start_time":               _to_iso(test.get("start_time")),
        "end_time":                 _to_iso(test.get("end_time")),
    }

    timeline = results.get('timeline', [])
    if isinstance(timeline, list) and timeline:
        return [
            {**common,
             "timestamp_seconds":         p.get("timestamp"),
             "timeline_response_time_ms": p.get("response_time"),
             "timeline_request_throughput_rps":   p.get("throughput")}
            for p in timeline
        ]

    return [{**common, "timestamp_seconds": None,
             "timeline_response_time_ms": None, "timeline_request_throughput_rps": None}]


def generate_tidy_csv_text(test_id, test):
    # Hasilkan string CSV lengkap dengan BOM + hint separator untuk Excel Indonesia
    raw_rows = build_tidy_csv_rows(test_id, test)
    rows = [
        {k: (_fmt(v) if k in FLOAT_FIELDS else ('' if v is None else v)) for k, v in row.items()}
        for row in raw_rows
    ]

    output = io.StringIO()
    output.write('﻿')   # BOM supaya Excel otomatis deteksi UTF-8
    output.write('sep=;\n')  # Hint separator untuk Excel versi Indonesia
    writer = csv.DictWriter(output, fieldnames=SUMMARY_FIELDNAMES, delimiter=';')
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def stream_request_csv_to_file(app, test_id, params, results_file, output_path):
    # Baca JTL per baris langsung tulis ke file — tidak load semua ke memory.
    # Aman untuk JTL besar (test durasi 300s ke atas bisa ratusan ribu baris).
    # Pass 1: scan timestamps untuk cari min_ts (keperluan hitung elapsed_ms).
    # Pass 2: baca ulang, join ke qlearning history, tulis ke CSV.
    # Return jumlah baris ditulis, atau -1 kalau error.
    if not results_file or not os.path.exists(results_file):
        app.logger.warning(f"⚠️ [CSV] JTL tidak ditemukan untuk generate CSV per-request: {results_file}")
        return 0

    qlearning_history = load_qlearning_history(app)

    try:
        min_ts = None
        with open(results_file, 'r', newline='') as fin:
            for row in csv.DictReader(fin):
                ts = _safe_int(row.get('timeStamp'), 0)
                if ts and (min_ts is None or ts < min_ts):
                    min_ts = ts

        row_count = 0
        with open(results_file, 'r', newline='') as fin, \
             open(output_path, 'w', newline='', encoding='utf-8-sig') as fout:

            fout.write('sep=;\n')
            writer = csv.DictWriter(fout, fieldnames=REQUEST_FIELDNAMES, delimiter=';',
                                    extrasaction='ignore')
            writer.writeheader()

            for idx, row in enumerate(csv.DictReader(fin), start=1):
                ts_ms      = _safe_int(row.get('timeStamp'), 0)
                request_dt = datetime.fromtimestamp(ts_ms / 1000) if ts_ms else None
                decision   = (
                    find_qlearning_decision(request_dt, qlearning_history)
                    if request_dt else None
                )
                success = row.get('success', 'true').lower() == 'true'

                writer.writerow({
                    'test_id':                test_id,
                    'request_no':             idx,
                    'timestamp':              request_dt.isoformat() if request_dt else '',
                    'elapsed_ms':             (ts_ms - min_ts) if (ts_ms and min_ts is not None) else '',
                    'target_url':             params.get('target_url', ''),
                    'http_path':              params.get('http_path', ''),
                    'label':                  row.get('label', ''),
                    'thread_name':            row.get('threadName', ''),
                    'selected_cycle':         decision.get('cycle', '')                if decision else '',
                    'selected_mode':          decision.get('action_mode', '')          if decision else '',
                    'selected_server':        decision.get('selected_backend_name', '') if decision else '',
                    'selected_server_ip':     (decision.get('selected_backend_ip') or
                                               decision.get('selected_backend', ''))   if decision else '',
                    'qlearning_window_start': decision.get('cycle_started_at', '')    if decision else '',
                    'qlearning_window_end':   decision.get('cycle_ended_at', '')      if decision else '',
                    'response_time_ms':       _safe_int(row.get('elapsed'), 0),
                    'latency_ms':             _safe_int(row.get('latency'), 0),
                    'connect_time_ms':        _safe_int(row.get('connect'), 0),
                    'bytes_received':         _safe_int(row.get('bytes'), 0),
                    'bytes_sent':             _safe_int(row.get('sentBytes'), 0),
                    'response_code':          row.get('responseCode') or row.get('code', ''),
                    'response_message':       row.get('responseMessage') or row.get('message', ''),
                    'success':                1 if success else 0,
                })
                row_count += 1

        size_mb = round(os.path.getsize(output_path) / (1024 * 1024), 1) if os.path.exists(output_path) else 0
        app.logger.info(f"✅ [CSV] CSV per-request selesai: {test_id} | {row_count} baris | {size_mb} MB")
        return row_count

    except Exception as e:
        app.logger.error(f"❌ [CSV] Gagal streaming CSV per-request untuk {test_id}: {e}", exc_info=True)
        return -1
