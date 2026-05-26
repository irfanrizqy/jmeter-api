"""
Bangun argumen command line untuk menjalankan JMeter.
Dipisahkan dari runner supaya logika subprocess tidak bercampur dengan logika command.
"""

import config


def parse_target_url(target_url):
    # Pecah URL menjadi host, port, path — ketiganya dilempar ke JMeter sebagai property
    url = target_url.replace('http://', '').replace('https://', '')

    host = config.DEFAULT_TARGET_HOST
    port = config.DEFAULT_TARGET_PORT
    path = config.DEFAULT_HTTP_PATH

    if '/' in url:
        host_port, path = url.split('/', 1)
        path = '/' + path
    else:
        host_port = url

    if ':' in host_port:
        host, port = host_port.split(':')
        port = int(port)
    else:
        host = host_port
        port = 443 if 'https://' in target_url else 80

    return host, port, path


def build_jmeter_cmd(target_host, target_port, http_path, params, results_file, log_file):
    # Susun daftar argumen JMeter CLI. Hasilnya langsung bisa dipakai di subprocess.Popen.
    return [
        config.JMETER_BIN,
        "-n",
        "-t", config.JMETER_TEMPLATE,
        "-l", results_file,
        "-j", log_file,
        f"-Jtarget_host={target_host}",
        f"-Jtarget_port={target_port}",
        f"-Jhttp_path={http_path}",
        f"-Jnum_threads={params.get('num_threads', config.DEFAULT_NUM_THREADS)}",
        f"-Jramp_time={params.get('ramp_time', config.DEFAULT_RAMP_TIME)}",
        f"-Jduration={params.get('duration', config.DEFAULT_DURATION)}",
        f"-Jresults_file={results_file}",
    ]
