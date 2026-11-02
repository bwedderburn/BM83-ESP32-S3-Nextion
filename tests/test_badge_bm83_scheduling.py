"""Keep artwork outside authenticated UDP transactions, with a fake clock/socket.

No network, device, artwork download, real sleep or badge runtime is started.
The slow-artwork fixture represents an indivisible background operation; this
cannot prove that DNS or the physical firmware's fetch implementation yields.
"""
from types import SimpleNamespace
from unittest.mock import Mock, patch

import tempfile
import unittest

from tests.test_badge_bm83_remote import FakeSocket, KEY, PEER, snapshot
from tests.test_badge_bm83_ui import FakeBadge, method_class, models, protocol, transport


class Clock:
    def __init__(self, now=0):
        self.now = now & 0xffffffff

    def advance(self, ms):
        self.now = (self.now + ms) & 0xffffffff


class ClockBadge(FakeBadge):
    def __init__(self, clock):
        super().__init__()
        self.clock = clock

    @property
    def ticks(self):
        return self.clock.now


class Artwork:
    def __init__(self, clock, delay=0):
        self.clock, self.delay = clock, delay
        self.calls = []
        self.cancelled = False

    def start(self, artist, album, now):
        self.calls.append(('start', artist, album, now))
        self.clock.advance(self.delay)

    def retry(self, now):
        self.calls.append(('retry', now))
        self.clock.advance(self.delay)

    def step(self, now, connected):
        self.calls.append(('step', now, connected))
        if connected:
            self.clock.advance(self.delay)
        else:
            self.cancelled = True


def app(now=0, delay=0):
    clock = Clock(now)
    badge = ClockBadge(clock)
    udp = FakeSocket()
    with patch.object(transport.socket, 'socket', return_value=udp):
        remote = transport.Remote(PEER[0], PEER[1], KEY)
    remote.unit, remote.client = '01020304', 7
    remote.last_poll = clock.now
    remote.playback.accept(snapshot(), clock.now)
    cls = method_class(names=('step', 'input', '_control', '_settings', 'update', '_artwork_idle'),
                       badge=badge, Remote=transport.Remote,
                       clamp_setting_index=models.clamp_setting_index,
                       LOCAL_RETRY_FEEDBACK='Local retry: badge Wi-Fi/artwork only')
    value = cls()
    value.remote, value.artwork = remote, Artwork(clock, delay)
    value.playback, value.ble = remote.playback, remote.ble
    value.sample_mode, value.config_error = False, False
    value.page, value.hold_action = 'now', None
    value.erase_confirm, value.setting_index, value.confirm_choice = False, 0, 0
    value.last_art_key, value.artwork_retry_pending = None, False
    value._wifi = lambda now: True
    value.wifi_ready, value.wifi_error, value.next_wifi = True, '', 0
    value.feedback, value.unit_status = 'Audio unit authenticated', 'Authenticated'
    value.draws = []
    value.draw = value.draws.append
    return value, badge, clock, udp


def state_reply(udp, remote, **changes):
    state = {'v': 1, 'type': 'state', 'unit': remote.unit, 'client': remote.client,
             'seq': remote.seq, 'dup': False, 'np': snapshot(**changes)}
    udp.incoming.append((protocol.encode(KEY, state, 1200), PEER))


def tokens(udp):
    return [protocol.decode(KEY, wire).get('token') for wire, _ in udp.sent]


