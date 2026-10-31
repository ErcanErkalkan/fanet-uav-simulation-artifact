# Gerçek AirSim izinin FANET R1 pipeline'ında yeniden oynatılması

## Veri, zaman ekseni ve koruma

- Kaynak: `airsim_real_3uav_120s.csv`; SHA-256 `9C09B80E19CC6321BA61899565D34CA96EA4D0C02C3B0E0E4F969DD7F93115E3`.
- Orijinal AirSim CSV'si salt okunur girdi olarak kullanıldı; 19 sütun ve 1.800 satır doğrulandı.
- Ortak NED konumları, hız vektörleri, `source=airsim`, araç adları ve orijinal sıra numaraları değişmeden korundu.
- Replay saati: `monotonic_time_s` (monotonik kayıt zamanı). AirSim simülasyon nanosanı ayrıca doğrulandı ve kaynakta saklandı.
- Duvar saati/monotonik zaman aralığı: 119.790921 s; AirSim simülasyon zamanı: 118.283523 s; fark: -1.507603 s.
- Zaman eksenleri birbirine ölçeklenmedi. AirSim simülasyon zamanının duvar saatinden yavaş ilerlemesi simülatör kayıt hızına aittir; replay zamanlaması monotonic kayıttır.

## Trafik ve kontrollü koşullar

- Her koşulda toplam trafik hedefi deterministik zaman tabanlı üreticiyle 5.0 paket/s; trafik zamanları ilk monotonic kareye göre 0,2 s aralıklarla üretilir.
- Her paket için source-destination çifti `random.Random(traffic_seed)` ile seçildi; `traffic_seed = repetition_seed + 119913`. Trafik RNG'si kanal RNG'sinden ayrıdır, aynı tekrar seed'inde koşullar arasında paket çiftleri eşleşir.
- Bir paket üretim anı iki hareket karesi arasındaysa, routing ve link değerlendirmesi bir sonraki örneklenmiş kare konumunda yapılır; ara-konum interpolasyonu yoktur.
- 1 Hz türetilmiş iz, orijinalden her 1 saniyeye en yakın kare seçilerek oluşturuldu; orijinal CSV değiştirilmedi. Trafik hızı aynı 5 paket/s kaldığından 1 Hz karede yaklaşık beş paket aynı örneklenmiş topoloji/konum üzerinde değerlendirilir.
- 30 RNG tekrarı koşul başına; seed'ler 20261029–20261058. Bunlar 30 bağımsız uçuş değildir; aynı sabit hareket izi üzerinde model RNG tekrarlarıdır.
- Binary 35 m, unrestricted WirelessChannel varsayılan R1 profili ve mevcut R1 kalibrasyon duyarlılık çalışmasındaki 35 m-capped wireless topoloji duyarlılığı kullanıldı. AirSim radyo ölçümleriyle ampirik kalibrasyon bulunmadığından WirelessChannel'ı fiziksel olarak AirSim'e kalibre edilmiş saymıyoruz ve binary-wireless fiziksel üstünlük iddiası kurmuyoruz.
- 35 m-capped profil, wireless link reliability eşiğini ve 35 m aday mesafe sınırını birlikte uygular. R1 `calibrated_channels.py` eşit kenar bütçesi/kapsama duyarlılığı içindir; AirSim'e özgü fiziksel parametre kalibrasyonu değildir.
- AODV-like ve OLSR-like uygulamaları protokol soyutlamalarıdır; ns-3/OMNeT++ protokol yığını değildir.

## Topoloji ve iddia sınırı

- Bağımsız geometrik denetim: 600/600 karede binary 35 m ağı tam bağlı; üç olası kenarın tamamı mevcut.
- Her UAV çifti menzil içinde olduğu için bu iz çok-atlamalı routing faydasını test etmez. AODV/OLSR sonuçları yalnızca doğrudan bağlı topolojideki routing/model davranışıdır.
- PDR %100 iken route flag görülmesi çelişki değildir: `route_failures` ve `route_recovery_after_flag` protokol olaylarıdır; bir flag, geçerli yol bulunduğu veya sonraki paket teslim edildiği halde raporlanabilir. `packets_without_routing_path` yalnızca route kararında geçerli yol bulunamayan paketleri sayar; PDR ise link/channel sonrasındaki teslim oranıdır.

