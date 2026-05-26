"""
Endpoint utama untuk mengelola test: start, stop, status, results, list.
Semua operasi yang berhubungan langsung dengan lifecycle satu test ada di sini.
"""

import json
import os
import threading
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request, Response

import config
import state
from storage.persistence import save_critical_test_info, save_metadata_async
from storage.recovery import cleanup_old_tests_from_memory
from jmeter.runner import generate_test_id, validate_test_parameters, run_jmeter_test
from jmeter.csv_writer import generate_tidy_csv_text

tests_bp = Blueprint('tests', __name__)


@tests_bp.route('/api/health', methods=['GET'])
def health_check():
    # Cek cepat apakah server masih hidup dan berapa test yang sedang berjalan
    return jsonify({
        'status':                'healthy',
        'timestamp':             datetime.now().isoformat(),
        'jmeter_home':           config.JMETER_HOME,
        'running_tests':         len([t for t in state.running_tests.values()
                                      if t['status'] == config.STATUS_RUNNING]),
        'total_tests_in_memory': len(state.running_tests)
    })


@tests_bp.route('/api/load-test/start', methods=['POST'])
def start_load_test():
    # Validasi parameter, buat entry test di memory, simpan ke disk, lalu jalankan di background thread
    try:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'Request body must be JSON'}), 400

        errors = validate_test_parameters(data)
        if errors:
            return jsonify({'status': 'error', 'message': 'Invalid parameters', 'errors': errors}), 400

        test_id   = generate_test_id()
        test_data = {
            'test_id':      test_id,
            'status':       config.STATUS_PENDING,
            'parameters':   data,
            'created_time': datetime.now()
        }

        with state.tests_lock:
            state.running_tests[test_id] = test_data

        # Simpan segera ke disk sebelum thread dimulai — kalau crash setelah ini, test masih ter-recover
        save_success = save_critical_test_info(current_app._get_current_object(), test_id, test_data)
        if not save_success:
            current_app.logger.warning(f"⚠️ [API] Critical info save gagal untuk {test_id}, test tetap dilanjutkan")

        save_metadata_async(current_app._get_current_object())
        cleanup_old_tests_from_memory(current_app._get_current_object())

        app_ref = current_app._get_current_object()
        threading.Thread(target=run_jmeter_test, args=(app_ref, test_id, data), daemon=True).start()

        return jsonify({'status': 'success', 'test_id': test_id,
                        'message': 'Load test started successfully'}), 200

    except Exception as e:
        current_app.logger.error(f"💥 [API] Gagal start test: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@tests_bp.route('/api/load-test/stop/<test_id>', methods=['POST'])
def stop_load_test(test_id):
    # Kirim SIGTERM ke proses JMeter, tunggu 5 detik, kalau tidak mati paksa kill
    with state.tests_lock:
        if test_id not in state.running_tests:
            return jsonify({'status': 'error', 'message': f'Test {test_id} not found'}), 404

        test = state.running_tests[test_id]
        if test['status'] != config.STATUS_RUNNING:
            return jsonify({'status': 'error', 'message': f'Test {test_id} is not running'}), 400

        if 'process' in test:
            try:
                test['process'].terminate()
                test['process'].wait(timeout=5)
            except Exception:
                test['process'].kill()
                test['process'].communicate()

            test['status']   = config.STATUS_STOPPED
            test['end_time'] = datetime.now()
            del test['process']

    current_app.logger.info(f"🛑 [TEST] Test dihentikan manual: {test_id}")
    save_metadata_async(current_app._get_current_object())
    return jsonify({'status': 'success', 'message': f'Test {test_id} stopped'}), 200


@tests_bp.route('/api/load-test/status/<test_id>', methods=['GET'])
def get_test_status(test_id):
    # Kembalikan status test + persentase progress kalau masih running
    with state.tests_lock:
        if test_id not in state.running_tests:
            return jsonify({'status': 'error', 'message': f'Test {test_id} not found'}), 404
        test = state.running_tests[test_id]

        response = {
            'test_id':    test_id,
            'status':     test['status'],
            'parameters': test['parameters']
        }

        if test['status'] == config.STATUS_RUNNING and 'start_time' in test:
            duration = test['parameters'].get('duration', config.DEFAULT_DURATION)
            elapsed  = (datetime.now() - test['start_time']).total_seconds()
            response['progress']     = round(min(100, (elapsed / duration) * 100), 1)
            response['elapsed_time'] = round(elapsed, 1)

        return jsonify(response), 200


def _load_results_from_disk(test_id, test):
    # Kalau results tidak ada di memory (misalnya setelah server restart), coba baca dari summary.json.
    # Setelah berhasil, warm-up memory supaya request berikutnya tidak perlu baca disk lagi.
    summary_file = os.path.join(config.RESULTS_DIR, test_id, 'summary.json')
    if not os.path.exists(summary_file):
        return

    try:
        with open(summary_file, 'r') as f:
            disk_data = json.load(f)

        results = disk_data.get('results')
        if not results:
            return

        test['results'] = results
        for field in ['start_time', 'end_time']:
            if not test.get(field):
                raw = disk_data.get(field)
                if raw:
                    try:
                        test[field] = datetime.fromisoformat(raw)
                    except Exception:
                        pass

        with state.tests_lock:
            if test_id in state.running_tests:
                state.running_tests[test_id]['results'] = results

    except Exception as e:
        current_app.logger.error(f"🚨 [PERSIST] Gagal baca summary.json untuk {test_id}: {e}")


@tests_bp.route('/api/load-test/results/<test_id>', methods=['GET'])
def get_test_results(test_id):
    # Kembalikan hasil test. Kalau parse thread belum selesai, kembalikan 202 processing.
    # Strip field internal (response_times, timestamps, dll.) yang besar dan tidak dipakai frontend.
    with state.tests_lock:
        if test_id not in state.running_tests:
            return jsonify({'status': 'error', 'message': f'Test {test_id} not found'}), 404
        test = state.running_tests[test_id].copy()

    if test['status'] not in [config.STATUS_COMPLETED, config.STATUS_FAILED]:
        return jsonify({'status': 'error', 'message': f'Test {test_id} is not completed yet'}), 400

    if 'results' not in test:
        _load_results_from_disk(test_id, test)

    if test['status'] == config.STATUS_COMPLETED and 'results' not in test:
        return jsonify({'status': 'processing', 'message': 'Test selesai, sedang memproses hasil...'}), 202

    _INTERNAL = {'response_times', 'bytes_received', 'bytes_sent', 'timestamps'}
    response = {
        'test_id':    test_id,
        'status':     test['status'],
        'parameters': test.get('parameters', {}),
    }
    if 'results' in test:
        response['summary'] = {k: v for k, v in test['results'].items() if k not in _INTERNAL}

    st = test.get('start_time')
    et = test.get('end_time')
    if st and et:
        response['start_time'] = st.isoformat() if isinstance(st, datetime) else st
        response['end_time']   = et.isoformat() if isinstance(et, datetime) else et
        if isinstance(st, datetime) and isinstance(et, datetime):
            response['total_time'] = (et - st).total_seconds()

    return jsonify(response), 200


@tests_bp.route('/api/load-test/results/<test_id>/csv', methods=['GET'])
def get_test_results_csv(test_id):
    # Download summary test sebagai CSV dengan format Excel Indonesia (semicolon delimiter, koma desimal)
    with state.tests_lock:
        if test_id not in state.running_tests:
            return jsonify({'status': 'error', 'message': f'Test {test_id} not found'}), 404
        test = state.running_tests[test_id].copy()

    if test['status'] not in [config.STATUS_COMPLETED, config.STATUS_FAILED]:
        return jsonify({'status': 'error', 'message': f'Test {test_id} is not completed yet'}), 400

    if 'results' not in test:
        _load_results_from_disk(test_id, test)

    if 'results' not in test:
        return jsonify({'status': 'error', 'message': f'No results available for test {test_id}'}), 400

    try:
        csv_text = generate_tidy_csv_text(test_id, test)
    except Exception as e:
        current_app.logger.error(f"❌ [CSV] Gagal generate summary CSV untuk {test_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Gagal generate CSV'}), 500

    return Response(
        csv_text,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={test_id}.csv'}
    )


@tests_bp.route('/api/load-test/list', methods=['GET'])
def list_tests():
    # Snapshot semua test dari memory, kembalikan info ringkas tanpa data besar
    with state.tests_lock:
        snapshot = [dict(test, _id=tid) for tid, test in state.running_tests.items()]

    def _iso(v):
        return v.isoformat() if isinstance(v, datetime) else v

    tests = []
    for test in snapshot:
        test_id = test['_id']
        params  = test.get('parameters', {})
        results = test.get('results')
        tests.append({
            'test_id':      test_id,
            'status':       test['status'],
            'created_time': _iso(test.get('created_time')),
            'start_time':   _iso(test.get('start_time')),
            'end_time':     _iso(test.get('end_time')),
            'target_url':   params.get('target_url', ''),
            'parameters': {
                'num_threads': params.get('num_threads'),
                'ramp_time':   params.get('ramp_time'),
                'duration':    params.get('duration'),
                'http_path':   params.get('http_path'),
                'no_jtl':      params.get('no_jtl', False),
            },
            'summary': {
                'response_time_avg': results.get('response_time_avg'),
                'error_rate':        results.get('error_rate'),
                'throughput':        results.get('throughput'),
                'total_requests':    results.get('total_requests'),
                'success_requests':  results.get('success_requests'),
                'error_requests':    results.get('error_requests'),
                'no_jtl':            results.get('no_jtl', False),
            } if results else None,
        })

    return jsonify({'status': 'success', 'tests': tests, 'total': len(tests)}), 200
