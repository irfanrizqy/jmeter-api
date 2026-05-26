"""
Eksekusi JMeter test di background thread.
Validasi parameter, jalankan subprocess JMeter, tunggu selesai,
lalu serahkan post-processing ke processor.py.
"""

import os
import re
import subprocess
from datetime import datetime

import config
import state
from storage.persistence import save_critical_test_info, save_metadata_async
from jmeter.cmd_builder import parse_target_url, build_jmeter_cmd
from jmeter.processor import process_results, process_no_jtl


def generate_test_id():
    # Format timestamp supaya ID sudah terurut secara leksikografis
    return f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def validate_test_parameters(params):
    # Validasi semua parameter sebelum test dijalankan.
    # Return list error string — kosong berarti valid.
    errors = []

    try:
        num_threads = int(params.get('num_threads', config.DEFAULT_NUM_THREADS))
        if num_threads < 1:
            errors.append("num_threads must be at least 1")
        if num_threads > config.MAX_THREADS:
            errors.append(f"num_threads cannot exceed {config.MAX_THREADS}")
    except (ValueError, TypeError):
        errors.append("num_threads must be a valid integer")

    try:
        ramp_time = int(params.get('ramp_time', config.DEFAULT_RAMP_TIME))
        if ramp_time < 0:
            errors.append("ramp_time cannot be negative")
    except (ValueError, TypeError):
        errors.append("ramp_time must be a valid integer")

    try:
        duration = int(params.get('duration', config.DEFAULT_DURATION))
        if duration < 1:
            errors.append("duration must be at least 1 second")
        if duration > config.MAX_DURATION:
            errors.append(f"duration cannot exceed {config.MAX_DURATION} seconds")
    except (ValueError, TypeError):
        errors.append("duration must be a valid integer")

    target_url = params.get('target_url')
    if not target_url:
        errors.append("target_url is required")
    elif not (target_url.startswith('http://') or target_url.startswith('https://')):
        errors.append("target_url must start with http:// or https://")

    no_jtl = params.get('no_jtl')
    if no_jtl is not None and not isinstance(no_jtl, bool):
        errors.append("no_jtl must be a boolean")

    return errors


def _parse_stdout_stats(stdout_text):
    # JMeter cetak baris 'summary = ...' berkala dan di akhir test.
    # Ambil yang terakhir sebagai hasil final — baris sebelumnya adalah checkpoint sementara.
    pattern = (
        r'summary =\s+(\d+) in [\d:]+\s+=\s+([\d.]+)/s '
        r'Avg:\s+(\d+) Min:\s+(\d+) Max:\s+(\d+) Err:\s+(\d+) \(([\d.]+)%\)'
    )
    matches = re.findall(pattern, stdout_text)
    if not matches:
        return None

    total_s, rps_s, avg_s, mn_s, mx_s, err_s, err_pct_s = matches[-1]
    total = int(total_s)
    err   = int(err_s)
    return {
        'total_requests':             total,
        'success_requests':           total - err,
        'error_requests':             err,
        'error_rate':                 float(err_pct_s),
        'throughput':                 float(rps_s),
        'response_time_avg':          int(avg_s),
        'response_time_min':          int(mn_s),
        'response_time_max':          int(mx_s),
        'response_time_median':       None,
        'response_time_90percentile': None,
        'response_time_95percentile': None,
        'bandwidth_received':         None,
        'bandwidth_sent':             None,
        'no_jtl':                     True,
    }


