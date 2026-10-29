# PROMPT 06 — Nihai kök neden ve bilimsel tutarlılık raporu

## 1. D/AODV yüksek gecikmesi neden oluşuyor?

30 seed'in instrumented ns-3 replay'inde teslim edilmiş 2371 paket için paket-ağırlıklı ortalama gecikme 767.541 ms, medyan 13.999 ms, P90 3477.676 ms, P95 4742.192 ms, P99 10320.508 ms ve maksimum 10330.395 ms ölçüldü. >100/>500/>1000 ms paket sayıları sırasıyla 819/582/424. P05 özetindeki 769.775 ms, her tekrarın paket ortalamasının aritmetik ortalamasıdır; bu rapor 2371 teslim edilmiş paketi tek havuzda ağırlıklandırır. Gönderim/alım simülasyon zamanları paket düzeyinde saklandı.

**Kök neden kesinleştirildi mi?** Hayır. ns-3.49 AODV'nin RREQ keşif/expanding-ring, bekleme ve kuyruk mekanizmaları olası açıklamalardır; kaynak varsayılanları tek başına per-packet nedensellik kanıtlamaz. 5/10/20 s warm-up değişikliği bu uzun gecikme kuyruğunu ortadan kaldırmadı; 25/35/45 m aralık deneyi PDR/gecikmenin topolojiye duyarlı olduğunu gösterdi. Ancak AODV route table, RREQ/RREP olayları ve paket kuyruk bekleme süresi packet ID ile ilişkilendirilmedi. Bu nedenle “yüksek gecikme kesin olarak route discovery kaynaklıdır” sonucu çıkarılamaz. Ayrıntı: `aodv_route_discovery_audit.md`.

## 2. D/OLSR gönderimleri neden reddediliyor?

Instrumented 30-seed denetimde 2842 ret kaydedildi (94.733/run); errno dağılımı: ERROR_NOROUTETOHOST=2842. Ölçüm 30 koşuda toplam 4500 üretilen paketin 1658 soket kabulüyle sürdürülmesi ve 1003 benzersiz uygulama teslimi gösterdi: ana uygulama PDR=1003/4500=0.22289; yalnız soketin kabul ettiği paketler payda alındığında koşullu teslim oranı=1003/1658=0.60495. Seed başına koşullu oranların aritmetik ortalaması 0.62355; bu, farklı paydaları havuzlayan koşullu orandan farklıdır. P05 özetindeki D/OLSR ortalama uygulama gecikmesi 14.120 ms'dir.

Retlerin ölçüm-anı geometrik bağlantı denetimi: no physical path=1855, path exists=987. Fiziksel yolsuz çiftte `ERROR_NOROUTETOHOST` görülmesi mevcut rota bulunmamasıyla uyumludur; ancak OLSR routing table state ve iç lookup çağrısı kaydedilmediğinden kesin iç neden olarak ileri sürülmez. PHY/MAC iletim/çakışma kanıtı da trace edilmedi.

## 3. Kök nedenler kanıtlandı mı?

Socket katmanındaki ret errno'su doğrudan yakalandı; olası “kanal kaybı” yorumu için destek yoktur. Bununla birlikte retlerin OLSR protokol içindeki kesin sebebi ve AODV gecikme kuyruğunun kesin sebebi henüz kanıtlanmamıştır. Gerekli ek kanıt: protokol route table/route-discovery trace'i ve PHY/MAC trace'leri packet ID veya güvenilir olay anahtarıyla eşleştirmek.

## 4. Yazılım veya ölçüm hatası var mı?

PROMPT 05'te FlowMonitor final sweep'inde `CheckForLostPackets(Seconds(0))` kullanılması ölçüm kusurudur: bekleme eşiğini sıfıra indirir. Düzeltilmiş no-argument çağrısıyla yapılan 60 D eşleştirilmiş rerunda PDR'yi oluşturan uygulama benzersiz teslimat sayısı ve FlowMonitor Rx hiçbir koşuda değişmedi; FlowMonitor lost toplamı AODV'de 2542'den 2541'e, OLSR'de 655'ten 654'e indi (her protokolde 30 koşudan yalnızca birinde 1 paket fark). Bu, D ana PDR/uygulama gecikme sonuçlarının FlowMonitor değişikliğinden etkilenmediğini gösterir; fakat eski FlowMonitor lost sayaçları düzeltilmiş gibi raporlanmamalıdır. Ayrıca düzeltilmiş ayrı out-of-range smoke testinde uygulama 0/5 teslimat gösterirken FlowMonitor lost=1 idi. C FlowMonitor rerun'ı yapılmadı. `lostPackets` ayrıca probe drop ve timeout sayaçlarını kapsayabilir; Tx-Rx veya uygulama kaybı ile eşit kabul edilmez.

