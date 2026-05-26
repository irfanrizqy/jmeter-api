"""
Gabungkan CSV dari beberapa fase test menjadi satu file.
Dipakai untuk skenario multi-phase (misalnya 3 fase traffic berbeda dalam satu sesi).
File output disimpan di merged_results/ dengan nama deterministik dari hash IDs
supaya kalau request datang lagi dengan kombinasi fase yang sama, file bisa langsung di-serve ulang.
"""

import csv
import hashlib
import io
import json
import os

import config
import state
from jmeter.csv_writer import generate_tidy_csv_text


def _ids_hash(test_ids):
    # Hash sorted IDs supaya urutan tidak pengaruhi nama file
    key = ','.join(sorted(test_ids))
    return hashlib.md5(key.encode()).hexdigest()[:8]


def _load_test_data(test_id):
    # Coba ambil dari memory dulu, kalau tidak ada baca summary.json dari disk
    with state.tests_lock:
        if test_id in state.running_tests:
            return dict(state.running_tests[test_id])

    summary_file = os.path.join(config.RESULTS_DIR, test_id, 'summary.json')
    if not os.path.exists(summary_file):
        return None

    with open(summary_file, 'r', encoding='utf-8') as sf:
        data = json.load(sf)
    return {
        'status':     data.get('status', ''),
        'parameters': data.get('parameters', {}),
        'results':    data.get('results', {}),
        'start_time': data.get('start_time'),
        'end_time':   data.get('end_time'),
    }


def build_merged_summary_csv(test_ids):
    # Merge summary CSV tiap fase, tambah kolom 'phase', dan baris TOTAL di akhir.
    # Kalau file dengan kombinasi IDs yang sama sudah ada, langsung return tanpa regenerasi.
    # Return (out_path, out_filename, missing_ids).
    # Raise RuntimeError kalau tidak ada satu pun fase yang punya data.
    out_dir = os.path.join(config.RESULTS_DIR, 'merged_results')
    os.makedirs(out_dir, exist_ok=True)

    h            = _ids_hash(test_ids)
    out_filename = f'multiphase_{len(test_ids)}phases_{h}_summary.csv'
    out_path     = os.path.join(out_dir, out_filename)

    if os.path.exists(out_path):
        return out_path, out_filename, []

    fieldnames = [
        'phase', 'test_id', 'status', 'target_url', 'num_threads', 'ramp_time',
        'duration_seconds', 'http_path', 'timestamp_seconds',
        'timeline_response_time_ms', 'timeline_throughput_rps',
        'total_requests', 'success_requests', 'error_requests',
        'error_rate_pct', 'success_rate_pct',
        'throughput_avg_rps', 'bandwidth_received_kbps', 'bandwidth_sent_kbps',
        'response_time_avg_ms', 'response_time_min_ms', 'response_time_max_ms',
        'response_time_median_ms', 'response_time_90th_ms', 'response_time_95th_ms',
        'start_time', 'end_time',
    ]

    def _pf(v):
        # Parse float dari nilai yang mungkin sudah pakai koma (format Indonesia)
        try:
            return float(str(v).replace(',', '.')) if v is not None else 0.0
        except Exception:
            return 0.0

    def _iso(val):
        if val is None:
            return ''
        return val.isoformat() if hasattr(val, 'isoformat') else str(val)

    def _fmt_f(v):
        return str(round(v, 4)).replace('.', ',')

    all_rows  = []
    missing   = []
    phase_agg = []

    for phase_idx, test_id in enumerate(test_ids):
        phase_label = f'fase_{phase_idx + 1}'
        test = _load_test_data(test_id)

        if test is None:
            missing.append(test_id)
            continue

        results   = test.get('results', {})
        params    = test.get('parameters', {})
        total_req = int(results.get('total_requests') or 0)

        phase_agg.append({
            'total_requests':          total_req,
            'success_requests':        int(results.get('success_requests') or 0),
            'error_requests':          int(results.get('error_requests') or 0),
            'duration_seconds':        int(params.get('duration') or 0),
            'throughput_avg_rps':      _pf(results.get('throughput')),
            'bandwidth_received_kbps': _pf(results.get('bandwidth_received')),
            'bandwidth_sent_kbps':     _pf(results.get('bandwidth_sent')),
            'response_time_avg_ms':    _pf(results.get('response_time_avg')),
            'response_time_min_ms':    _pf(results.get('response_time_min')),
            'response_time_max_ms':    _pf(results.get('response_time_max')),
            'start_time':              test.get('start_time'),
            'end_time':                test.get('end_time'),
        })

        # Ambil baris dari summary CSV fase ini, sisipkan kolom phase
        csv_text = generate_tidy_csv_text(test_id, test)
        lines    = [l for l in csv_text.lstrip('﻿').splitlines()
                    if l and not l.startswith('sep=')]
        reader   = csv.DictReader(io.StringIO('\n'.join(lines)), delimiter=';')
        for row in reader:
            row['phase'] = phase_label
            all_rows.append(row)

    if not all_rows:
        detail = f"Fase yang hilang: {', '.join(missing)}" if missing else ''
        raise RuntimeError(f'Tidak ada data dari fase manapun. {detail}'.strip())

    total_req_sum = sum(p['total_requests']  for p in phase_agg)
    success_sum   = sum(p['success_requests'] for p in phase_agg)
    error_sum     = sum(p['error_requests']   for p in phase_agg)
    duration_sum  = sum(p['duration_seconds'] for p in phase_agg)

    def _wavg(field):
        # Weighted average — bobot berdasarkan jumlah request per fase
        if total_req_sum == 0:
            return '-'
        return _fmt_f(sum(p[field] * p['total_requests'] for p in phase_agg) / total_req_sum)

    err_rate = _fmt_f((error_sum / total_req_sum) * 100) if total_req_sum else ''
    suc_rate = _fmt_f((success_sum / total_req_sum) * 100) if total_req_sum else ''
    rt_min   = min((p['response_time_min_ms'] for p in phase_agg), default=0)
    rt_max   = max((p['response_time_max_ms'] for p in phase_agg), default=0)
    starts   = [p['start_time'] for p in phase_agg if p['start_time']]
    ends     = [p['end_time']   for p in phase_agg if p['end_time']]

    total_row = {
        'phase':                     'TOTAL',
        'test_id':                   '-', 'status': '-', 'target_url': '-',
        'num_threads':               '-', 'ramp_time': '-',
        'duration_seconds':          duration_sum,
        'http_path':                 '-', 'timestamp_seconds': '-',
        'timeline_response_time_ms': '-', 'timeline_throughput_rps': '-',
        'total_requests':            total_req_sum,
        'success_requests':          success_sum,
        'error_requests':            error_sum,
        'error_rate_pct':            err_rate,
        'success_rate_pct':          suc_rate,
        'throughput_avg_rps':        _wavg('throughput_avg_rps'),
        'bandwidth_received_kbps':   _wavg('bandwidth_received_kbps'),
        'bandwidth_sent_kbps':       _wavg('bandwidth_sent_kbps'),
        'response_time_avg_ms':      _wavg('response_time_avg_ms'),
        'response_time_min_ms':      _fmt_f(rt_min),
        'response_time_max_ms':      _fmt_f(rt_max),
        'response_time_median_ms':   '-',
        'response_time_90th_ms':     '-',
        'response_time_95th_ms':     '-',
        'start_time':                _iso(min(starts, key=str)) if starts else '',
        'end_time':                  _iso(max(ends,   key=str)) if ends   else '',
    }
    all_rows.append(total_row)

    with open(out_path, 'w', newline='', encoding='utf-8-sig') as f:
        f.write('sep=;\n')
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';', extrasaction='ignore')
        writer.writeheader()
        writer.writerows(all_rows)

    return out_path, out_filename, missing


