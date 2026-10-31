# ns-3 environment report

## Pre-install inspection

- Host: Windows 11 Enterprise, x64; WSL2 Ubuntu 24.04.4 LTS (Noble).
- WSL kernel: Microsoft WSL2 kernel 6.18.54.1.
- CPU: Intel Core i5-10400, 6 cores / 12 threads; WSL reports 12 processors.
- WSL memory: 7.8 GiB total, approximately 7.2 GiB available before the build; 2 GiB swap.
- WSL root filesystem: 1007 GiB total, approximately 953 GiB free before installation.
- Initial tool versions: g++ 13.3.0, Git 2.43.0, Python 3.12.3. CMake and Ninja were missing.
- No Windows Python installation was changed. CMake was configured with `/usr/bin/python3`; the ns-3 build used system Python 3.12.3.

## Selected release

- Official current stable release: ns-3.49, released 2026-10-07.
- The requested 3.47 candidate is not the latest stable release.
- Official source archive: <https://www.nsnam.org/releases/ns-3.49.tar.bz2>
- Source archive SHA-256: `81c9eb0839d2b527e9cc01db7eb0a521d8fc6a520ebb23d17f3a5c96e47b4d68`.
- Official Git tag `ns-3.49` peeled commit: `418210e8914e9f6bcb5cddbcc94a2cecb7853b68`.
- Source location: `$HOME/ns3-work/ns-3.49` (Linux filesystem, outside the Windows-mounted repository).
- The Google Drive `G:` volume is not mounted inside this WSL distribution. The Windows PowerShell runner copies only the tracked smoke source into the Linux `scratch` directory via the WSL UNC share, then copies the sanitized results back.

## Installation and build

- User approved installing CMake/Ninja dependencies and downloading ns-3.49 before changes.
- Installed CMake 3.28.3 and Ninja 1.11.1 plus Ubuntu runtime dependencies; no Python or compiler package was upgraded.
- Selected ns-3 modules: core, network, mobility, Wi-Fi, Internet, AODV, OLSR, applications, and FlowMonitor, plus required module dependencies.
- Optional GSL, SQLite, LibXML2, Eigen, GTK/visualizer, documentation, and Python bindings were not installed/enabled. They are not required for the selected C++ Wi-Fi/routing modules.
- Build configuration enables examples and tests, filters their compilation to core/Wi-Fi suites, and caps parallel jobs at 8 after checking RAM.
- Build status: passed; all 750 configured build actions completed with 8 parallel jobs and no swap pressure.
- Official example: `./ns3 run first` passed; the client and server exchanged the expected 1024-byte packet.
- Focused standard tests: `simulator` and `wifi-channel-settings`, `QUICK` fullness, both passed (1/1 each).
- Custom C++ smoke suite: all four cases passed. Single-hop: 5/5 delivered (PDR 1.0; mean IP delay 1.000 ms). Out-of-range: 0/5 delivered (PDR 0). Three-node AODV chain: 5/5 (PDR 1.0; 3.000 ms; forwarding-derived hop estimate 2.2). Three-node OLSR chain: 5/5 (PDR 1.0; 2.000 ms; forwarding-derived hop estimate 2.0).
- `lost_packets` is evaluated at simulation end using `FlowMonitor::CheckForLostPackets(Seconds(0))`; this counts all packets still undelivered at termination. Control overhead is not measured and remains `NA`. Delay and hop figures are ns-3 smoke-model outputs, not calibrated cross-framework results.

## API verified from the 3.49 source tree

- Module directories exist for all nine requested modules.
- C++ helper classes include `ns3::AodvHelper`, `ns3::OlsrHelper`, and `ns3::FlowMonitorHelper`.
- The tested program uses `ns3::WifiHelper`, `ns3::YansWifiChannelHelper`, `ns3::YansWifiPhyHelper`, `ns3::InternetStackHelper`, and `ns3::RangePropagationLossModel`.
- The local 3.49 headers/source define the `RangePropagationLossModel` attribute `MaxRange`, `FlowMonitorHelper::InstallAll()`/`GetClassifier()`, and `FlowStats` packet/delay/forwarding counters.
- The compiled smoke source exercises 802.11g ad-hoc Wi-Fi, fixed-rate PHY configuration, the range cutoff, UDP applications, FlowMonitor, global routing, AODV, and OLSR.

## Revision context

- Repository branch: `revision/simpat-2026-validation`.
- Starting commit: `c0c8d6d708a00893aea65d1df12807718fc4c271`.
- R1 Python source and the original AirSim CSV were not edited by the ns-3 setup.