class SchedulingTests(unittest.TestCase):
    def test_actual_artwork_clock_recovery_waits_for_udp_idle_and_local_retry_rearms(self):
        from tests.test_badge_bm83_artwork import artwork, FakeCore
        for busy in ('hello', 'normal_queue', 'volume_queue', 'held_volume', 'release'):
            with self.subTest(busy=busy), tempfile.TemporaryDirectory() as directory:
                recovery = SimpleNamespace(message='Artwork needs a valid UTC clock',
                                           step=Mock(return_value=False), rearm=Mock())
                with patch.object(artwork, 'ClockRecovery', return_value=recovery), \
                        patch.object(artwork, 'clock_ready', return_value=False), \
                        patch.object(artwork, 'fetch', SimpleNamespace(AsyncFetch=FakeCore)):
                    value, badge, clock, udp = app()
                    value.artwork = artwork.Artwork(directory)
                    value.artwork.start('Artist', 'Album', 0)
                    value.last_art_key = ('Artist', 'Album')
                    assert value.artwork.stage == 'clock-wait'
                    if busy == 'hello':
                        value.remote.unit = value.remote.client = None
                    elif busy == 'normal_queue':
                        value.remote.queue_command('BT_NEXT')
                    elif busy == 'volume_queue':
                        value.remote.volume_queue = [
                            {'command': 'BT_VOLUP', 'pressed': True, 'released': False}]
                    elif busy == 'held_volume':
                        value.remote.held_volume = 'BT_VOLUP'
                    else:
                        value.remote._command('BT_VOLUP_R', clock.now)
                    value.update()
                    recovery.step.assert_not_called()
                    value.page, value.setting_index = 'settings', 4
                    badge.frame(pressed=('select',))
                    value.input(clock.now)
                    recovery.rearm.assert_called_once_with()
                    recovery.step.assert_not_called()
                    assert value.artwork_retry_pending
        # Only a later authenticated-idle pump may actually attempt NTP.
        with tempfile.TemporaryDirectory() as directory:
            recovery = SimpleNamespace(message='Artwork needs a valid UTC clock',
                                       step=Mock(return_value=False), rearm=Mock())
            with patch.object(artwork, 'ClockRecovery', return_value=recovery), \
                    patch.object(artwork, 'clock_ready', return_value=False), \
                    patch.object(artwork, 'fetch', SimpleNamespace(AsyncFetch=FakeCore)):
                value, badge, clock, udp = app()
                value.artwork = artwork.Artwork(directory)
                value.artwork.start('Artist', 'Album', 0)
                value.last_art_key = ('Artist', 'Album')
                value.update()
                recovery.step.assert_called_once_with(0)

    def test_lost_first_status_reply_retries_before_slow_artwork_runs(self):
        for start in [0, 4294967232]:
            with self.subTest(start=start):
                value, badge, clock, udp = app(start, delay=650)
                value.last_art_key = ('Artist', 'Album')
                value.remote.last_poll = (start - 1000) & 0xffffffff
                value.update()  # STATUS sent; the first reply is deliberately lost.
                assert value.artwork.calls == []
                assert clock.now == start
                assert tokens(udp) == ['STATUS']
                clock.advance(150)
                value.update()
                assert tokens(udp) == ['STATUS', 'STATUS']
                assert value.artwork.calls == []
                state_reply(udp, value.remote)
                clock.advance(10)
                value.update()
                assert value.remote.pending is None
                assert value.remote.playback.fresh(clock.now)
                assert 'no reply' not in value.feedback
                assert value.artwork.calls == [('step', (start + 160) & 0xffffffff, True)]
                assert value.draws[-1] == clock.now == (start + 810) & 0xffffffff

    def test_buffered_status_reply_survives_a_gap_without_deadline_relaxation(self):
        value, badge, clock, udp = app()
        value.last_art_key = ('Artist', 'Album')
        value.remote.last_poll = -1000
        value.update()
        state_reply(udp, value.remote)
        clock.advance(650)
        value.update()
        assert value.remote.pending is None
        assert value.remote.playback.received == 650
        assert value.remote.playback.fresh(650)
        assert 'no reply' not in value.feedback
        assert transport.REPLY_TIMEOUT_MS == 600

    def test_busy_or_unauthenticated_remote_defers_start_and_pump(self):
        for busy in ['hello', 'normal_queue', 'volume_queue', 'held_volume', 'release']:
            with self.subTest(busy=busy):
                value, badge, clock, udp = app()
                if busy == 'hello':
                    value.remote.unit = value.remote.client = None
                elif busy == 'normal_queue':
                    value.remote.queue_command('BT_NEXT')
                elif busy == 'volume_queue':
                    value.remote.volume_queue = [{'command': 'BT_VOLUP', 'pressed': True, 'released': False}]
                elif busy == 'held_volume':
                    value.remote.held_volume = 'BT_VOLUP'
                else:
                    value.remote._command('BT_VOLUP_R', clock.now)
                value.update()
                assert value.artwork.calls == []
                assert value.last_art_key is None

    def test_release_reply_is_serviced_before_deferred_artwork_start(self):
        value, badge, clock, udp = app()
        value.remote._command('BT_VOLUP_R', clock.now)
        value.update()
        assert value.artwork.calls == []
        state_reply(udp, value.remote)
        clock.advance(10)
        value.update()
        assert value.remote.pending is None
        assert value.artwork.calls == [('start', 'Artist', 'Album', 10)]

    def test_only_latest_album_starts_after_pending_transaction_completes(self):
        value, badge, clock, udp = app()
        value.remote._command('STATUS', clock.now)
        value.update()
        assert value.last_art_key is None
        value.remote.playback.accept(snapshot(album='Album B'), 10)
        clock.advance(10)
        value.update()
        assert value.artwork.calls == [] and value.last_art_key is None
        state_reply(udp, value.remote, album='Album C')
        clock.advance(10)
        value.update()
        assert value.last_art_key == ('Artist', 'Album C')
        assert value.artwork.calls == [('start', 'Artist', 'Album C', 20)]

    def test_offline_artwork_cancel_still_runs_with_pending_remote_transaction(self):
        value, badge, clock, udp = app()
        value.remote._command('STATUS', clock.now)
        value._wifi = lambda now: False
        value.update()
        assert value.artwork.calls == [('step', 0, False)]
        assert value.artwork.cancelled
        assert value.last_art_key is None

    def test_local_retry_is_deferred_until_the_authenticated_remote_is_idle(self):
        value, badge, clock, udp = app(delay=650)
        value.last_art_key = ('Artist', 'Album')
        value.page, value.setting_index = 'settings', 4
        value.remote._command('STATUS', clock.now)
        badge.frame(pressed=('select',))
        value.input(clock.now)
        assert value.artwork.calls == []
        assert value.artwork_retry_pending
        assert not value.wifi_ready
        badge.frame()
        value.update()
        assert value.artwork.calls == [] and value.artwork_retry_pending
        state_reply(udp, value.remote)
        clock.advance(10)
        value.update()
        assert value.artwork.calls == [('retry', 10)]
        assert not value.artwork_retry_pending
        assert value.draws[-1] == 660

    def test_deferred_retry_uses_new_latest_album_instead_of_restarting_old_art(self):
        value, badge, clock, udp = app()
        value.last_art_key = ('Artist', 'Old album')
        value.artwork_retry_pending = True
        value.remote.playback.accept(snapshot(album='New album'), clock.now)
        value.update()
        assert value.artwork.calls == [('start', 'Artist', 'New album', 0)]
        assert value.last_art_key == ('Artist', 'New album')
        assert not value.artwork_retry_pending

    def test_reconnection_preserves_deferred_retry_until_fresh_state_is_available(self):
        value, badge, clock, udp = app()
        value.last_art_key = ('Artist', 'Album')
        value.artwork_retry_pending = True
        value._wifi = lambda now: False
        value.update()
        assert value.artwork_retry_pending
        clock.advance(7000)
        value._wifi = lambda now: True
        value.update()
        assert value.artwork_retry_pending
        assert value.artwork.calls == [('step', 0, False)]
        state_reply(udp, value.remote)
        clock.advance(10)
        value.update()
        assert value.artwork.calls[-1] == ('retry', 7010)
        assert not value.artwork_retry_pending

    def test_slow_background_work_does_not_render_an_expired_snapshot_as_fresh(self):
        value, badge, clock, udp = app(delay=6500)
        rendered_freshness = []
        value.draw = lambda now: rendered_freshness.append(value.playback.fresh(now))
        value.update()
        assert rendered_freshness == [False]

    def test_draw_refreshes_clock_after_one_background_operation(self):
        for start in [0, 4294967232]:
            with self.subTest(start=start):
                value, badge, clock, udp = app(start, delay=650)
                value.update()
                assert value.artwork.calls == [('start', 'Artist', 'Album', start)]
                assert value.draws == [(start + 650) & 0xffffffff]


if __name__ == "__main__":
    unittest.main()
