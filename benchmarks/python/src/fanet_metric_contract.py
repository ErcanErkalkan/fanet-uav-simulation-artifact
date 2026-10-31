"""R1/A1 metric contract for SIMPAT-D-26-1023 (reviewer R2.6).

This module supplements the original simulator without claiming to improve its
PHY/MAC fidelity. It deliberately distinguishes route-event flags, packet loss,
and observed (possibly right-censored) link episodes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite, nan, sqrt
from statistics import mean, stdev
from typing import Any, Hashable, Iterable


def finite_or_na_mean(values: Iterable[float]) -> float:
    valid = [float(v) for v in values if isfinite(float(v))]
    return mean(valid) if valid else nan


def normal_95ci_halfwidth(values: Iterable[float]) -> float:
    """Approximate 95% normal CI *half-width* from independent run values.

    This is an approximation (1.96 * sample SD / sqrt(n)), not a Student-t CI.
    Undefined for fewer than two finite independent observations.
    """
    valid = [float(v) for v in values if isfinite(float(v))]
    return 1.96 * stdev(valid) / sqrt(len(valid)) if len(valid) >= 2 else nan


@dataclass
class RouteEventCounter:
    """Mutually interpretable packet outcomes plus protocol-specific event flags."""
    attempted_packets: int = 0
    packets_without_routing_path: int = 0
    packets_with_routing_path: int = 0
    route_discovery_attempts: int = 0
    route_discovery_failures: int = 0
    route_recovery_after_flag: int = 0
    stale_route_packets: int = 0
    protocol_specific_route_flag_events: int = 0
    failed_wireless_packets_after_routing: int = 0

    def observe(self, decision: Any, delivered_after_channel: bool | None = None) -> None:
        self.attempted_packets += 1
        path_available = bool(decision.delivered) and bool(decision.path)
        if path_available:
            self.packets_with_routing_path += 1
        else:
            self.packets_without_routing_path += 1
        if bool(decision.discovery):
            self.route_discovery_attempts += 1
            if not path_available:
                self.route_discovery_failures += 1
        if bool(decision.route_failure):
            self.protocol_specific_route_flag_events += 1
            if path_available:
                self.route_recovery_after_flag += 1
        if bool(decision.stale_route):
            self.stale_route_packets += 1
        if path_available and delivered_after_channel is False:
            self.failed_wireless_packets_after_routing += 1

    def as_columns(self) -> dict[str, int]:
        return vars(self).copy()


@dataclass
class LinkEpisodeTracker:
    """Track consecutive sampled active-link episodes and right-censoring.

    `dt_s` is the simulated duration represented by the current observation.
    Completed episodes end when the link is absent at a later observation.
    Episodes still active at experiment end are right-censored, NOT treated as
    observed full link lifetimes. First-frame edges are an initial condition,
    not topology changes.
    """
    active: dict[Hashable, float] = field(default_factory=dict)
    completed: list[float] = field(default_factory=list)
    previous: set[Hashable] | None = None
    initial_active_links: int = 0
    post_initial_edge_transitions: int = 0
    frames: int = 0

    def observe(self, edges: Iterable[Hashable], dt_s: float) -> None:
        if dt_s < 0:
            raise ValueError("dt_s must be >=0")
        present = set(edges)
        if self.previous is None:
            self.initial_active_links = len(present)
        else:
            self.post_initial_edge_transitions += len(self.previous.symmetric_difference(present))
        for edge in list(self.active):
            if edge not in present:
                self.completed.append(self.active.pop(edge))
        for edge in present:
            self.active[edge] = self.active.get(edge, 0.0) + dt_s
        self.previous = present
        self.frames += 1

    def as_columns(self, duration_s: float) -> dict[str, float | int]:
        observed = self.completed + list(self.active.values())
        return {
            "initial_active_links": self.initial_active_links,
            "topology_changes_excluding_initial": self.post_initial_edge_transitions,
            "topology_changes_excluding_initial_per_s":
                self.post_initial_edge_transitions / duration_s if duration_s > 0 else nan,
            "completed_link_episode_count": len(self.completed),
            "right_censored_link_episode_count": len(self.active),
            "mean_completed_link_episode_s": finite_or_na_mean(self.completed),
            "mean_observed_link_episode_s_including_censored": finite_or_na_mean(observed),
        }
