"""
Endpoint CRUD untuk sesi multi-phase.
Sesi menyimpan kumpulan test_id yang termasuk dalam satu skenario pengujian bertahap,
supaya bisa di-merge nanti tanpa harus ingat ID tiap fase satu per satu.
"""

from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from storage.sessions import _sessions_lock, load_sessions, save_sessions

sessions_bp = Blueprint('sessions', __name__)


@sessions_bp.route('/api/load-test/sessions', methods=['GET'])
def get_sessions():
    # Kembalikan semua sesi yang tersimpan di disk
    with _sessions_lock:
        sessions = load_sessions()
    return jsonify({'status': 'ok', 'sessions': sessions})


@sessions_bp.route('/api/load-test/sessions', methods=['POST'])
def save_session():
    # Simpan sesi baru di posisi pertama (terbaru di atas), batasi 100 sesi
    data = request.get_json(silent=True) or {}
    if not data.get('test_ids') or not data.get('phase_count'):
        return jsonify({'status': 'error', 'message': 'test_ids dan phase_count wajib'}), 400

    session = {
        'id':           data.get('id') or 'mp_' + datetime.utcnow().strftime('%Y%m%d%H%M%S%f'),
        'test_ids':     data['test_ids'],
        'phase_count':  data['phase_count'],
        'target_url':   data.get('target_url', ''),
        'completed_at': data.get('completed_at', datetime.utcnow().isoformat()),
    }
    with _sessions_lock:
        sessions = load_sessions()
        sessions.insert(0, session)
        if len(sessions) > 100:
            sessions = sessions[:100]
        save_sessions(sessions)

    current_app.logger.info(f"✅ [SESSION] Sesi baru disimpan: {session['id']} | {session['phase_count']} fase | url={session['target_url']}")
    return jsonify({'status': 'ok', 'session': session}), 201


@sessions_bp.route('/api/load-test/sessions/<session_id>', methods=['DELETE'])
def delete_session(session_id):
    # Hapus sesi berdasarkan ID dari file
    with _sessions_lock:
        sessions = load_sessions()
        sessions = [s for s in sessions if s.get('id') != session_id]
        save_sessions(sessions)
    current_app.logger.info(f"🗑️ [SESSION] Sesi dihapus: {session_id}")
    return jsonify({'status': 'ok'})