## İstatistik

- Her link-model × routing × iz çözünürlüğü koşulunda n=30 RNG tekrar vardır. Özet CSV, metrik ortalaması, örnek SD ve iki taraflı Student-t %95 güven aralığı yarı genişliğini ayrı sütunlarda verir; df=29, t(0.975,29)=2.045229642133.
- PDR, gecikme, hop, rota, kontrol ve topoloji metrikleri FANET R1 kodunun simülasyon çıktılarıdır; AirSim'den ölçülmüş ağ/PHY gecikmesi, gerçek paket teslimi veya gerçek protokol kontrol trafiği değildir.

## Deney koşulu özetleri

| İz | Link modeli | Routing | PDR (ortalama ± t95 yarı genişlik) | Model gecikmesi ms (ortalama ± t95 yarı genişlik) | Ortalama hop | route_failures | packets_without_routing_path | route_recovery_after_flag | control packets/s |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1hz_derived | binary | aodv_like_reactive | 1.0000 ± 0.0000 | 14.871 ± 0.013 | 1.000 | 38.933 | 0.000 | 38.933 | 1.410 |
| 1hz_derived | binary | olsr_like_proactive | 1.0000 ± 0.0000 | 14.046 ± 0.013 | 1.000 | 0.000 | 0.000 | 0.000 | 3.479 |
| 1hz_derived | wireless | aodv_like_reactive | 0.9393 ± 0.0070 | 15.317 ± 0.071 | 1.276 | 71.433 | 30.033 | 56.633 | 3.478 |
| 1hz_derived | wireless | olsr_like_proactive | 0.8346 ± 0.0106 | 13.210 ± 0.034 | 1.112 | 66.500 | 94.700 | 0.000 | 3.100 |
| 1hz_derived | wireless_35m_cap | aodv_like_reactive | 0.9393 ± 0.0070 | 15.317 ± 0.071 | 1.276 | 71.433 | 30.033 | 56.633 | 3.478 |
| 1hz_derived | wireless_35m_cap | olsr_like_proactive | 0.8346 ± 0.0106 | 13.210 ± 0.034 | 1.112 | 66.500 | 94.700 | 0.000 | 3.100 |
| 5hz_original | binary | aodv_like_reactive | 1.0000 ± 0.0000 | 14.897 ± 0.015 | 1.000 | 40.500 | 0.000 | 40.500 | 1.453 |
| 5hz_original | binary | olsr_like_proactive | 1.0000 ± 0.0000 | 14.054 ± 0.012 | 1.000 | 0.000 | 0.000 | 0.000 | 4.282 |
| 5hz_original | wireless | aodv_like_reactive | 0.9391 ± 0.0038 | 16.458 ± 0.109 | 1.289 | 122.433 | 31.000 | 93.833 | 5.379 |
| 5hz_original | wireless | olsr_like_proactive | 0.7800 ± 0.0109 | 13.195 ± 0.029 | 1.102 | 95.267 | 127.767 | 0.000 | 3.821 |
| 5hz_original | wireless_35m_cap | aodv_like_reactive | 0.9391 ± 0.0038 | 16.458 ± 0.109 | 1.289 | 122.433 | 31.000 | 93.833 | 5.379 |
| 5hz_original | wireless_35m_cap | olsr_like_proactive | 0.7800 ± 0.0109 | 13.195 ± 0.029 | 1.102 | 95.267 | 127.767 | 0.000 | 3.821 |

## Tekrar üretimi

Çalıştırma komutu: `python run_real_airsim_replay.py`. Script SHA-256'i, giriş doğrulamalarını, topoloji testini, paket olay planını, RNG seed'lerini, ham run satırlarını, özetleri, grafiği ve kendi çalışma günlüğünü üretir.
