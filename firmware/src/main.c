// ESP32-S3 Wi-Fi CSI capture.
//
// Single-board setup: the ESP joins your router as a station, pings the
// gateway at PING_HZ, and records the CSI of every frame the router sends
// back. Each frame becomes one line on the serial port:
//
//   CSI,<seq>,<esp_us>,<rssi>,<rate>,<sig_mode>,<first_word_invalid>,<len>,<hex bytes>
//
// The hex payload is int8 pairs [imag, real] per subcarrier (64 subcarriers
// for L-LTF => 128 bytes). Everything not starting with "CSI," is log noise.

#include <stdio.h>
#include <string.h>
#include <inttypes.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/event_groups.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_mac.h"
#include "nvs_flash.h"
#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"
#include "ping/ping_sock.h"
#include "lwip/ip_addr.h"

#include "secrets.h"

#define PING_HZ      100   // CSI sample rate you'll get (approximately)
#define CSI_MAX_LEN  128   // L-LTF only: 64 subcarriers * (imag, real)
#define QUEUE_DEPTH  64

static const char *TAG = "csi";

typedef struct {
    uint32_t seq;
    uint32_t ts_us;
    int8_t   rssi;
    uint8_t  rate;
    uint8_t  sig_mode;
    uint8_t  first_word_invalid;
    uint16_t len;
    int8_t   buf[CSI_MAX_LEN];
} csi_pkt_t;

static QueueHandle_t s_queue;
static EventGroupHandle_t s_wifi_events;
#define GOT_IP_BIT BIT0
static uint8_t s_ap_bssid[6];
static volatile uint32_t s_seq, s_dropped;

// Runs in the Wi-Fi task: keep it short, hand off to the printer task.
static void csi_cb(void *ctx, wifi_csi_info_t *info)
{
    if (!info || !info->buf) return;
    if (memcmp(info->mac, s_ap_bssid, 6) != 0) return;  // only frames from our AP

    csi_pkt_t p;
    p.seq = s_seq++;
    p.ts_us = info->rx_ctrl.timestamp;
    p.rssi = info->rx_ctrl.rssi;
    p.rate = info->rx_ctrl.rate;
    p.sig_mode = info->rx_ctrl.sig_mode;
    p.first_word_invalid = info->first_word_invalid;
    p.len = info->len > CSI_MAX_LEN ? CSI_MAX_LEN : info->len;
    memcpy(p.buf, info->buf, p.len);

    if (xQueueSend(s_queue, &p, 0) != pdTRUE) s_dropped++;
}

static void print_task(void *arg)
{
    static const char hex[] = "0123456789abcdef";
    static char line[64 + CSI_MAX_LEN * 2 + 2];
    csi_pkt_t p;

    while (true) {
        xQueueReceive(s_queue, &p, portMAX_DELAY);
        int n = snprintf(line, sizeof(line),
                         "CSI,%" PRIu32 ",%" PRIu32 ",%d,%u,%u,%u,%u,",
                         p.seq, p.ts_us, p.rssi, p.rate, p.sig_mode,
                         p.first_word_invalid, p.len);
        for (int i = 0; i < p.len; i++) {
            uint8_t b = (uint8_t)p.buf[i];
            line[n++] = hex[b >> 4];
            line[n++] = hex[b & 0xf];
        }
        line[n++] = '\n';
        fwrite(line, 1, n, stdout);
        fflush(stdout);
    }
}

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        wifi_event_sta_disconnected_t *d = data;
        // 201 = network not found (off / 5 GHz only), 15/204 = wrong password
        ESP_LOGW(TAG, "disconnected (reason %d), retrying", d->reason);
        xEventGroupClearBits(s_wifi_events, GOT_IP_BIT);
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        xEventGroupSetBits(s_wifi_events, GOT_IP_BIT);
    }
}

static esp_netif_t *wifi_init(void)
{
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_t *netif = esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL));

    wifi_config_t wc = {0};
    strlcpy((char *)wc.sta.ssid, WIFI_SSID, sizeof(wc.sta.ssid));
    strlcpy((char *)wc.sta.password, WIFI_PASS, sizeof(wc.sta.password));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wc));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));  // power save drops packets
    return netif;
}

static void csi_init(void)
{
    wifi_csi_config_t c = {
        .lltf_en = true,           // legacy LTF: 64 subcarriers, present on every frame
        .htltf_en = false,
        .stbc_htltf2_en = false,
        .ltf_merge_en = true,
        .channel_filter_en = false,
        .manu_scale = false,
        .shift = 0,
    };
    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&c));
    ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(csi_cb, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_csi(true));
}

static void ping_start(esp_netif_t *netif)
{
    esp_netif_ip_info_t ip;
    ESP_ERROR_CHECK(esp_netif_get_ip_info(netif, &ip));

    esp_ping_config_t pc = ESP_PING_DEFAULT_CONFIG();
    ip_2_ip4(&pc.target_addr)->addr = ip.gw.addr;
    IP_SET_TYPE(&pc.target_addr, IPADDR_TYPE_V4);
    pc.count = ESP_PING_COUNT_INFINITE;
    pc.interval_ms = 1000 / PING_HZ;
    pc.timeout_ms = 1000;
    pc.data_size = 1;
    pc.task_stack_size = 4096;

    esp_ping_callbacks_t cbs = {0};
    esp_ping_handle_t h;
    ESP_ERROR_CHECK(esp_ping_new_session(&pc, &cbs, &h));
    ESP_ERROR_CHECK(esp_ping_start(h));
    ESP_LOGI(TAG, "pinging gateway " IPSTR " at %d Hz", IP2STR(&ip.gw), PING_HZ);
}

void app_main(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    // Buffered, interrupt-driven USB output. The default console path is
    // polled and can't keep up with ~30 KB/s of CSI text.
    usb_serial_jtag_driver_config_t usb_cfg = {
        .tx_buffer_size = 16384,
        .rx_buffer_size = 256,
    };
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&usb_cfg));
    usb_serial_jtag_vfs_use_driver();

    s_queue = xQueueCreate(QUEUE_DEPTH, sizeof(csi_pkt_t));
    s_wifi_events = xEventGroupCreate();
    xTaskCreate(print_task, "csi_print", 4096, NULL, 5, NULL);

    esp_netif_t *netif = wifi_init();
    ESP_LOGI(TAG, "connecting to \"%s\"...", WIFI_SSID);
    xEventGroupWaitBits(s_wifi_events, GOT_IP_BIT, pdFALSE, pdTRUE, portMAX_DELAY);

    wifi_ap_record_t ap;
    ESP_ERROR_CHECK(esp_wifi_sta_get_ap_info(&ap));
    memcpy(s_ap_bssid, ap.bssid, 6);
    ESP_LOGI(TAG, "connected, AP " MACSTR " ch %d rssi %d", MAC2STR(ap.bssid), ap.primary, ap.rssi);

    csi_init();
    ping_start(netif);

    // Quiet the driver logs so they don't interleave with CSI lines.
    esp_log_level_set("*", ESP_LOG_WARN);

    while (true) {
        vTaskDelay(pdMS_TO_TICKS(5000));
        if (s_dropped) {
            ESP_LOGW(TAG, "dropped %" PRIu32 " CSI frames (serial too slow)", s_dropped);
            s_dropped = 0;
        }
    }
}
