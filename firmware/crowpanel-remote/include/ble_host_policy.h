// BHC1/BHP1 version 1. Pure bounded C++11; never treats radio ACK as completion.
#pragma once
#include "ble_status.h"

namespace ble_host_policy {

static const size_t MAX_PEERS = 8, MAX_ALIAS = 24, MAX_BODY = 360;
static const size_t FRAGMENT_DATA = 45, MAX_FRAGMENTS = 8, STATUS_BYTES = 63;
static const uint32_t FRESH_MS = 5000, ASSEMBLY_MS = 2000, REQUEST_MS = 15000;
static const uint32_t HANDSHAKE_RETRY_MS = 750, HANDSHAKE_DEADLINE_MS = 2500, HANDSHAKE_COOLDOWN_MS = 1000;
enum Opcode { LIST = 0, DISCONNECT = 1, SELECT = 2, ENROLL = 3, ALIAS = 4, FORGET = 5 };
enum Mode { PAUSED = 0, AUTO = 1, ENROLL_MODE = 2, UNKNOWN_MODE = 255 };
enum State { PAUSED_STATE = 0, SWITCHING = 1, WAITING = 2, ENROLLING = 3,
             CONNECTED = 4, ERROR_STATE = 5, UNSUPPORTED = 6 };
enum Flag { READY = 1, ADVERTISING = 2, CONNECTED_FLAG = 4, ENCRYPTED = 8,
            BONDED = 16, HID_READY = 32, PERSISTED = 64,
            LAST_DISCONNECT_LOCAL = 128, FILTER_READY = 256 };
enum PeerFlag { OUR_SEC = 1, PEER_SEC = 2, CCCD = 4, RESUMABLE = 8, PEER_CONNECTED = 16 };
enum Result { IDLE, PENDING, WAITING_HOST, PAIRING, CONFIRMED, REJECTED,
              FAILED, TIMED_OUT, RESTARTED, SUPERSEDED, NOT_SENT, ENROLLMENT_ENDED };

inline bool id_none(const uint8_t *id) {
    uint8_t combined = 0;
    for (size_t i = 0; i < 8; ++i) combined |= id[i];
    return combined == 0;
}
inline bool same_id(const uint8_t *a, const uint8_t *b) { return memcmp(a, b, 8) == 0; }
inline void put16(uint8_t *p, uint16_t value) { p[0] = value >> 8; p[1] = value; }
inline void put32(uint8_t *p, uint32_t value) {
    p[0] = value >> 24; p[1] = value >> 16; p[2] = value >> 8; p[3] = value;
}
inline bool newer(uint32_t a, uint32_t b) { const uint32_t d = a - b; return d && d < 0x80000000U; }
inline bool valid_mode(uint8_t value) { return value <= ENROLL_MODE || value == UNKNOWN_MODE; }

// Strict scalar UTF-8, at most 24 bytes. Aliases cannot inject dropdown lines
// or terminal controls; empty means the owner's alias is cleared.
inline bool valid_alias(const uint8_t *text, size_t length) {
    if (length > MAX_ALIAS || (!text && length)) return false;
    for (size_t i = 0; i < length;) {
        const uint8_t first = text[i++];
        uint32_t scalar = first;
        unsigned continuation = 0;
        uint32_t minimum = 0;
        if (first >= 0xC2 && first <= 0xDF) { continuation = 1; scalar &= 0x1F; minimum = 0x80; }
        else if (first >= 0xE0 && first <= 0xEF) { continuation = 2; scalar &= 0x0F; minimum = 0x800; }
        else if (first >= 0xF0 && first <= 0xF4) { continuation = 3; scalar &= 7; minimum = 0x10000; }
        else if (first >= 0x80) return false;
        if (i + continuation > length) return false;
        while (continuation--) {
            if ((text[i] & 0xC0) != 0x80) return false;
            scalar = (scalar << 6) | (text[i++] & 0x3F);
        }
        if (scalar < minimum || scalar > 0x10FFFF || (scalar >= 0xD800 && scalar <= 0xDFFF) ||
            scalar < 32 || (scalar >= 127 && scalar <= 159)) return false;
    }
    return true;
}

struct Status {
    uint8_t native_version, request_result, request_error, requested_mode, applied_mode, state, error_domain;
    uint32_t client_session, request_sequence, native_operation, policy_generation, bond_generation, connection_generation;
    uint16_t flags, enrollment_remaining;
    int32_t error_code;
    uint32_t reason, last_disconnect_generation;
    uint8_t target[8], connected[8];
};
inline bool clean_paused(const Status &status) {
    const uint16_t required = READY | PERSISTED;
    const uint16_t active = ADVERTISING | CONNECTED_FLAG;
    return status.requested_mode == PAUSED && status.applied_mode == PAUSED && status.state == PAUSED_STATE &&
           (status.flags & required) == required && !(status.flags & active) &&
           !status.error_domain && !status.error_code;
}
struct Peer { uint8_t id[8], flags; char alias[MAX_ALIAS + 1]; };
struct PeerList { uint32_t bond_generation; uint8_t count; Peer peers[MAX_PEERS]; };

class Decoder {
public:
    Status status;
    PeerList list;
    uint32_t session, status_sequence;

