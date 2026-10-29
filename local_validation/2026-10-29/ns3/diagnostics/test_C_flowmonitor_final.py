"""Tests against the preserved real 60-run evidence and adverse mutations."""
import copy
import math
import statistics
import unittest
from collections import Counter

import analyze_C_flowmonitor as analysis
import verify_C_flowmonitor as gate


class CFlowMonitorFinalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = analysis.OUT
        cls.comparison, cls.summaries, cls.historical_count = analysis.collect(cls.out)
        cls.validation = gate.read_json(cls.out / 'C_flowmonitor_validation.json')

    def test_01_exactly_60_unique_main_runs(self):
        self.assertEqual(len(self.summaries), 60)
        self.assertEqual(len({(s['routing'], s['repetition_seed']) for s in self.summaries}), 60)
        self.assertEqual(len(gate.read_json(self.out / 'main/runlog.json')), 60)

    def test_02_30_seeds_per_protocol(self):
        self.assertEqual(Counter(s['routing'] for s in self.summaries), {'aodv': 30, 'olsr': 30})
        for routing in ('aodv', 'olsr'):
            self.assertEqual({int(s['repetition_seed']) for s in self.summaries if s['routing'] == routing},
                             set(analysis.SEEDS))

    def test_03_every_run_contains_599_generated_packet_events(self):
        for s, c in zip(self.summaries, self.comparison):
            self.assertEqual(int(s['application_generated_packets']), 599)
            self.assertEqual(c['packet_ids_checked'], 599)
        self.assertEqual(sum(c['packet_ids_checked'] for c in self.comparison), 35940)

    def test_04_source_and_runner_sha256(self):
        self.assertEqual(gate.sha(gate.REF / 'ns3_fanet_reference.cc'), gate.EXPECTED_SOURCE)
        self.assertEqual(gate.sha(gate.RUNNER), gate.EXPECTED_RUNNER)
        self.assertEqual(gate.read_json(self.out / 'main_validation.json')['source_sha256'], gate.EXPECTED_SOURCE)

    def test_05_frozen_prompt05_prompt06_data_unchanged(self):
        self.assertEqual(gate.verify_frozen(self.out), self.historical_count)
        self.assertGreater(self.historical_count, 100)

    def test_06_all_C_input_hashes_match_original_settings(self):
        settings = gate.read_json(gate.REF / 'real_airsim_replay/ns3_experiment_settings.json')
        selected = {k: v for k, v in settings['input_hashes']['input_csv_sha256'].items() if k.startswith('C/')}
        self.assertEqual(len(selected), 31)
        for name, expected in selected.items():
            self.assertEqual(gate.sha(gate.REF / 'real_airsim_replay/inputs' / name), expected)

    def test_07_protocols_use_same_packet_endpoints_and_timelines(self):
        # collect() independently checks AODV vs OLSR schedules for every seed.
        self.assertTrue(all(c['packet_schedule_mismatches'] == 0 for c in self.comparison))
        self.assertTrue(all(c['packet_baseline_identity_mismatches'] == 0 for c in self.comparison))

    def test_08_application_delivery_and_pdr_match_prompt05(self):
        for c in self.comparison:
            self.assertTrue(c['delivered_unchanged'])
            self.assertTrue(c['application_pdr_unchanged'])
            self.assertEqual(c['packet_delivery_mismatches'], 0)
        for s in self.summaries:
            self.assertTrue(math.isclose(float(s['pdr']), int(s['application_unique_delivered_packets']) / 599,
                                        rel_tol=0, abs_tol=1e-12))

    def test_09_summary_and_packet_delays_match_prompt05(self):
        self.assertTrue(all(c['delay_ms_unchanged'] for c in self.comparison))
        self.assertTrue(all(c['packet_delay_mismatches'] == 0 for c in self.comparison))

    def test_10_socket_and_drain_counts_match(self):
        for c in self.comparison:
            for name in ('generated', 'socket_accepted', 'socket_rejected', 'undelivered_after_drain'):
                self.assertTrue(c[name + '_unchanged'])

    def test_11_flowmonitor_components_and_labels(self):
        for s in self.summaries:
            self.assertEqual(int(s['flowmonitor_lost_packets']),
                             int(s['flowmonitor_reported_drop_packets']) + int(s['flowmonitor_pending_timeout_packets']))
        for c in self.comparison:
            self.assertEqual(c['flowmonitor_check_method_corrected'], 'CheckForLostPackets()')
            self.assertEqual(c['flowmonitor_check_method_old'], 'CheckForLostPackets(Seconds(0))')
        self.assertTrue(self.validation['flowmonitor_lost_is_not_tx_minus_rx_or_application_loss'])

    def test_12_runner_receipts_match_real_outputs(self):
        receipt = gate.read_json(self.out / 'main/C_flowmonitor_summary.json')
        log = gate.read_json(self.out / 'main/runlog.json')
        self.assertEqual(receipt['n_runs'], len(self.summaries))
        self.assertEqual(receipt['application_mismatches'], [])
        self.assertTrue(all(r['exit'] == 0 and 'completed,C,' in r['output'] for r in log))
        for name in ('runlog.json', 'C_flowmonitor_summary.json'):
            self.assertEqual(gate.sha(self.out / name), gate.sha(self.out / 'main' / name))
        self.assertEqual(self.validation['actual_main_runs'], 60)
        self.assertEqual(self.validation['packet_mismatch_runs'], 0)

    def test_13_student_t_interval_uses_repeat_means_and_df29(self):
        data = [float(i) for i in range(30)]
        mean, half_width = analysis.interval(data)
        self.assertEqual(mean, 14.5)
        self.assertAlmostEqual(half_width, 2.045229642132703 * statistics.stdev(data) / math.sqrt(30))
        self.assertEqual(analysis.interval([1.0] * 30), (1.0, 0.0))
        with self.assertRaises(ValueError):
            analysis.interval([1.0])

    def test_14_loss_mutation_is_reported_separately_from_application_metrics(self):
        key = ('aodv', 20261029)
        old = copy.deepcopy(analysis.baseline_index()[key])
        old['flowmonitor_lost_packets'] = '999'
        new = analysis.rows(self.out / 'main/aodv_seed_20261029/summary.csv')[0]
        events = analysis.rows(self.out / 'main/aodv_seed_20261029/packet_events.csv')
        traffic = {r['packet_id']: r for r in analysis.rows(gate.REF / 'real_airsim_replay/inputs/C/traffic_seed_20261029.csv')}
        result = analysis.compare_run(old, new, events, analysis.baseline_packets()[key], traffic)
        self.assertFalse(result['flowmonitor_lost_unchanged'])
        self.assertTrue(result['application_metrics_match'])

    def test_15_packet_delivery_and_delay_mutations_are_detected(self):
        key = ('aodv', 20261029)
        old = analysis.baseline_index()[key]
        new = analysis.rows(self.out / 'main/aodv_seed_20261029/summary.csv')[0]
        events = analysis.rows(self.out / 'main/aodv_seed_20261029/packet_events.csv')
        events[0]['delivered_same_id'] = '0'
        events[1]['application_latency_ms'] = '10000'
        traffic = {r['packet_id']: r for r in analysis.rows(gate.REF / 'real_airsim_replay/inputs/C/traffic_seed_20261029.csv')}
        result = analysis.compare_run(old, new, events, analysis.baseline_packets()[key], traffic)
        self.assertFalse(result['packet_metrics_match'])
        self.assertEqual(result['packet_delivery_mismatches'], 1)
        self.assertEqual(result['packet_delay_mismatches'], 1)

    def test_16_pilot_is_separate_and_successful(self):
        self.assertEqual(gate.read_json(self.out / 'pilot_validation.json')['runs'], 2)
        gate.verify_runs(self.out / 'pilot', (20261029,))

    def test_17_statistical_json_matches_independent_recomputation(self):
        for record in self.validation['statistics']:
            selected = [s for s in self.summaries if s['routing'] == record['routing']]
            self.assertEqual(record['simulator_repeats'], 30)
            self.assertEqual(record['independent_recorded_flights'], 1)
            self.assertEqual(record['mean_pdr'], statistics.mean(float(s['pdr']) for s in selected))
            self.assertEqual(record['corrected_flowmonitor_lost_total'], sum(int(s['flowmonitor_lost_packets']) for s in selected))

    def test_18_nonfinite_delay_and_changed_pdr_cannot_pass(self):
        self.assertFalse(analysis.number_equal('NaN', 'NaN'))
        self.assertFalse(analysis.number_equal('0.999', '1', 1e-12))
        self.assertTrue(analysis.number_equal('NA', 'NA'))


if __name__ == '__main__':
    unittest.main()