## 5. PROMPT 05 sonuçları geçerli mi?

Baseline CSV'ler/özetler `baseline_before_diagnostics/` içinde immutable arşivlendi ve SHA-256 manifestine göre 105/105 dosya eşleşti; uyumsuzluk sayısı 0. D için eşleştirilmiş 60 rerun'da application PDR/teslimat ve FlowMonitor Rx aynı kaldı; bu nedenle D ana PDR ve paket düzeyi gecikme özetleri yeniden hesaplanmak zorunda değildir. Ancak PROMPT 05 FlowMonitor `lostPackets` sayacı sıfır eşikli çağrı nedeniyle yöntemsel olarak düzeltilmeli/yeniden etiketlenmelidir; C için düzeltilmiş FlowMonitor rerun'ı tamamlanmadı. Rerun'lar ve duyarlılık çıktıları baseline dosyalarını değiştirmedi.

## 6. Hakem R2.1 için güvenli iddialar

Bağımsız ns-3.49 paket düzeyi simülatöründe standart AODV ve OLSR ile, R1 Python soyutlamalarıyla eşlenmiş koordinat ve trafik çizelgeleri üzerinde 30 seed tekrarlı çalıştırma yapılmıştır. Raporlanan CI yarı genişlikleri seed düzeyindeki eşleştirilmiş Student-t hesabıdır. Bu bir uygulama düzeyi çapraz-doğrulamadır; fiziksel eşdeğerlik, radyo kalibrasyonu ya da “aynı protokol” kanıtı değildir. R2.1 için uygun sınırlar `R2_1_validation_interpretation.md` içindedir.

## 7. Makalede açıklanması gereken sınırlamalar

- Python AODV-like/OLSR-like ve ns-3 standart AODV/OLSR aynı uygulama değildir.
- Python model gecikmesi ile ns-3 packet-level gecikmesi farklı tanımlıdır.
- 35 m hard cutoff ve PHY/MAC ayarları kalibre edilmemiştir; ns-3 control bytes/messages instrument edilmemiştir.
- C'deki tek gerçek AirSim izi 35 m grafında tam bağlıdır; çok-atlamalı stres testi değildir ve 30 seed 30 uçuş değildir.
- D, R1 SyntheticMobility izlerini kullanır; seed tekrarları bağımsız uçuş değil, sentetik RNG/trafik tekrarlarıdır.
- FlowMonitor assumed-loss ve uygulama packet-ID sayaçları ayrı tutulmalıdır; retlerin ve FlowMonitor farklarının nedeni kanıt sınırlarını aşacak biçimde atfedilmemelidir.
- Warm-up pozisyonları sürekli oynatmaz: simülasyon ilk konumda başlar ve pozisyon snapshot'ı yalnız trafik değerlendirme anlarında atanır.

## 8. Test sayısı

Test durumu: 31 unit tests passed (21 R1 + 6 ns-3 + 4 PROMPT 06); 5 ns-3 smoke cases passed; 0 failures. Komut ve tam çıktı `diagnostic_tests.log` içinde kayıtlıdır.

## 9. Git commit

Baseline commit: `b1e7a40289012b4f18ba7341092622e91ccfdd08`. Tanı değişikliklerinin commit kimliği Git geçmişinden doğrulanır; rapor içinde kendi commit SHA'sı tekrarlanmaz.

## 10. Google Drive bulut eşitlemesi

Dosyaların yerel eşitleme klasöründeki kopyaları SHA-256 ile doğrulanabilir; bulut tarafındaki tamamlanma bu ortamdan bağımsız ve doğrudan doğrulanmadıkça “tamamlandı” denmeyecektir.

## Eşleştirilmiş CI denetimi

P05'teki karşılaştırmalar repetition seed'e göre eşleştirilmiş Student-t testidir (n=30, df=29; 95% yarı genişlik aşağıda). Bunlar seed düzeyindeki eşleştirilmiş farkların bağımsız olduğu varsayımına dayanır; C için tek AirSim izi sabittir, dolayısıyla CI uçuşlar-arası belirsizliği kapsamaz.