    Decoder() { reset(); }
    void reset() {
        memset(&status, 0, sizeof(status)); memset(&list, 0, sizeof(list));
        memset(assembly_, 0, sizeof(assembly_)); memset(retired_, 0, sizeof(retired_));
        session = status_sequence = list_sequence_ = 0;
        have_status_ = have_list_ = false; status_expired_ = list_expired_ = false;
        status_at_ = list_at_ = 0; retired_count_ = retired_next_ = 0;
    }
    // A local radio/channel/sleep interruption invalidates observations, not
    // the controller boot history or sequence anti-replay baselines. Keeping
    // have_* also rejects an identical cached publication after the link returns.
    void invalidate_freshness() {
        memset(assembly_, 0, sizeof(assembly_));
        status_expired_ = list_expired_ = true;
    }
    bool fresh_status(uint32_t now) const {
        if (!have_status_ || status_expired_) return false;
        if (static_cast<uint32_t>(now - status_at_) >= FRESH_MS) status_expired_ = true;
        return !status_expired_;
    }
    bool fresh_list(uint32_t now) const {
        if (!have_list_ || list_expired_) return false;
        if (static_cast<uint32_t>(now - list_at_) >= FRESH_MS) list_expired_ = true;
        return !list_expired_;
    }
    uint32_t status_age(uint32_t now) const { return fresh_status(now) ? now - status_at_ : 0xFFFFFFFFU; }
    bool supported(uint32_t now) const { return fresh_status(now) && status.native_version == 1 && status.state != UNSUPPORTED; }
    bool coherent_list(uint32_t now) const {
        return supported(now) && fresh_list(now) && list.bond_generation == status.bond_generation;
    }
    const Peer *find(const uint8_t *id, uint32_t now) const {
        if (!coherent_list(now) || !id || id_none(id)) return nullptr;
        for (size_t i = 0; i < list.count; ++i) if (same_id(id, list.peers[i].id)) return &list.peers[i];
        return nullptr;
    }

