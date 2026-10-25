#include <cassert>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <memory>
#include <string>
#include <vector>

struct lv_event_t {
    void *user_data;
    int code;
};
using EventCallback = void (*)(lv_event_t *);
struct Binding {
    EventCallback callback;
    int code;
    void *user_data;
};
struct lv_obj_t {
    std::string label;
    int x, y, width, height;
    std::vector<Binding> bindings;
};
static const int LV_EVENT_CLICKED = 1, LV_EVENT_PRESSED = 2;
static const int LV_EVENT_RELEASED = 3, LV_EVENT_PRESS_LOST = 4;
#define LV_SYMBOL_PREV "<"
#define LV_SYMBOL_PLAY ">"
#define LV_SYMBOL_NEXT ">|"
#define LV_SYMBOL_MUTE "X"

static std::vector<std::unique_ptr<lv_obj_t>> buttons;
static std::vector<std::string> sent;
static lv_obj_t *g_play_button_label = nullptr;

static lv_obj_t *make_button(lv_obj_t *, const char *label, int x, int y,
                             int width, int height, bool = false) {
    std::unique_ptr<lv_obj_t> button(new lv_obj_t{label, x, y, width, height, {}});
    lv_obj_t *result = button.get();
    buttons.push_back(std::move(button));
    return result;
}
static void lv_obj_add_event_cb(lv_obj_t *button, EventCallback callback, int code, void *data) {
    button->bindings.push_back({callback, code, data});
}
static lv_obj_t *lv_obj_get_child(lv_obj_t *button, int) { return button; }
static void *lv_event_get_user_data(lv_event_t *event) { return event->user_data; }
static int lv_event_get_code(lv_event_t *event) { return event->code; }
static bool note_token(const char *token) { sent.push_back(token); return true; }

// Actual main.cpp definitions: action label, both callback forms and footer.
#include "mute_controls_runtime.inc"

static void trigger(lv_obj_t *button, int code) {
    for (const Binding &binding : button->bindings) {
        if (binding.code == code) {
            lv_event_t event = {binding.user_data, code};
            binding.callback(&event);
        }
    }
}

int main() {
    build_transport_controls(nullptr);
    assert(buttons.size() == 6 && g_play_button_label);
    lv_obj_t *mute = nullptr;
    for (const auto &button : buttons) {
        assert(button->x >= 0 && button->x + button->width <= 800);
        assert(button->y >= 0 && button->y + button->height <= 480);
        assert(button->width >= 44 && button->height >= 44);
        for (const auto &other : buttons) {
            if (button.get() == other.get()) continue;
            assert(button->x + button->width <= other->x ||
                   other->x + other->width <= button->x ||
                   button->y + button->height <= other->y ||
                   other->y + other->height <= button->y);
        }
        for (const Binding &binding : button->bindings)
            if (std::strcmp(static_cast<const char *>(binding.user_data), "BT_MUTE") == 0)
                mute = button.get();
    }
    assert(mute && mute->label.find("Mute") != std::string::npos);
    assert(mute->bindings.size() == 1 && mute->bindings[0].code == LV_EVENT_CLICKED);
    assert(std::strcmp(action_name("BT_MUTE"), "Mute") == 0);
    trigger(mute, LV_EVENT_PRESSED);
    trigger(mute, LV_EVENT_RELEASED);
    trigger(mute, LV_EVENT_PRESS_LOST);
    assert(sent.empty());  // Hold/release must not toggle mute a second time.
    trigger(mute, LV_EVENT_CLICKED);
    assert(sent == std::vector<std::string>{"BT_MUTE"});
    trigger(mute, LV_EVENT_CLICKED);
    assert(sent == (std::vector<std::string>{"BT_MUTE", "BT_MUTE"}));
    std::cout << "PASS: one mute action per click; footer touch targets fit without overlap\n";
}
