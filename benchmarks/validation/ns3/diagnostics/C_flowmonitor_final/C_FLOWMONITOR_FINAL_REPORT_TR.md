# SIMPAT PROMPT 06 — Senaryo C FlowMonitor son doğrulaması

**Deney sonucu: BAŞARILI.** 29 Ekim 2026 tarihinde WSL2 Ubuntu 24.04 / Python 3.12.3 üzerinde gerçek ns-3.49 kullanılarak 2 pilot ve bunlardan ayrı 60 ana koşu seri yürütüldü. Ana koşular 22:41:06–22:42:12 TSİ aralığında tamamlandı. Sonuçlar bir AirSim uçuş kaydına koşullu, protokol başına 30 simülatör tekrarıdır; 30 bağımsız gerçek uçuş değildir.

## 1. Çalıştırma ve girdiler

- Senaryo C, 3 İHA, aynı 600 karelik gerçek AirSim kaydı; NED koordinatları.
- Seed aralığı: 20261029–20261058; her seed için bir AODV ve bir OLSR koşusu.
- Her koşuda aynı seed'e ait 599 trafik olayı, 256 bayt uygulama paketi; yeni trafik üretilmedi.
- `range_limited_wifi`, 35 m menzil; warm-up 5 s, drain 10 s, ölçüm penceresi 119.7909209 s.
- ns-3 RNG seed'i 20261029; run numaraları 1–30. Trafik seed'leri özgün çizelgelerden okundu.
- Verilen `run_C_corrected_flowmonitor.py` gerçek Drive dosyasından bulundu ve **değiştirilmeden** kullanıldı. Pilot için yalnızca içe aktarılan modülün seed listesi bellekte tek seed'e sınırlandı; dosya baytları değiştirilmedi.
- Ana koşuların her birinde ns-3 süreç çıkışı 0; 60 `summary.csv` ve 60 `packet_events.csv` korundu. Pilotun 4 CSV dosyası ayrı `pilot/` altındadır.

Depo ve WSL `scratch/ns3_fanet_reference.cc` kaynaklarının ikisinde SHA-256:

`BDEDB8C09FDE29B9146C82E8B28512D6E995FD1DC495C7F9E4087B17145AA840`

Her ikisinde `CheckForLostPackets()` mevcuttur; `CheckForLostPackets(Seconds(0))` çağrısı yoktur. Kaynak eşitleme/yedekleme gerektiren bir fark görülmedi. Mevcut deney betiğinin SHA-256 değeri:

`34389574CE70ECDEB55CEA14CD519B8DD1676389132E003095D7864D2896F1A4`

Özgün AirSim CSV SHA-256 değeri:

`9C09B80E19CC6321BA61899565D34CA96EA4D0C02C3B0E0E4F969DD7F93115E3`

30 trafik çizelgesi ve hareketlilik CSV'si PROMPT 05 ayar dosyasındaki hash'lerle eşleştirildi. İki protokolün aynı seed'de paket kimlikleri, kaynak/hedefleri ve zaman çizelgeleri aynı kaldı.

## 2. Sayısal sonuçlar

Değerlerdeki ±, 30 koşunun ortalaması için Student-t %95 güven aralığı **yarı genişliğidir** (`df=29`, `t=2.045229642132703`); standart sapma değildir. PDR, `benzersiz teslim edilen uygulama paket kimlikleri / uygulamada üretilen paketler` olarak hesaplandı.