    // True only after a new complete validated status/list is committed.
    bool accept(const uint8_t *frame, size_t length, uint32_t now) {
        if (!frame || length < 20 || length > 64 || memcmp(frame, "BHP1", 4) ||
            ble_status::crc16(frame, length - 2) != ble_status::read16(frame + length - 2)) return false;
        const uint32_t incoming_session = ble_status::read32(frame + 4), sequence = ble_status::read32(frame + 8);
        const uint8_t kind = frame[12], index = frame[13], count = frame[14];
        const size_t total = ble_status::read16(frame + 15);
        if (!incoming_session || kind < 1 || kind > 2 || !total || total > MAX_BODY ||
            count != (total + FRAGMENT_DATA - 1) / FRAGMENT_DATA || count > MAX_FRAGMENTS || index >= count) return false;
        const size_t piece = index + 1 < count ? FRAGMENT_DATA : total - index * FRAGMENT_DATA;
        if (length != 19 + piece || (kind == 1 && total != STATUS_BYTES) ||
            (kind == 2 && (total < 6 || total > 278))) return false;
        for (size_t i = 0; i < retired_count_; ++i) if (retired_[i] == incoming_session) return false;
        if (incoming_session == session) {
            if (kind == 1 && have_status_ && !newer(sequence, status_sequence)) return false;
            if (kind == 2 && have_list_ && !newer(sequence, list_sequence_)) return false;
        }
        Assembly &a = assembly_[kind - 1];
        if (a.have && a.session == incoming_session && a.sequence == sequence) {
            if (a.poisoned || static_cast<uint32_t>(now - a.started) >= ASSEMBLY_MS) { a.poisoned = true; return false; }
            if (a.total != total || a.count != count) { a.poisoned = true; return false; }
        } else {
            if (a.have && a.session == incoming_session && !newer(sequence, a.sequence)) return false;
            memset(&a, 0, sizeof(a)); a.have = true; a.session = incoming_session;
            a.sequence = sequence; a.total = total; a.count = count; a.started = now;
        }
        const uint8_t bit = static_cast<uint8_t>(1U << index);
        uint8_t *destination = a.bytes + index * FRAGMENT_DATA;
        if (a.received & bit) {
            if (memcmp(destination, frame + 17, piece)) a.poisoned = true;
            return false;  // An identical duplicate never refreshes freshness.
        }
        memcpy(destination, frame + 17, piece); a.received |= bit;
        if (a.received != static_cast<uint8_t>((1U << count) - 1)) return false;
        Status incoming_status = {};
        PeerList incoming_list = {};
        if (!(kind == 1 ? decode_status(a.bytes, total, incoming_status) : decode_list(a.bytes, total, incoming_list))) {
            a.poisoned = true; return false;
        }
        commit_session(incoming_session);
        if (kind == 1) {
            status = incoming_status; status_sequence = sequence; status_at_ = now;
            have_status_ = true; status_expired_ = false;
        } else {
            list = incoming_list; list_sequence_ = sequence; list_at_ = now;
            have_list_ = true; list_expired_ = false;
        }
        return true;
    }

private:
    struct Assembly {
        bool have, poisoned;
        uint32_t session, sequence, started;
        size_t total;
        uint8_t count, received, bytes[MAX_BODY];
    } assembly_[2];
    bool have_status_, have_list_;
    mutable bool status_expired_, list_expired_;
    uint32_t status_at_, list_at_, list_sequence_, retired_[8];
    uint8_t retired_count_, retired_next_;

