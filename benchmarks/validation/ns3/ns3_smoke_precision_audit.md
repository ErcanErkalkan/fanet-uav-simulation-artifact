# Smoke-test measurement audit

## What changed

The prior smoke driver used `delaySum.GetMilliSeconds() / rxPackets`. That performs integer-millisecond conversion before division and can discard fractional milliseconds. The corrected calculation is `1000.0 * delaySum.GetSeconds() / static_cast<double>(rxPackets)`. When no application packet is received, mean delay remains `NA`.

The old channel helper also started with the default log-distance loss model and added a hard range loss model. The corrected driver constructs each channel from an empty helper and selects exactly one explicit profile:

- `range_limited_wifi`: a hard 50 m cutoff in these smoke cases, with no additional propagation loss. This is a deterministic topology fixture, not a radio calibration. Wi-Fi PHY reception, MAC contention, retries and routing remain active.
- `log_distance_wifi`: LogDistance with exponent 3.0, reference distance 1 m and reference loss 40.05 dB, with no hard range cutoff. It is an uncalibrated propagation sensitivity profile.

Both use ad-hoc 802.11g, channel 1 / 20 MHz at 2.4 GHz, fixed 6 Mbps data/control rates, 16 dBm transmit power, -101 dBm receive sensitivity, and an explicit short-frame retry limit of 7. The ns-3.49 `WifiMac::FrameRetryLimit` is used; obsolete `MaxSsrc`/`MaxSlrc` attributes are not used.

The driver now separately records actual UdpClient Tx trace callbacks, IP FlowMonitor Tx/Rx counters, and PacketSink application Rx trace callbacks. The simulation includes time after the last scheduled packet; `CheckForLostPackets(Seconds(0))` accounts for packets still undelivered at simulation end. Forwarding-based hop estimates are labelled as estimates, not exact per-packet paths. Routing control overhead is not captured and stays `NA`.

## Before/after delay results

For each corrected run, the driver now emits both the exact double-precision mean and the old integer-millisecond expression computed over the same FlowMonitor observations. This isolates the arithmetic difference from changes to the channel and PHY/MAC configuration.

| Smoke case | Legacy integer formula on same run (ms) | Corrected double formula (ms) | Fraction lost (ms) |
|---|---:|---:|---:|
| Single-hop / global | 1.000000 | 1.348494 | 0.348494 |
| Linear chain / AODV | 3.000000 | 3.462772 | 0.462772 |
| Linear chain / OLSR | 2.000000 | 2.497172 | 0.497172 |
| Out of range / global | NA | NA | NA |

The previously committed smoke CSV contained the legacy integer values (1, 3 and 2 ms). The corrected paired calculation above reproduces those integer outputs exactly while exposing the fractional-millisecond mean that was lost. Because the channel and radio settings were also made explicit in this change, cross-run changes in the full-precision values must not be attributed to precision alone. These are five-packet smoke runs, not inferential or calibrated results.

## Verification

All four original smoke conditions passed after correction: 5/5 packets delivered for single-hop, 0/5 for the out-of-range pair, and 5/5 for each two-hop routing case. A fifth single-hop run validated that the separate LogDistance profile executes. See `ns3_smoke_test_results.csv` and `ns3_smoke_test.log`.