| Ölçüt | AODV | OLSR |
|---|---:|---:|
| Başarılı ana koşu | 30/30 | 30/30 |
| Ortalama PDR | 0.9956594323873 | 1.0000000000000 |
| PDR %95 GA yarı genişliği | 0.0088774575452 | 0 |
| Ortalama PDR, yüzde | %99.56594324 | %100 |
| PDR GA yarı genişliği, yüzde puan | 0.88774575 | 0 |
| Ortalama uygulama gecikmesi (ms) | 0.5617959564053 | 0.5627742048978 |
| Gecikme %95 GA yarı genişliği (ms) | 0.0042117148132 | 0.0042652416334 |
| Üretilen uygulama paketi toplamı | 17970 | 17970 |
| Benzersiz teslim toplamı | 17892 | 17970 |
| Socket kabul / ret toplamı | 17970 / 0 | 17970 / 0 |
| FlowMonitor Tx / Rx toplamı | 17970 / 17892 | 17970 / 17970 |
| Eski FlowMonitor lostPackets toplamı | 78 | 0 |
| Düzeltilmiş FlowMonitor lostPackets toplamı | 78 | 0 |
| FlowMonitor lostPackets değişen koşu | **0** | **0** |
| PDR değişen seed | **0** | **0** |
| Ortalama gecikmesi değişen seed | **0** | **0** |
| Uygulama teslim sayısı değişen seed | **0** | **0** |
| Drain sonunda teslim edilmeyen toplam | 78 | 0 |

AODV'nin `20261043` seed'inde 521/599 teslim (`PDR=0.869782971619`) ve 78 teslim edilmeyen paket vardır. Aynı sonuç PROMPT 05'te de vardır; yeni bir uyumsuzluk değildir. Bu koşunun düzeltilmiş FlowMonitor değerleri `Tx=599`, `Rx=521`, `lostPackets=78`, `reported_drop_packets=0`, `pending_timeout_packets=78` olarak kaydedildi. AODV'nin diğer 29 koşusunda ve OLSR'nin 30 koşusunda lostPackets 0'dır.

Bu örnekte bazı sayaçların sayısal olarak eşit olması tanımlarını eşitlemez. FlowMonitor lostPackets, doğrudan ns-3 FlowStats'tan alınmıştır; `Tx−Rx` veya uygulama PDR kaybından türetilmemiştir. `pending_timeout_packets`, bu tanı kaynağında `lostPackets − sum(packetsDropped)` olarak tanımlanır; zaman aşımı bekleyen canlı kuyruk uzunluğu değildir. Uygulama ve IP katmanı sayaçları ayrı sütunlarda korunmuştur. Dayanak, kurulu ns-3.49 `src/flow-monitor/model/flow-monitor.cc` kaynağı ve [resmî FlowMonitor belgesidir](https://www.nsnam.org/docs/release/3.49/models/html/flow-monitor.html).

## 3. PROMPT 05 ile paket düzeyinde karşılaştırma

60 seed/protokol çifti özgün `real_airsim_replay_raw.csv` ile; **35940 paket kaydı** özgün `real_airsim_replay_packet_audit.csv` ile birebir eşleştirildi. Paket kimliği çakışması veya eksik eşleşme yoktur.

- Üretim, benzersiz teslim, PDR, socket kabul/ret ve drain sonrası teslim edilmeyen sayılarda uyumsuzluk: **0 koşu**.
- Ortalama gecikmede uyumsuzluk: **0 koşu**.
- Paket teslim durumunda uyumsuzluk: **0 paket**.
- Paket gecikmesinde uyumsuzluk: **0 paket**; gözlenen en büyük mutlak fark **0 ms**.
- Kaynak/hedef ve zaman çizelgesinde değişiklik: **0**.
- FlowMonitor Tx, Rx veya lostPackets değişikliği: **0 koşu**.

PDR karşılaştırma toleransı 1e-12; gecikme toleransı 1e-6 ms, çizelge zaman toleransı 1e-9 s kullanıldı. Gözlenen gecikme farkı toleransa yakın değildir: sıfırdır. Ortalama gecikmeler, koşu başına benzersiz teslimlerin uygulama gönderiminden ilk alıma kadar geçen sürelerinden hesaplandı; protokol özetinde bu 30 koşu ortalamasının aritmetik ortalaması kullanıldı.