    void commit_session(uint32_t incoming) {
        if (session == incoming) return;
        if (session) {
            retired_[retired_next_] = session; retired_next_ = (retired_next_ + 1) % 8;
            if (retired_count_ < 8) ++retired_count_;
        }
        session = incoming; have_status_ = have_list_ = false;
        status_expired_ = list_expired_ = false;
        // Keep only fragments belonging to this newly validated boot.
        for (size_t i = 0; i < 2; ++i) if (assembly_[i].session != incoming) memset(&assembly_[i], 0, sizeof(Assembly));
    }
    static bool decode_status(const uint8_t *p, size_t size, Status &s) {
        if (size != STATUS_BYTES || p[0] > 1 || p[1] > 4 || p[2] > 11 ||
            !valid_mode(p[27]) || !valid_mode(p[28]) || p[29] > UNSUPPORTED ||
            (ble_status::read16(p + 30) & ~0x1FFU) || p[32] > 4 || ble_status::read16(p + 45) > 120) return false;
        s.native_version = p[0]; s.request_result = p[1]; s.request_error = p[2];
        s.client_session = ble_status::read32(p + 3); s.request_sequence = ble_status::read32(p + 7);
        s.native_operation = ble_status::read32(p + 11); s.policy_generation = ble_status::read32(p + 15);
        s.bond_generation = ble_status::read32(p + 19); s.connection_generation = ble_status::read32(p + 23);
        s.requested_mode = p[27]; s.applied_mode = p[28]; s.state = p[29];
        s.flags = ble_status::read16(p + 30); s.error_domain = p[32];
        const uint32_t code = ble_status::read32(p + 33);
        s.error_code = code <= 0x7FFFFFFFU ? static_cast<int32_t>(code) : -1 - static_cast<int32_t>(~code);
        s.reason = ble_status::read32(p + 37); s.last_disconnect_generation = ble_status::read32(p + 41);
        s.enrollment_remaining = ble_status::read16(p + 45);
        memcpy(s.target, p + 47, 8); memcpy(s.connected, p + 55, 8);
        return true;
    }
    static bool decode_list(const uint8_t *p, size_t size, PeerList &out) {
        if (size < 6 || p[0] != 1 || p[5] > MAX_PEERS) return false;
        out.bond_generation = ble_status::read32(p + 1); out.count = p[5];
        size_t offset = 6;
        for (size_t i = 0; i < out.count; ++i) {
            if (offset + 10 > size) return false;
            Peer &peer = out.peers[i]; memcpy(peer.id, p + offset, 8);
            peer.flags = p[offset + 8]; const size_t bytes = p[offset + 9]; offset += 10;
            if (id_none(peer.id) || (peer.flags & ~31U) || offset + bytes > size || !valid_alias(p + offset, bytes)) return false;
            for (size_t prior = 0; prior < i; ++prior) if (same_id(peer.id, out.peers[prior].id)) return false;
            memcpy(peer.alias, p + offset, bytes); peer.alias[bytes] = 0; offset += bytes;
        }
        return offset == size;
    }
};

inline size_t command(uint8_t *out, size_t capacity, uint32_t controller, uint32_t client,
                      uint32_t request, Opcode op, uint32_t generation,
                      const uint8_t *target = nullptr, const uint8_t *payload = nullptr, size_t payload_size = 0) {
    if (!out || !controller || !client || capacity < 32 + payload_size || payload_size > MAX_ALIAS || op < LIST || op > FORGET) return 0;
    const bool has_target = target && !id_none(target);
    if ((op == SELECT || op == ALIAS || op == FORGET) != has_target) return 0;
    if ((op == LIST || op == DISCONNECT || op == SELECT || op == FORGET) && payload_size) return 0;
    if (op == ALIAS && !valid_alias(payload, payload_size)) return 0;
    if (op == ENROLL && (!payload || payload_size != 2 || ble_status::read16(payload) < 5 || ble_status::read16(payload) > 120)) return 0;
    memcpy(out, "BHC1", 4); put32(out + 4, controller); put32(out + 8, client); put32(out + 12, request);
    out[16] = op; put32(out + 17, generation); memset(out + 21, 0, 8);
    if (has_target) memcpy(out + 21, target, 8);
    out[29] = payload_size;
    if (payload_size) memcpy(out + 30, payload, payload_size);
    const size_t size = 32 + payload_size; put16(out + size - 2, ble_status::crc16(out, size - 2));
    return size;
}

class Control {
public:
    Decoder decoder;
    Result result;
    uint32_t client_session;
    explicit Control(uint32_t client = 1, uint32_t initial_sequence = 0) : client_session(client ? client : 1) {
        clear(); sequence_ = initial_sequence;
    }
    void set_client_session(uint32_t value) { client_session = value ? value : 1; }
    void invalidate_link() {
        const bool was_pending = holding(); decoder.invalidate_freshness(); selected_ = false;
        pending_ = false; observed_session_ = 0; reset_admission(); result = was_pending ? RESTARTED : IDLE;
    }
    bool holding() const { return handshake_waiting_ || (pending_ && (result == PENDING || result == PAIRING)); }
    bool admitted(uint32_t now) const { return admitted_ && admission_session_ == decoder.session && decoder.supported(now); }
    bool can_manage(uint32_t now) const { return admitted(now); }
    const Peer *selection(uint32_t now) const { return selected_ ? decoder.find(selected_id_, now) : nullptr; }
    bool choose(size_t index, uint32_t now) {
        if (!can_manage(now) || !decoder.coherent_list(now) || index >= decoder.list.count) { selected_ = false; return false; }
        memcpy(selected_id_, decoder.list.peers[index].id, 8); selected_ = true; return true;
    }
    void clear_selection() { selected_ = false; }
    bool can_connect(uint32_t now) const {
        const Peer *peer = selection(now);
        return can_manage(now) && !holding() && peer && (peer->flags & RESUMABLE);
    }
    bool can_alias(uint32_t now) const { return can_manage(now) && !holding() && selection(now); }
    bool can_forget(uint32_t now) const {
        const Peer *peer = selection(now);
        return can_manage(now) && !holding() && peer && !(peer->flags & PEER_CONNECTED) &&
               clean_paused(decoder.status);
    }
    Opcode last_opcode() const { return opcode_; }

