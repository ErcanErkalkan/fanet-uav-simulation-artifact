# Hakem 2 R2.5 — gerçek AirSim izinden sağlanan kanıt

Yerel depoda Hakem 2 R2.5 yorumunun tam metni bulunmadığından aşağıdaki kanıt, madde metninin tamamına verilmiş yanıt olarak sunulmamalıdır.

## Gerçek AirSim hareket izi

- Kaynak gerçek AirSim CSV'si: SHA-256 `9C09B80E19CC6321BA61899565D34CA96EA4D0C02C3B0E0E4F969DD7F93115E3`; 19 sütun, 1.800 satır, 600 kare ve üç UAV.
- `source=airsim`, node kimlikleri, monotonik sıra, sonlu NED konum/hız ve AirSim simülasyon timestamp'leri denetlendi; ortak NED koordinatları oynatma sırasında değiştirilmedi.
- Replay zamanı `monotonic_time_s`; duvar/monotonik aralık 119.791 s, AirSim sim zamanı 118.284 s (fark -1.508 s).
- Binary 35 m menzil altında bağımsız hesaplama 600/600 karede tam bağlantı gösterdi; bu nedenle bu iz çok-atlamalı routing başarısı kanıtlamaz.

## Replay deneyleri

- 360 kontrollü model replay'i: üç bağlantı profili (binary 35 m, varsayılan wireless model, wireless 35 m sınır duyarlılığı), AODV-like ve OLSR-like, orijinal 5 Hz ve türetilmiş 1 Hz, koşul başına 30 RNG tekrarı.
- Her koşulda aynı deterministik 5 paket/s üretici kullanıldı; aynı seed için kaynak-hedef çiftleri koşullar arasında eşleştirildi. 30 tekrar 30 uçuş değildir.
- Wireless profili AirSim radyo ölçümlerine göre ampirik olarak kalibre edilmemiştir; fiziksel binary-vs-wireless üstünlük iddiası yapılmaz. Gecikme, hop, PDR, control/topology ve route event metrikleri R1 soyutlama model çıktılarıdır.
- Koşul bazında PDR, model gecikmesi ve Student-t %95 güven aralığı yarı genişliği aşağıdaki tabloda verilmiştir.

| İz | Link modeli | Routing | PDR mean | PDR t95 half-width | Model latency ms | Latency t95 half-width |
|---|---|---|---:|---:|---:|---:|
| 1hz_derived | binary | aodv_like_reactive | 1.0000 | 0.0000 | 14.871 | 0.013 |
| 1hz_derived | binary | olsr_like_proactive | 1.0000 | 0.0000 | 14.046 | 0.013 |
| 1hz_derived | wireless | aodv_like_reactive | 0.9393 | 0.0070 | 15.317 | 0.071 |
| 1hz_derived | wireless | olsr_like_proactive | 0.8346 | 0.0106 | 13.210 | 0.034 |
| 1hz_derived | wireless_35m_cap | aodv_like_reactive | 0.9393 | 0.0070 | 15.317 | 0.071 |
| 1hz_derived | wireless_35m_cap | olsr_like_proactive | 0.8346 | 0.0106 | 13.210 | 0.034 |
| 5hz_original | binary | aodv_like_reactive | 1.0000 | 0.0000 | 14.897 | 0.015 |
| 5hz_original | binary | olsr_like_proactive | 1.0000 | 0.0000 | 14.054 | 0.012 |
| 5hz_original | wireless | aodv_like_reactive | 0.9391 | 0.0038 | 16.458 | 0.109 |
| 5hz_original | wireless | olsr_like_proactive | 0.7800 | 0.0109 | 13.195 | 0.029 |
| 5hz_original | wireless_35m_cap | aodv_like_reactive | 0.9391 | 0.0038 | 16.458 | 0.109 |
| 5hz_original | wireless_35m_cap | olsr_like_proactive | 0.7800 | 0.0109 | 13.195 | 0.029 |

## Sınırlar

- Hareket ve kinematik kaynakta AirSim gerçeğidir; paket taşınımı AirSim içinde çalıştırılmamıştır.
- R1 route protocols, kanal, gecikme ve PDR metrikleri model tabanlıdır; ns-3/OMNeT++ packet-level doğrulama değildir.
- Üç düğümlü iz tam bağlı olduğundan dinamik multi-hop protokol üstünlüğü hakkında sonuç çıkarılamaz.
- R2.5'in tam metni sağlanırsa kanıtlar yoruma birebir eşlenmelidir.
