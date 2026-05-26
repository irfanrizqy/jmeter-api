"""
Endpoint untuk generate dan download CSV per-request.
CSV ini besar dan butuh waktu untuk di-generate dari JTL,
makanya dibuat async dengan status polling terpisah.
"""

import os
import threading

from flask import Blueprint, current_app, jsonify, send_file

import config
import state
from storage.persistence import save_metadata_async
from jmeter.csv_writer import stream_request_csv_to_file

csv_bp = Blueprint('csv', __name__)


@csv_bp.route('/api/load-test/results/<test_id>/requests-csv/generate', methods=['POST'])
def generate_requests_csv(test_id):
    # Trigger generate CSV per-request di background thread.
    # Kalau sudah ready (dan file masih ada dengan format baru), langsung return ready.
    # Kalau file hilang atau format lama (comma), reset dan generate ulang.
    with state.tests_lock:
        if test_id not in state.running_tests:
            return jsonify({'status': 'error', 'message': f'Test {test_id} not found'}), 404

        test = state.running_tests[test_id]
        if test['status'] not in [config.STATUS_COMPLETED, config.STATUS_FAILED]:
            return jsonify({'status': 'error', 'message': 'Test not completed'}), 400

        if test.get('parameters', {}).get('no_jtl'):
            return jsonify({'status': 'error', 'message': 'Test ini tidak memiliki JTL (mode Hemat Disk)'}), 400

        csv_status = test.get('csv_request_status', 'idle')
        if csv_status == 'generating':
            return jsonify({'status': 'generating'}), 200

        if csv_status == 'ready':
            existing_file = test.get('requests_csv_file')
            file_ok = False
            if existing_file and os.path.exists(existing_file):
                try:
                    with open(existing_file, 'rb') as _f:
                        # BOM UTF-8 di awal file = tanda format baru (semicolon delimiter)
                        file_ok = _f.read(3) == b'\xef\xbb\xbf'
                except OSError:
                    pass
            if file_ok:
                return jsonify({'status': 'ready'}), 200
            test['csv_request_status'] = 'idle'

        test['csv_request_status'] = 'generating'
        params       = test.get('parameters', {})
        results_file = test.get('results_file')
        if results_file:
            test_dir = os.path.dirname(results_file)
        else:
            # Test di-recover dari disk, results_file tidak ada di memory
            test_dir = os.path.join(config.RESULTS_DIR, test_id)
            candidate = os.path.join(test_dir, "results.jtl")
            if os.path.exists(candidate):
                results_file = candidate

    app_ref = current_app._get_current_object()

    def _do_generate():
        try:
            app_ref.logger.info(f"📝 [CSV] Mulai generate CSV per-request: {test_id}")
            os.makedirs(test_dir, exist_ok=True)
            requests_csv_file = os.path.join(test_dir, "requests.csv")

            row_count = stream_request_csv_to_file(app_ref, test_id, params, results_file, requests_csv_file)
            if row_count < 0:
                raise RuntimeError("stream_request_csv_to_file gagal")

            with state.tests_lock:
                state.running_tests[test_id]['requests_csv_file']  = requests_csv_file
                state.running_tests[test_id]['request_count']      = row_count
                state.running_tests[test_id]['csv_request_status'] = 'ready'
            size_mb = round(os.path.getsize(requests_csv_file) / (1024 * 1024), 1) if os.path.exists(requests_csv_file) else 0
            app_ref.logger.info(f"✅ [CSV] Generate selesai: {test_id} | {row_count} baris | {size_mb} MB")
            save_metadata_async(app_ref)
        except Exception as e:
            app_ref.logger.error(f"❌ [CSV] Generate CSV per-request gagal untuk {test_id}: {e}", exc_info=True)
            with state.tests_lock:
                if test_id in state.running_tests:
                    state.running_tests[test_id]['csv_request_status'] = 'error'

    threading.Thread(target=_do_generate, daemon=True).start()
    return jsonify({'status': 'generating'}), 202


@csv_bp.route('/api/load-test/results/<test_id>/requests-csv/status', methods=['GET'])
def requests_csv_status(test_id):
    # Cek apakah CSV sudah selesai di-generate.
    # Kalau state di memory tidak 'ready' tapi file sudah ada di disk (misalnya setelah restart), auto-update state.
    with state.tests_lock:
        if test_id not in state.running_tests:
            return jsonify({'status': 'error', 'message': f'Test {test_id} not found'}), 404
        csv_status = state.running_tests[test_id].get('csv_request_status', 'idle')

    if csv_status not in ('ready', 'generating'):
        fallback = os.path.join(config.RESULTS_DIR, test_id, 'requests.csv')
        if os.path.exists(fallback):
            with state.tests_lock:
                if test_id in state.running_tests:
                    state.running_tests[test_id]['requests_csv_file'] = fallback
                    state.running_tests[test_id]['csv_request_status'] = 'ready'
            csv_status = 'ready'

    extra = {}
    with state.tests_lock:
        csv_file = state.running_tests.get(test_id, {}).get('requests_csv_file') if test_id in state.running_tests else None
    if not csv_file:
        csv_file = os.path.join(config.RESULTS_DIR, test_id, 'requests.csv')
    if os.path.exists(csv_file):
        extra['size_mb']   = round(os.path.getsize(csv_file) / (1024 * 1024), 1)
        extra['file_path'] = csv_file

    return jsonify({'status': csv_status, **extra}), 200


@csv_bp.route('/api/load-test/results/<test_id>/requests-csv/download', methods=['GET'])
def download_requests_csv(test_id):
    # Serve file CSV yang sudah di-generate. Kalau path di memory tidak valid,
    # coba fallback ke lokasi standar di test_dir.
    with state.tests_lock:
        if test_id not in state.running_tests:
            return jsonify({'status': 'error', 'message': f'Test {test_id} not found'}), 404
        test              = state.running_tests[test_id]
        csv_status        = test.get('csv_request_status', 'idle')
        requests_csv_file = test.get('requests_csv_file')

    if csv_status == 'generating':
        return jsonify({'status': 'error', 'message': 'CSV masih diproses, harap tunggu'}), 400

    if not requests_csv_file or not os.path.exists(requests_csv_file):
        fallback = os.path.join(config.RESULTS_DIR, test_id, 'requests.csv')
        if os.path.exists(fallback):
            requests_csv_file = fallback
            with state.tests_lock:
                if test_id in state.running_tests:
                    state.running_tests[test_id]['requests_csv_file'] = fallback
                    state.running_tests[test_id]['csv_request_status'] = 'ready'
            current_app.logger.info(f"⚠️ [CSV] Path CSV di memory tidak valid, pakai fallback path untuk {test_id}: {fallback}")

    if not requests_csv_file or not os.path.exists(requests_csv_file):
        return jsonify({'status': 'error', 'message': 'CSV file not found on disk'}), 404

    if not os.access(requests_csv_file, os.R_OK):
        current_app.logger.error(f"🚨 [CSV] Permission denied saat baca CSV {test_id}: {requests_csv_file}")
        return jsonify({'status': 'error', 'message': 'CSV file tidak bisa dibaca (permission denied)'}), 500

    try:
        return send_file(requests_csv_file, mimetype='text/csv',
                         as_attachment=True, download_name=f'{test_id}_requests.csv')
    except Exception as e:
        current_app.logger.error(f"❌ [CSV] send_file gagal untuk {test_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Gagal membaca file CSV'}), 500
