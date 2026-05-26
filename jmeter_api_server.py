#!/usr/bin/env python3
"""
Entry point JMeter API Server.
Startup sequence: load metadata dari disk → recover test dari disk → jalankan Flask.
Auto-recovery memastikan test yang ada sebelum restart tetap terlihat di dashboard.
"""

import logging
import os
import signal
import sys
import threading

from flask import Flask, request
from werkzeug.middleware.proxy_fix import ProxyFix

import config
import state
from storage.persistence import periodic_metadata_save, save_metadata
from storage.recovery import load_metadata, scan_and_recover_all_tests
from routes.tests import tests_bp
from routes.csv_routes import csv_bp
from routes.csv_merge_routes import csv_merge_bp
from routes.sessions import sessions_bp
from routes.disk import disk_bp
from routes.recovery_routes import recovery_bp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

app = Flask(__name__)
app.logger.setLevel(logging.INFO)

# Percaya pada header proxy dari Nginx/reverse proxy untuk dapat IP asli client
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

app.register_blueprint(tests_bp)
app.register_blueprint(csv_bp)
app.register_blueprint(csv_merge_bp)
app.register_blueprint(sessions_bp)
app.register_blueprint(disk_bp)
app.register_blueprint(recovery_bp)


@app.before_request
def log_request():
    # DEBUG supaya tidak banjiri journalctl — aktif kalau butuh trace request
    real_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    app.logger.debug(f"[HTTP] {request.method} {request.path} from {real_ip}")


def signal_handler(sig, frame):
    # Simpan metadata sebelum mati supaya recovery saat restart lebih akurat
    app.logger.info(f"🛑 [SHUTDOWN] Signal {sig} diterima — flush metadata ke disk sebelum exit")
    state.shutdown_flag = True
    save_metadata(app)
    app.logger.info("🛑 [SHUTDOWN] Metadata tersimpan, server berhenti")
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


if __name__ == '__main__':
    os.makedirs(config.RESULTS_DIR, exist_ok=True)
    os.makedirs(config.LOGS_DIR, exist_ok=True)

    load_metadata(app)
    scan_and_recover_all_tests(app)

    threading.Thread(
        target=periodic_metadata_save,
        args=(app,),
        daemon=True,
        name='periodic-backup'
    ).start()
    app.logger.info("Periodic backup thread started (every 60s)")
    app.logger.info(f"Server starting on port {config.FLASK_PORT}...")
    app.logger.info(f"Results: {config.RESULTS_DIR} | JMeter: {config.JMETER_HOME}")
    app.logger.info(f"Tests in memory: {len(state.running_tests)}")

    app.run(host=config.FLASK_HOST, port=config.FLASK_PORT, debug=config.FLASK_DEBUG)
