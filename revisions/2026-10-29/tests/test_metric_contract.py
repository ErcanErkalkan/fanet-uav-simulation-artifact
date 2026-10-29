"""Deterministic tests of R1 metric semantics, not physical validation."""
import math
import unittest
from statistics import stdev
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fanet_metric_contract import (LinkEpisodeTracker, RouteEventCounter,
                                   finite_or_na_mean, normal_95ci_halfwidth)
from fanet_routing_protocols import RouteDecision, make_protocol, RoutingBenchmarkSimulator
from fanet_wireless_channel_model import WirelessFANETSimulator
from fanet_unified_pipeline import parse_args, UnifiedFANETPipeline

class MetricContractTests(unittest.TestCase):
    def test_ci_halfwidth(self):
        values=[1., 2., 3., 4.]
        self.assertAlmostEqual(normal_95ci_halfwidth(values), 1.96 * stdev(values)/2)
        self.assertTrue(math.isnan(normal_95ci_halfwidth([1.])))
        self.assertTrue(math.isnan(normal_95ci_halfwidth([])))
        self.assertAlmostEqual(normal_95ci_halfwidth([1., float('nan'), 2.]),1.96*stdev([1.,2.])/math.sqrt(2))

    def test_nan_mean(self):
        self.assertTrue(math.isnan(finite_or_na_mean([])))
        self.assertTrue(math.isnan(finite_or_na_mean([math.nan])))
        self.assertEqual(finite_or_na_mean([1., math.nan, 3.]), 2.)

    def test_initial_links_not_topology_changes(self):
        t=LinkEpisodeTracker()
        t.observe({(0,1)},1)
        self.assertEqual(t.post_initial_edge_transitions,0)
        self.assertEqual(t.initial_active_links,1)
        t.observe({(0,1)},1)
        self.assertEqual(t.post_initial_edge_transitions,0)
        t.observe(set(),1)
        self.assertEqual(t.post_initial_edge_transitions,1)
        self.assertEqual(t.completed,[2.])

    def test_broken_and_recovered_link_are_separate_episodes(self):
        t=LinkEpisodeTracker()
        t.observe({'A'},1.)
        t.observe(set(),1.)
        t.observe({'A'},1.)
        t.observe({'A'},1.)
        out=t.as_columns(4)
        self.assertEqual(out['completed_link_episode_count'],1)
        self.assertEqual(out['right_censored_link_episode_count'],1)
        self.assertEqual(out['mean_completed_link_episode_s'],1.)
        self.assertEqual(out['mean_observed_link_episode_s_including_censored'],1.5)
        self.assertEqual(out['topology_changes_excluding_initial'],2)

    def test_no_completed_episodes_undefined(self):
        t=LinkEpisodeTracker(); t.observe({'a'},1)
        self.assertTrue(math.isnan(t.as_columns(1.)['mean_completed_link_episode_s']))

    def test_recovered_legacy_flag_not_lost_packet(self):
        c=RouteEventCounter()
        c.observe(RouteDecision(True, [0,1], discovery=True, route_failure=True))
        self.assertEqual(c.packets_without_routing_path,0)
        self.assertEqual(c.route_recovery_after_flag,1)
        self.assertEqual(c.protocol_specific_route_flag_events,1)
        self.assertEqual(c.route_discovery_failures,0)

    def test_route_unavailable_different_from_channel_failure(self):
        c=RouteEventCounter()
        c.observe(RouteDecision(False, None, discovery=True))
        c.observe(RouteDecision(True,[0,1]),delivered_after_channel=False)
        self.assertEqual(c.packets_without_routing_path,1)
        self.assertEqual(c.packets_with_routing_path,1)
        self.assertEqual(c.failed_wireless_packets_after_routing,1)
        self.assertEqual(c.route_discovery_failures,1)

    def test_routing_smoke_counters(self):
        r=RoutingBenchmarkSimulator(5,make_protocol('aodv_like_reactive'),102, duration_s=6).run()
        self.assertEqual(r['attempted_packets'],r['attempted'])
        self.assertEqual(r['packets_without_routing_path']+r['packets_with_routing_path'],r['attempted'])
        self.assertGreaterEqual(r['initial_active_links'],0)
        self.assertGreaterEqual(r['topology_changes_excluding_initial'],0)

    def test_binary_metrics_undefined_not_fake_sinr(self):
        r=WirelessFANETSimulator(10,102,duration_s=4).run_once('binary')
        self.assertTrue(math.isnan(r['mean_sinr_db']))
        self.assertTrue(math.isnan(r['energy_mj_per_packet']))
        self.assertEqual(r['attempted_packets'],r['delivered_packets']+r['packets_without_routing_path'])

    def test_wireless_conservation(self):
        r=WirelessFANETSimulator(10,102,duration_s=4).run_once('wireless')
        self.assertEqual(r['attempted_packets'], r['delivered_packets']+r['packets_without_routing_path']+r['failed_wireless_packets_after_routing'])

    def test_unified_synthetic_model_consistency(self):
        import argparse
        args=argparse.Namespace(source='synthetic',trace=None,num_uavs=8,duration=4.,dt=1.,
            area_xy=100., altitude_min=15.,altitude_max=45.,speed_min=1.5,speed_max=6.,
            packets_per_step=3,communication_range=35.,link_model='wireless', routing='aodv_like_reactive', scenario_name='smoke')
        r=UnifiedFANETPipeline(args,102).run_once()
        self.assertEqual(r['packet_attempts'], r['delivered_packets']+r['packets_without_routing_path']+r['failed_wireless_packets_after_routing']+r['missing_route_edges'])
        self.assertEqual(r['attempted_packets'],r['packet_attempts'])

if __name__=='__main__':unittest.main()