    // Discovery is read-only. Unknown/rebooted clients establish admission with
    // a recent complete STATUS sequence, not by sending a mutating command.
    // A single challenge gets at most three identical application attempts;
    // after its deadline a fresh STATUS/challenge and request ID are required.
    size_t handshake_request(uint32_t now, uint8_t *frame, size_t capacity) {
        tick(now);
        if (!frame || capacity < 32 || admitted(now) || !decoder.supported(now) || decoder.status_age(now) >= 3000 ||
            (pending_ && (result == PENDING || result == PAIRING))) return 0;
        if (handshake_waiting_) {
            if (handshake_attempts_ >= 3 || static_cast<uint32_t>(now - handshake_last_send_) < HANDSHAKE_RETRY_MS) return 0;
            ++handshake_attempts_; handshake_last_send_ = now;
            memcpy(frame, handshake_frame_, 32); return 32;
        }
        if (handshake_cooldown_ && static_cast<uint32_t>(now - handshake_retry_at_) >= 0x80000000U) return 0;
        if (have_challenge_ && challenge_session_ == decoder.session && last_challenge_ == decoder.status_sequence) return 0;
        const uint32_t request = sequence_ + 1;
        const size_t size = command(handshake_frame_, sizeof(handshake_frame_), decoder.session, client_session,
                                    request, LIST, decoder.status_sequence);
        if (!size) return 0;
        // An already applied offline policy remains native-owned; this LIST
        // does not cancel it or automatically connect/enroll another host.
        pending_ = false; sequence_ = request; handshake_request_ = request;
        handshake_session_ = challenge_session_ = decoder.session; last_challenge_ = decoder.status_sequence;
        have_challenge_ = handshake_waiting_ = true; handshake_cooldown_ = false;
        handshake_started_ = handshake_last_send_ = now; handshake_attempts_ = 1;
        memcpy(frame, handshake_frame_, size); return size;
    }
    size_t begin(Opcode op, uint32_t now, uint8_t *frame, size_t capacity,
                 const char *alias = nullptr, uint16_t enrollment_seconds = 60) {
        if (!can_manage(now) || (op != DISCONNECT && holding())) return 0;
        const Peer *peer = selection(now);
        if (op == SELECT && (!peer || !(peer->flags & RESUMABLE))) return 0;
        if (op == ALIAS && !peer) return 0;
        if (op == FORGET && !can_forget(now)) return 0;
        uint8_t seconds[2]; put16(seconds, enrollment_seconds);
        const size_t alias_size = alias ? strlen(alias) : 0;
        const uint8_t *payload = op == ENROLL ? seconds : reinterpret_cast<const uint8_t *>(alias);
        const size_t bytes = op == ENROLL ? 2 : op == ALIAS ? alias_size : 0;
        const uint32_t request = sequence_ + 1;
        const size_t length = command(frame, capacity, decoder.session, client_session, request, op,
                                      op == LIST ? decoder.status_sequence : (op == SELECT || op == ALIAS || op == FORGET) ? decoder.status.bond_generation : 0,
                                      (op == SELECT || op == ALIAS || op == FORGET) ? peer->id : nullptr,
                                      payload, bytes);
        if (!length) return 0;
        sequence_ = request; request_ = request; opcode_ = op; session_ = decoder.session;
        baseline_ = decoder.status_sequence; baseline_operation_ = decoder.status.native_operation;
        operation_ = 0; observed_own_ = false; bond_generation_ = decoder.status.bond_generation;
        sent_at_ = now; timeout_ = REQUEST_MS + (op == ENROLL ? enrollment_seconds * 1000U : 0);
        memset(target_, 0, sizeof(target_)); if (peer && (op == SELECT || op == ALIAS || op == FORGET)) memcpy(target_, peer->id, 8);
        memset(alias_, 0, sizeof(alias_)); if (op == ALIAS && bytes) memcpy(alias_, alias, bytes);
        pending_ = true; result = PENDING; return length;
    }
    void not_sent() { pending_ = false; result = NOT_SENT; }
    void tick(uint32_t now) {
        if (decoder.session && observed_session_ && decoder.session != observed_session_) {
            observed_session_ = decoder.session; selected_ = false; reset_admission(); finish(RESTARTED); return;
        }
        if (decoder.session) observed_session_ = decoder.session;
        if (!decoder.fresh_status(now)) admitted_ = false;
        if (handshake_waiting_ && static_cast<uint32_t>(now - handshake_started_) >= HANDSHAKE_DEADLINE_MS) defer_handshake(now);
        if (handshake_waiting_ && decoder.fresh_status(now) && decoder.session == handshake_session_ &&
            newer(decoder.status_sequence, last_challenge_)) {
            const Status &state = decoder.status;
            if (state.client_session == client_session && state.request_sequence == handshake_request_) {
                if (state.request_result == 4 && (state.flags & READY) && decoder.coherent_list(now)) {
                    admitted_ = true; admission_session_ = decoder.session;
                    handshake_waiting_ = handshake_cooldown_ = false;
                    if (!pending_) result = IDLE;
                } else if (state.request_result == 2) defer_handshake(now);
            }
        }
        if (selected_ && decoder.coherent_list(now) && !decoder.find(selected_id_, now)) selected_ = false;
        if (!pending_) return;
        if (decoder.session && decoder.session != session_) { finish(RESTARTED); return; }
        if (decoder.fresh_status(now) && newer(decoder.status_sequence, baseline_)) {
            const Status &s = decoder.status;
            if (s.client_session == client_session && s.request_sequence == request_) {
                observed_own_ = true;
                if (s.request_result == 2) {
                    if (s.request_error == 11) { admitted_ = false; defer_handshake(now); }
                    finish(REJECTED); return;
                }
                if (opcode_ == LIST && (s.flags & READY) && s.request_result == 4 && decoder.coherent_list(now)) { finish(CONFIRMED); return; }
                if (s.native_operation && s.native_operation != baseline_operation_) {
                    if (operation_ && operation_ != s.native_operation) { finish(SUPERSEDED); return; }
                    operation_ = s.native_operation;
                }
                if (operation_ && s.native_operation == operation_ && (s.flags & READY)) {
                    // Native bounded enrollment expiry is deliberately PAUSED
                    // with the full POLICY/HP_TIMEOUT diagnostic retained.
                    // It closes the window; it never confirms a connection.
                    if (opcode_ == ENROLL && (s.flags & PERSISTED) && s.state == PAUSED_STATE &&
                        s.requested_mode == PAUSED && s.applied_mode == PAUSED &&
                        !(s.flags & (CONNECTED_FLAG | ADVERTISING)) && !s.enrollment_remaining &&
                        s.error_domain == 1 && s.error_code == 6) { finish(ENROLLMENT_ENDED); return; }
                    if (s.state == ERROR_STATE || s.error_domain || s.error_code) { finish(FAILED); return; }
                    const bool persisted = (s.flags & PERSISTED) != 0;
                    if (opcode_ == DISCONNECT && persisted && s.requested_mode == PAUSED && s.applied_mode == PAUSED &&
                        s.state == PAUSED_STATE && !(s.flags & (CONNECTED_FLAG | ADVERTISING))) { finish(CONFIRMED); return; }
                    const uint16_t ready = CONNECTED_FLAG | ENCRYPTED | BONDED | HID_READY | PERSISTED | FILTER_READY;
                    const bool connected = s.requested_mode == AUTO && s.applied_mode == AUTO && s.state == CONNECTED &&
                                           (s.flags & ready) == ready && !s.error_domain && !id_none(s.target) && same_id(s.target, s.connected);
                    if (opcode_ == SELECT && same_id(s.target, target_)) {
                        if (connected) { finish(CONFIRMED); return; }
                        if (persisted && (s.flags & FILTER_READY) && s.requested_mode == AUTO && s.applied_mode == AUTO && s.state == WAITING) result = WAITING_HOST;
                    } else if (opcode_ == ENROLL) {
                        if (connected) { finish(CONFIRMED); return; }
                        if (s.state == ENROLLING) result = PAIRING;
                        else if (persisted && s.state == PAUSED_STATE && s.requested_mode == PAUSED && s.applied_mode == PAUSED) { finish(ENROLLMENT_ENDED); return; }
                    } else if (opcode_ == FORGET && s.request_result == 3 && clean_paused(s) &&
                               !same_id(s.target, target_) && s.bond_generation != bond_generation_ &&
                               decoder.coherent_list(now) && !decoder.find(target_, now)) {
                        finish(CONFIRMED); return;
                    } else if (opcode_ == ALIAS && s.request_result == 3 && persisted) {
                        const Peer *peer = decoder.find(target_, now);
                        if (peer && strcmp(peer->alias, alias_) == 0) { finish(CONFIRMED); return; }
                    }
                }
            } else if (observed_own_ && (s.request_result == 1 || s.request_result == 3 || s.request_result == 4)) { finish(SUPERSEDED); return; }
        }
        if (result != WAITING_HOST && static_cast<uint32_t>(now - sent_at_) >= timeout_) finish(TIMED_OUT);
    }

private:
    bool selected_, pending_, observed_own_;
    bool admitted_, handshake_waiting_, handshake_cooldown_, have_challenge_;
    uint8_t selected_id_[8], target_[8];
    uint8_t handshake_frame_[32], handshake_attempts_;
    char alias_[MAX_ALIAS + 1];
    uint32_t sequence_, request_, session_, observed_session_, baseline_, baseline_operation_, operation_, bond_generation_, sent_at_, timeout_;
    uint32_t admission_session_, handshake_request_, handshake_session_, handshake_started_, handshake_last_send_,
             handshake_retry_at_, challenge_session_, last_challenge_;
    Opcode opcode_;
    void clear() {
        decoder.reset(); result = IDLE; selected_ = pending_ = observed_own_ = false;
        memset(selected_id_, 0, 8); memset(target_, 0, 8); memset(alias_, 0, sizeof(alias_));
        sequence_ = request_ = session_ = observed_session_ = baseline_ = baseline_operation_ = operation_ = bond_generation_ = sent_at_ = timeout_ = 0; opcode_ = LIST;
        reset_admission();
    }
    void reset_admission() {
        admitted_ = handshake_waiting_ = handshake_cooldown_ = have_challenge_ = false;
        handshake_attempts_ = 0; memset(handshake_frame_, 0, sizeof(handshake_frame_));
        admission_session_ = handshake_request_ = handshake_session_ = handshake_started_ = handshake_last_send_ =
            handshake_retry_at_ = challenge_session_ = last_challenge_ = 0;
    }
    void defer_handshake(uint32_t now) {
        handshake_waiting_ = false; handshake_cooldown_ = true; handshake_retry_at_ = now + HANDSHAKE_COOLDOWN_MS;
    }
    void finish(Result value) { pending_ = false; result = value; }
};

}  // namespace ble_host_policy