**Eski sonuçları yeniden hesaplamak gerekiyor mu?** Senaryo C'nin uygulama PDR, teslimat ve gecikme sonuçlarını değiştirmek gerekmiyor. C için eski FlowMonitor lostPackets sayıları da düzeltilmiş koşularla aynıdır; raporlarda doğru yöntem ve bu yeni doğrulama kaydı kullanılmalıdır. Bu bulgu Senaryo D'ye genellenmez; D'nin PROMPT 06 tanı kayıtları ayrı değerlendirilmelidir. Önceki ham CSV'ler yerinde korunmuştur.

## 4. Testler ve dosya güvenliği

| Test grubu | Başarılı / toplam |
|---|---:|
| R1 metrikleri, gerçek AirSim replay ve kayıtçı testleri | 21/21 |
| ns-3 giriş/doğrulama testleri | 6/6 |
| PROMPT 06 tanı testleri | 4/4 |
| Yeni Senaryo C FlowMonitor testleri | 18/18 |
| **Son test turu** | **49/49** |

Mevcut 31 test pilot öncesinde de başarıyla çalıştırıldı. Son turda 49 test geçti; bunların 18'i yenidir. Yayımdan önce aynı 49 test ve SHA-256 manifestosu ayrıca yeniden doğrulandı. Yeni testler gerçek 60 koşuluk kanıtı, girdi hash'lerini, 599 olay/koşu şartını, aynı-seed çizelgelerini, paket teslim/gecikmelerini, sayaç etiketlerini, JSON tutarlılığını ve kasıtlı bozma örneklerinin saptanmasını denetler. Yeniden çalıştırmalar ayrı test sayısı olarak sayılmamıştır.

İlk açılan DriveFS deposu doğru daldaydı, uzak daldan 4 commit gerideydi ve 7 değiştirilmiş izlenen dosya ile izlenmeyen diagnostics dosyaları içeriyordu. `git fetch origin` yapıldı; bu değişikliklere dokunulmadı. Güncel uzak dalın `b6b58735ac28c180d661b8ca3ff8f4fbe66787ea` commit'inden ayrı bir çalışma kopyası oluşturuldu. İlk deponun HEAD'i `b1e7a40289012b4f18ba7341092622e91ccfdd08` olarak korundu.

İzole çalışma kopyasındaki 152 önceki doğrulama dosyasının hash'leri koşulardan önce ve sonra aynı kaldı. İlk DriveFS çalışma alanında 266 mevcut dosyanın SHA-256 değerleri ve Git çalışma durumu ayrıca denetlendi; sonuç `original_workspace_preservation.json` içindedir. `main`, R0 metni ve PROMPT 05/PROMPT 06 ham sonuçları değiştirilmedi.

## 5. Hakem R2.1 açısından anlamı ve sınırlamalar

Bu deney, verilen gerçek AirSim hareketlilik kaydı aynı trafik çizelgeleriyle ns-3.49 AODV/OLSR'ye tekrar oynatıldığında, düzeltilmiş FlowMonitor son kontrolünün **uygulama PDR ve gecikme sonuçlarını değiştirmediğini** doğrular. Sonuç yalnız kod incelemesine değil, gerçek süreç çıkışlarına, 120 ana çıktı CSV'sine ve 35940 paket eşleşmesine dayanır. FlowMonitor muhasebesi ile temel uygulama teslim ölçümünün ayrı raporlanması yeniden üretilebilir biçimde doğrulanmıştır.

Devam eden sınırlar:

