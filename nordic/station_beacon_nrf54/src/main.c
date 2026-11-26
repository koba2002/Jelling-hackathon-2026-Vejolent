/*
 * Harald's Messengers: station beacon for the nRF54L15-DK
 *
 * The board shouts a name over Bluetooth 10 times a second, for example "STN-TOKYO".
 * The badge (ESP32) listens for names starting with "STN-", measures how strong
 * the signal is, and ticks faster the closer it gets.
 *
 * On the board:
 *   BUTTON 0  -> become the TOKYO station   (LED0 on)
 *   BUTTON 1  -> become the LONDON station  (LED1 on)
 *   LED3 blinks = the beacon is running
 * After a power cut the board starts again as DEFAULT_STATION, so set that line
 * to the right city before you flash each board.
 *
 * Board target: nrf54l15dk/nrf54l15/cpuapp   (nRF Connect SDK 2.8 or newer)
 */

#include <zephyr/kernel.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/gap.h>
#include <dk_buttons_and_leds.h>
#include <string.h>

/* ---- change this line for the second board: "STN-LONDON" ---- */
#define DEFAULT_STATION "STN-TOKYO"

static char name[24] = DEFAULT_STATION;

static struct bt_data ad[] = {
	BT_DATA_BYTES(BT_DATA_FLAGS, BT_LE_AD_NO_BREDR),
	BT_DATA(BT_DATA_NAME_COMPLETE, name, sizeof(DEFAULT_STATION) - 1),
};

static void show_station(void)
{
	dk_set_led(DK_LED1, strcmp(name, "STN-TOKYO") == 0);   /* LED0 on the board */
	dk_set_led(DK_LED2, strcmp(name, "STN-LONDON") == 0);  /* LED1 on the board */
	printk("Beacon is now %s\n", name);
}

static void set_station(const char *station)
{
	strncpy(name, station, sizeof(name) - 1);
	name[sizeof(name) - 1] = '\0';
	ad[1].data_len = strlen(name);

	int err = bt_le_adv_update_data(ad, ARRAY_SIZE(ad), NULL, 0);
	if (err) {
		printk("Could not change the name (err %d)\n", err);
	}
	show_station();
}

static void button_changed(uint32_t state, uint32_t changed)
{
	uint32_t pressed = state & changed;

	if (pressed & DK_BTN1_MSK) {        /* BUTTON 0 on the board */
		set_station("STN-TOKYO");
	} else if (pressed & DK_BTN2_MSK) { /* BUTTON 1 on the board */
		set_station("STN-LONDON");
	}
}

int main(void)
{
	int err;

	printk("Harald's Messengers station beacon\n");

	err = dk_leds_init();
	if (err) {
		printk("LEDs failed (err %d)\n", err);
	}
	err = dk_buttons_init(button_changed);
	if (err) {
		printk("Buttons failed (err %d)\n", err);
	}

	err = bt_enable(NULL);
	if (err) {
		printk("Bluetooth failed to start (err %d)\n", err);
		return 0;
	}

	/* Not connectable, every 100 ms (160 x 0.625 ms), so the badge reacts quickly */
	err = bt_le_adv_start(BT_LE_ADV_PARAM(BT_LE_ADV_OPT_NONE, 160, 160, NULL),
			      ad, ARRAY_SIZE(ad), NULL, 0);
	if (err) {
		printk("Advertising failed to start (err %d)\n", err);
		return 0;
	}
	show_station();

	/* Heartbeat: LED3 blinks so you can see the beacon is alive */
	bool on = false;
	while (1) {
		on = !on;
		dk_set_led(DK_LED4, on);
		k_sleep(K_MSEC(500));
	}
	return 0;
}
