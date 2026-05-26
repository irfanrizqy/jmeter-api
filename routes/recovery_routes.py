"""
Endpoint untuk recovery test dari disk.
Berguna setelah server restart atau kalau ada test yang tidak muncul di list
padahal foldernya masih ada.
"""

from flask import Blueprint, current_app, jsonify

import state
from storage.persistence import save_metadata_async
from storage.recovery import load_test_from_disk, scan_and_recover_all_tests

recovery_bp = Blueprint('recovery', __name__)


@recovery_bp.route('/api/load-test/restore', methods=['POST'])
def restore_tests():
    # Scan seluruh test_results/ dan load semua test yang belum ada di memory
    try:
        recovered = scan_and_recover_all_tests(current_app._get_current_object())
        return jsonify({
            'status':      'success',
            'message':     f'Restored {recovered} tests from disk',
            'total_tests': len(state.running_tests)
        }), 200
    except Exception as e:
        current_app.logger.error(f"Error restoring: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@recovery_bp.route('/api/load-test/reload/<test_id>', methods=['POST'])
def reload_test(test_id):
    # Load ulang satu test spesifik dari disk ke memory
    try:
        test = load_test_from_disk(current_app._get_current_object(), test_id)
        if not test:
            return jsonify({'status': 'error', 'message': f'Test {test_id} not found on disk'}), 404

        with state.tests_lock:
            state.running_tests[test_id] = test

        save_metadata_async(current_app._get_current_object())
        return jsonify({
            'status':  'success',
            'message': f'Test {test_id} reloaded',
            'test':    {'test_id': test_id, 'status': test['status']}
        }), 200
    except Exception as e:
        current_app.logger.error(f"Error reloading {test_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
