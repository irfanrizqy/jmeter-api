"""
Parse file JTL hasil JMeter menjadi summary statistics.
JTL adalah CSV biasa dengan kolom timeStamp, elapsed, success, bytes, dll.
"""

import csv
import os

from jmeter.formatting import _safe_int


def parse_jmeter_results(app, results_file):
    # Baca seluruh JTL, hitung statistik agregat + timeline per-detik
    if not os.path.exists(results_file):
        return None

    stats = {
        'total_requests':             0,
        'success_requests':           0,
        'error_requests':             0,
        'response_times':             [],
        'bytes_received':             [],
        'bytes_sent':                 [],
        'timestamps':                 [],
        'response_time_min':          float('inf'),
        'response_time_max':          0,
        'response_time_avg':          0,
        'response_time_median':       0,
        'response_time_90percentile': 0,
        'response_time_95percentile': 0,
        'throughput':                 0,
        'error_rate':                 0,
        'bandwidth_received':         0,
        'bandwidth_sent':             0,
        'timeline':                   []
    }

    try:
        with open(results_file, 'r', newline='') as f:
            for row in csv.DictReader(f):
                stats['total_requests'] += 1

                success = row.get('success', 'true').lower() == 'true'
                if success:
                    stats['success_requests'] += 1
                else:
                    stats['error_requests'] += 1

                rt = _safe_int(row.get('elapsed', 0), 0)
                stats['response_times'].append(rt)
                stats['response_time_min'] = min(stats['response_time_min'], rt)
                stats['response_time_max'] = max(stats['response_time_max'], rt)

                stats['bytes_received'].append(_safe_int(row.get('bytes', 0), 0))
                stats['bytes_sent'].append(_safe_int(row.get('sentBytes', 0), 0))
                stats['timestamps'].append(_safe_int(row.get('timeStamp', 0), 0))

        if stats['response_times']:
            sorted_times = sorted(stats['response_times'])
            n = len(sorted_times)
            stats['response_time_avg']            = sum(sorted_times) / n
            stats['response_time_median']         = sorted_times[n // 2]
            stats['response_time_90percentile']   = sorted_times[min(int(n * 0.9), n - 1)]
            stats['response_time_95percentile']   = sorted_times[min(int(n * 0.95), n - 1)]

        if len(stats['timestamps']) > 1:
            duration_ms = max(stats['timestamps']) - min(stats['timestamps'])
            if duration_ms > 0:
                stats['throughput'] = (stats['total_requests'] / duration_ms) * 1000

        if stats['total_requests'] > 0:
            stats['error_rate'] = (stats['error_requests'] / stats['total_requests']) * 100

        if len(stats['timestamps']) > 1:
            duration_s = (max(stats['timestamps']) - min(stats['timestamps'])) / 1000
            if duration_s > 0:
                stats['bandwidth_received'] = (sum(stats['bytes_received']) / 1024) / duration_s
                stats['bandwidth_sent']     = (sum(stats['bytes_sent']) / 1024) / duration_s

        # Kelompokkan request per detik untuk data timeline di grafik
        timeline_data = {}
        for i, ts in enumerate(stats['timestamps']):
            second = int(ts / 1000)
            if second not in timeline_data:
                timeline_data[second] = {'response_times': [], 'count': 0}
            timeline_data[second]['response_times'].append(stats['response_times'][i])
            timeline_data[second]['count'] += 1

        if timeline_data:
            start = min(timeline_data.keys())
            for second in sorted(timeline_data.keys()):
                rts = timeline_data[second]['response_times']
                stats['timeline'].append({
                    'timestamp':     second - start,
                    'response_time': round(sum(rts) / len(rts), 4),
                    'throughput':    timeline_data[second]['count']
                })

        stats['response_time_min'] = round(stats['response_time_min'], 4) if stats['response_time_min'] != float('inf') else 0
        for field in ('response_time_max', 'response_time_avg', 'response_time_median',
                      'response_time_90percentile', 'response_time_95percentile',
                      'throughput', 'error_rate', 'bandwidth_received', 'bandwidth_sent'):
            stats[field] = round(stats[field], 4)

        return stats

    except Exception as e:
        app.logger.error(f"❌ [JTL] Error parsing JTL {results_file}: {e}")
        return None
