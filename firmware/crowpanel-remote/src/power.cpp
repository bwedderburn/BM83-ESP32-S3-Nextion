#include "power.h"
#include "display_init.h"

#include <Arduino.h>
#include <esp_sleep.h>
#include <driver/rtc_io.h>

void enter_light_sleep_until_boot() {
    // 1. Drop the backlight — the dominant power load on the HMI.
    set_backlight(0);

    // 2. Configure GPIO 0 (BOOT button) as an RTC input with pull-up,
    //    then enable ext0 wake on a low level. The BOOT button is wired
    //    to ground when pressed.
    rtc_gpio_init(GPIO_NUM_0);
    rtc_gpio_set_direction(GPIO_NUM_0, RTC_GPIO_MODE_INPUT_ONLY);
    rtc_gpio_pullup_en(GPIO_NUM_0);
    rtc_gpio_pulldown_dis(GPIO_NUM_0);
    esp_sleep_enable_ext0_wakeup(GPIO_NUM_0, 0);

    // 3. Light sleep until the button is pressed.
    //    Wi-Fi modem sleeps in the background; association is preserved
    //    so on return there's no reconnect.
    esp_light_sleep_start();

    // 4. Wake — release the RTC GPIO so subsequent reads (if anything ever
    //    needed GPIO 0 in regular GPIO mode) work normally.
    rtc_gpio_deinit(GPIO_NUM_0);

    // 5. Restore the backlight. The caller resets idle-tracking state.
    set_backlight(255);
}