1. Tek hareketlilik uçuş kaydı kullanılmıştır; 30 seed yeni gerçek uçuş veya farklı hareketlilik örneklemi değildir. Güven aralıkları bu kayda ve modele koşullu simülatör değişkenliğini gösterir.
2. Üç İHA ve 35 m profilindeki C girdisi PROMPT 05 topoloji denetiminde 600/600 karede tam bağlıdır; geniş ölçekli, kopuk veya yoğun çok atlamalı FANET koşullarını temsil etmez.
3. AirSim hareketliliği gerçek kayıt olsa da radyo, yönlendirme ve paket gecikmeleri ns-3 modeli içinde üretilmiştir. Gerçek uçuş ağı üzerinden uçtan uca paket ölçümü veya tam fiziksel radyo doğrulaması iddiası yoktur.
4. OLSR'nin gözlenen PDR'sinin 1 olması genel kayıpsızlık kanıtı değildir. Student-t aralığı klasik, kırpılmamış aralıktır; PDR gibi sınırlı bir ölçü için bu koşullu tekrar özetidir.
5. Bu çalışma C FlowMonitor son doğrulamasına sınırlıdır; önceki D muhasebe farklarını veya bütün makalenin dış geçerliliğini tek başına çözmez.

## 6. Dosyalar, yeniden üretme ve teslim kaydı

Bu raporun depo konumu: `local_validation/2026-10-29/ns3/diagnostics/C_flowmonitor_final/`.

- `C_flowmonitor_comparison.csv`: istenen tüm eski/yeni uygulama ve FlowMonitor alanları, paket eşleşme sayaçları.
- `C_flowmonitor_statistical_summary.csv`: protokol başına ortalama, Student-t %95 GA yarı genişliği ve açık sıfır değişim sayıları.
- `C_flowmonitor_summary.json` ve `runlog.json`: verilen betiğin ürettiği dosyaların baytları değiştirilmemiş kopyaları; asılları `main/` altındadır.
- `C_flowmonitor_execution.log`: pilot ve 60 ana koşunun ilerleme kayıtları.
- `C_flowmonitor_validation.json`: bağımsız doğrulama ve hesaplama kaydı.
- `C_flowmonitor_sha256_manifest.txt`: sonuç dosyalarının ve kullanılan yeni kodların SHA-256 manifestosu.
- `main/<protokol>_seed_<seed>/summary.csv` ve `packet_events.csv`: 60 gerçek ana koşunun bütün ham çıktıları.
- `pilot/`: iki pilotun ayrı çıktıları; `existing_tests.*` ve `final_tests.*`: test kanıtları.

Yeniden üretme komutları bir üst dizindeki `C_flowmonitor_reproduce.md` dosyasındadır. Verilen koşucu mevcut çıktı dizinini reddeder. Yeni bir çalıştırmada yeni ve önceden var olmayan çıktı yolu kullanılır.

**Git ve bulut teslimi:** Deney sonucu ile dağıtım durumunu ayırmak için son commit/push SHA'sı ve doğrudan Drive readback kanıtı ayrıca teslim makbuzunda ve son kullanıcı yanıtında bildirilir. Bu raporu içeren commit kendi SHA'sını içine gömemez. Bulut eşitlemesi yalnız DriveFS süreç durumundan çıkarılmaz; bulut dosyaları bağlı Google Drive üzerinden okunarak denetlenir.

**Google Drive bulut doğrulaması: BAŞARILI.** 29 Ekim 2026 22:52:07 TSİ itibarıyla ilk 149 sonuç dosyasının tamamı bağlı Drive üzerinden ham dosya olarak alınmış, bağımsız HTTPS indirmesiyle SHA-256 ve bayt boyutu yerel dosyalarla eşleştirilmiştir. Bunların içinde 60 ana koşunun 120 CSV'sinin tamamı vardır. Eşleşmeyen içerik: 0 dosya. `C_flowmonitor_cloud_verification.json` ayrıntılı ilk doğrulama makbuzudur. Son rapor/manifest ve makbuzun bulut kopyaları da teslim öncesi ayrıca okunur. Bulut klasörü: [C_flowmonitor_final](https://drive.google.com/drive/folders/1Ld0yWr9ku3gsGu5YoLu1McDbZI6obl3D).