| Scenario | Routing | Metric | Mean paired difference | 95% Student-t CI half-width | n | df |
|---|---|---|---:|---:|---:|---:|
| C | aodv | pdr | -0.004341 | 0.008877 | 30 | 29 |
| C | aodv | mean_latency_ms | -14.335398 | 0.016882 | 30 | 29 |
| C | olsr | pdr | 0.000000 | 0.000000 | 30 | 29 |
| C | olsr | mean_latency_ms | -13.491264 | 0.014785 | 30 | 29 |
| D | aodv | pdr | -0.000222 | 0.018737 | 30 | 29 |
| D | aodv | mean_latency_ms | 736.180111 | 112.818856 | 30 | 29 |
| D | olsr | pdr | -0.256667 | 0.036631 | 30 | 29 |
| D | olsr | mean_latency_ms | -7.477301 | 6.938477 | 30 | 29 |

## Deney duyarlılığı (temsilî üç seed)

Warm-up/drain:

| Parametre | Değer | Yönlendirme | n | PDR ort. | Ret/run ort. | Gecikme ort. ms | P95 ms | Ölçüm sonrasında teslim/run | Fiziksel yolsuz çift/run |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| drain | 10.0 | aodv | 3 | 0.60222 | 0.000 | 577.029172328677 | 3148.9799775666665 | 0.000 | 53.667 |
| drain | 10.0 | olsr | 3 | 0.22667 | 82.667 | 37.4775928524129 | 18.867763316666657 | 0.000 | 53.667 |
| drain | 20.0 | aodv | 3 | 0.60222 | 0.000 | 577.029172328677 | 3148.9799775666665 | 0.000 | 53.667 |
| drain | 20.0 | olsr | 3 | 0.22667 | 82.667 | 37.4775928524129 | 18.867763316666657 | 0.000 | 53.667 |
| drain | 5.0 | aodv | 3 | 0.60222 | 0.000 | 577.029172328677 | 3148.9799775666665 | 0.000 | 53.667 |
| drain | 5.0 | olsr | 3 | 0.22667 | 82.667 | 37.4775928524129 | 18.867763316666657 | 0.000 | 53.667 |
| warmup | 10.0 | aodv | 3 | 0.58889 | 0.000 | 563.4912404316119 | 3262.1179329666666 | 0.333 | 53.667 |
| warmup | 10.0 | olsr | 3 | 0.27556 | 70.000 | 38.60280306876277 | 25.593493316666667 | 0.000 | 53.667 |
| warmup | 20.0 | aodv | 3 | 0.58222 | 0.000 | 634.1429508793486 | 3565.034460416666 | 0.000 | 53.667 |
| warmup | 20.0 | olsr | 3 | 0.27111 | 66.333 | 31.006628928571295 | 27.42538811666666 | 0.000 | 53.667 |
| warmup | 5.0 | aodv | 3 | 0.60222 | 0.000 | 577.029172328677 | 3148.9799775666665 | 0.000 | 53.667 |
| warmup | 5.0 | olsr | 3 | 0.22667 | 82.667 | 37.4775928524129 | 18.867763316666657 | 0.000 | 53.667 |

Menzil:

| Parametre | Değer | Yönlendirme | n | PDR ort. | Ret/run ort. | Gecikme ort. ms | P95 ms | Ölçüm sonrasında teslim/run | Fiziksel yolsuz çift/run |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| range | 25.0 | aodv | 3 | 0.16000 | 0.000 | 1521.7257523693124 | 7471.425763266665 | 0.333 | 133.000 |
| range | 25.0 | olsr | 3 | 0.05333 | 135.333 | 6.890904880952344 | 12.502594083333332 | 0.000 | 133.000 |
| range | 35.0 | aodv | 3 | 0.60222 | 0.000 | 577.029172328677 | 3148.9799775666665 | 0.000 | 53.667 |
| range | 35.0 | olsr | 3 | 0.22667 | 82.667 | 37.4775928524129 | 18.867763316666657 | 0.000 | 53.667 |
| range | 45.0 | aodv | 3 | 0.79556 | 0.000 | 221.15848272325752 | 869.2625900833333 | 0.333 | 9.667 |
| range | 45.0 | olsr | 3 | 0.47111 | 29.000 | 15.550397433720363 | 17.43315563333333 | 0.000 | 9.667 |

## Kanıt dosyaları

- `socket_send_errno_audit.csv`
- `aodv_delay_distribution.csv`
- `aodv_route_discovery_audit.md`
- `olsr_send_rejection_root_cause.md`
- `flowmonitor_discrepancy_audit.md`
- `warmup_drain_sensitivity.csv`
- `range_sensitivity.csv`
- `sensitivity_packet_delivery_audit.csv` (8100 packet-condition rows; the baseline condition is reused as the reference for each sensitivity dimension)
- `paired_comparison_integrity.json`
- `diagnostic_statistical_summary.csv`
- `diagnostic_tests.log`