def build_merged_requests_csv(test_ids):
    # Gabungkan requests.csv per fase menjadi satu file besar, tambah kolom 'phase'.
    # Header hanya ditulis sekali dari fase pertama yang punya file.
    # Return (out_path, out_filename, missing_ids).
    # Raise RuntimeError kalau tidak ada satu pun fase yang punya requests.csv.
    out_dir = os.path.join(config.RESULTS_DIR, 'merged_results')
    os.makedirs(out_dir, exist_ok=True)

    h            = _ids_hash(test_ids)
    out_filename = f'multiphase_{len(test_ids)}phases_{h}_requests.csv'
    out_path     = os.path.join(out_dir, out_filename)

    if os.path.exists(out_path):
        return out_path, out_filename, []

    missing       = []
    merged_header = None

    with open(out_path, 'wb') as out:
        out.write(b'\xef\xbb\xbf')  # BOM supaya Excel deteksi UTF-8
        out.write(b'sep=;\n')

        for phase_idx, test_id in enumerate(test_ids):
            csv_path = os.path.join(config.RESULTS_DIR, test_id, 'requests.csv')
            if not os.path.exists(csv_path):
                missing.append(test_id)
                continue

            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                first_line = True
                for raw_line in f:
                    line = raw_line.rstrip('\r\n')
                    if not line or line.startswith('sep='):
                        continue
                    if first_line:
                        first_line = False
                        if merged_header is None:
                            out.write(f'phase;{line}\n'.encode('utf-8'))
                            merged_header = line
                        continue  # skip header fase berikutnya, sudah ditulis dari fase pertama
                    out.write(f'fase_{phase_idx + 1};{line}\n'.encode('utf-8'))

    if merged_header is None:
        try:
            os.unlink(out_path)
        except OSError:
            pass
        detail = f"Fase yang hilang: {', '.join(missing)}" if missing else ''
        raise RuntimeError(f'Tidak ada requests.csv dari fase manapun. {detail}'.strip())

    return out_path, out_filename, missing