def run_jmeter_test(app, test_id, params):
    # Entry point yang dipanggil dari background thread.
    # Siapkan file, jalankan JMeter, tentukan status, lalu trigger post-processing.
    url      = params.get('target_url', '?')
    threads  = params.get('num_threads', '?')
    duration = params.get('duration', '?')
    no_jtl   = bool(params.get('no_jtl', False))
    app.logger.info(f"🚀 [TEST] Mulai: {test_id} | url={url} threads={threads} dur={duration}s no_jtl={no_jtl}")

    try:
        target_host, target_port, http_path = parse_target_url(params['target_url'])

        test_dir = os.path.join(config.RESULTS_DIR, test_id)
        os.makedirs(test_dir, exist_ok=True)
        log_file = os.path.join(test_dir, "jmeter.log")

        if no_jtl:
            results_file = '/dev/null'
        else:
            results_file = os.path.join(test_dir, "results.jtl")
            props_file   = os.path.join(test_dir, "saveservice.properties")
            with open(props_file, 'w') as pf:
                pf.write("jmeter.save.saveservice.response_headers=true\n")
                pf.write("jmeter.save.saveservice.latency=true\n")
                pf.write("jmeter.save.saveservice.connect_time=true\n")

        cmd = build_jmeter_cmd(target_host, target_port, http_path, params, results_file, log_file)
        if not no_jtl:
            cmd.extend(["-q", props_file])

        app.logger.info(f"🔧 [TEST] JMeter command: {' '.join(cmd)}")

        with state.tests_lock:
            state.running_tests[test_id]['status']       = config.STATUS_RUNNING
            state.running_tests[test_id]['start_time']   = datetime.now()
            state.running_tests[test_id]['results_file'] = None if no_jtl else results_file

        save_critical_test_info(app, test_id, state.running_tests[test_id])

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        with state.tests_lock:
            state.running_tests[test_id]['process'] = process

        # Timeout sedikit lebih panjang dari durasi test untuk kasih waktu JMeter shutdown bersih
        _timeout = int(params.get('duration', config.DEFAULT_DURATION)) + 300
        try:
            stdout, stderr = process.communicate(timeout=_timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            end_time = datetime.now()
            app.logger.error(f"⏱️ [TEST] Timeout: {test_id} tidak selesai dalam {_timeout}s — proses JMeter di-kill")
            with state.tests_lock:
                state.running_tests[test_id]['status']   = config.STATUS_FAILED
                state.running_tests[test_id]['end_time'] = end_time
                state.running_tests[test_id]['error']    = f'JMeter tidak selesai dalam {_timeout}s, dihentikan paksa'
                state.running_tests[test_id].pop('process', None)
            save_metadata_async(app)
            return

        end_time     = datetime.now()
        stdout_stats = _parse_stdout_stats(stdout) if no_jtl else None

        with state.tests_lock:
            was_stopped = state.running_tests[test_id].get('status') == config.STATUS_STOPPED

        if was_stopped:
            status = config.STATUS_STOPPED
        elif no_jtl:
            if process.returncode == 0 or stdout_stats:
                status = config.STATUS_COMPLETED
            else:
                app.logger.error(f"❌ [TEST] Gagal (no_jtl): {test_id} | rc={process.returncode} | stderr: {stderr[:200]}")
                status = config.STATUS_FAILED
        else:
            jtl_has_data = os.path.exists(results_file) and os.path.getsize(results_file) > 0
            if process.returncode == 0:
                status = config.STATUS_COMPLETED
            elif jtl_has_data:
                # JMeter kadang exit non-zero karena warning JVM, tapi JTL tetap lengkap — tetap proses
                app.logger.warning(f"⚠️ [TEST] JMeter exit rc={process.returncode} tapi JTL ada data, tetap proses: {test_id}")
                status = config.STATUS_COMPLETED
            else:
                app.logger.error(f"❌ [TEST] Gagal: {test_id} | rc={process.returncode} | stderr: {stderr[:300].replace(chr(10), ' | ')}")
                status = config.STATUS_FAILED

        with state.tests_lock:
            start_time = state.running_tests[test_id].get('start_time', end_time)
            if not was_stopped:
                state.running_tests[test_id]['status'] = status
            state.running_tests[test_id]['end_time'] = end_time
            state.running_tests[test_id].pop('process', None)

        save_metadata_async(app)

        elapsed_s = round((end_time - start_time).total_seconds())
        app.logger.info(f"✅ [TEST] Selesai: {test_id} | status={status} | elapsed={elapsed_s}s")

        if status == config.STATUS_COMPLETED:
            if no_jtl:
                process_no_jtl(app, test_id, test_dir, params, status, start_time, end_time, stdout_stats)
            else:
                process_results(app, test_id, test_dir, results_file, params, status, start_time, end_time)

    except Exception as e:
        app.logger.error(f"💥 [TEST] Error tidak terduga di test {test_id}: {e}")
        with state.tests_lock:
            state.running_tests[test_id]['status'] = config.STATUS_FAILED
            state.running_tests[test_id]['error']  = str(e)
            state.running_tests[test_id].pop('process', None)
        save_metadata_async(app)
