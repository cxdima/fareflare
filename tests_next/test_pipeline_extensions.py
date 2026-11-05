import json
from dataclasses import asdict
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from gfpt_next.api import create_app
from gfpt_next.credentials import Credentials, RateLimited, RateLimiter
from gfpt_next.delivery import TelegramSink
from gfpt_next.domain import AlertPolicy, evaluate
from gfpt_next.link_resolver import GoogleLinkResolver
from gfpt_next.links import InvalidLink, import_link
from gfpt_next.service import Reading
from gfpt_next.store import Document
from gfpt_next.worker import Worker

SHARE = 'https://www.google.com/travel/flights/s/CtJjhcABupzKqMeB9'


def test_short_links_resolve_without_fetching_the_booking_page(flight_url):
    requests = []
    def route(request):
        requests.append(request)
        return httpx.Response(302, headers={'Location': flight_url})
    resolver = GoogleLinkResolver(httpx.MockTransport(route))
    assert resolver(SHARE)['id'] == import_link(flight_url)['id']
    assert len(requests) == 1
    assert 'cookie' not in requests[0].headers
    assert resolver(flight_url)['id'] == import_link(flight_url)['id']
    assert len(requests) == 1


@pytest.mark.parametrize('destination', ['http://127.0.0.1/', 'https://www.google.com@evil.example/',
                                         'https://www.google.com/url?q=evil', 'https://accounts.google.com/'])
def test_share_redirect_cannot_escape_allowlist(destination):
    calls = []
    def route(request):
        calls.append(request)
        return httpx.Response(302, headers={'Location': destination})
    with pytest.raises(InvalidLink):
        GoogleLinkResolver(httpx.MockTransport(route))(SHARE)
    assert len(calls) == 1


def test_share_redirect_loop_is_bounded():
    calls = []
    def route(request):
        calls.append(request)
        return httpx.Response(302, headers={'Location': SHARE})
    with pytest.raises(InvalidLink, match='Too many'):
        GoogleLinkResolver(httpx.MockTransport(route))(SHARE)
    assert len(calls) == 3


def test_known_attribution_normalizes_but_unknown_fares_do_not(flight_url):
    first = import_link(flight_url)
    assert import_link(flight_url + '&utm_campaign=sharing&source=flre_fli_share')['id'] == first['id']
    assert import_link(flight_url + '&newFareConstraint=yes')['id'] != first['id']
    assert first['offer']['slices'][0]['legs'][0]['airline'] == 'UA'
    assert import_link(json.loads(json.dumps(first))['url']) == first


def test_store_pagination_is_bounded_and_scoped(store):
    store.commit([Document(f'p:{n:02}', 'one', {'n': n}, due=n // 2) for n in range(13)])
    found, cursor = [], None
    while True:
        page = store.page('one', limit=3, cursor=cursor)
        assert len(page.items) <= 3
        found.extend(d.data['n'] for d in page.items)
        cursor = page.cursor
        if cursor is None:
            break
        with pytest.raises(ValueError):
            store.page('other-owner', limit=3, cursor=cursor)
    assert set(found) == set(range(13)) and len(found) == 13
    assert store.page('one', limit=1, reverse=True).items[0].data['n'] == 12
    with pytest.raises(ValueError):
        store.page('one', limit=0)
    with pytest.raises(ValueError):
        store.page('one', cursor='invalid')


def test_credentials_rotate_revoke_expire_without_storing_secrets(store, clock):
    credentials = Credentials(store, lambda: clock[0])
    first, key1 = credentials.issue('alice', 60)
    _, key2 = credentials.issue('alice', 120)
    assert credentials.authenticate(key1) == credentials.authenticate(key2) == 'alice'
    assert key1 not in str(store.get('credential:' + first))
    with pytest.raises(ValueError):
        credentials.revoke('bob', first)
    credentials.revoke('alice', first)
    assert credentials.authenticate(key1) is None
    assert credentials.authenticate(key2) == 'alice'
    clock[0] += 121
    assert credentials.authenticate(key2) is None
    assert credentials.authenticate('invalid') is None


def test_shared_rate_limit_and_api_revocation(service, clock):
    limiter = RateLimiter(service.store, lambda: clock[0], per_minute=2)
    credentials = Credentials(service.store, lambda: clock[0])
    identifier, key = credentials.issue('alice')
    with TestClient(create_app(service, credentials=credentials, limiter=limiter)) as client:
        headers = {'Authorization': 'Bearer ' + key}
        assert client.get('/v1/monitors', headers=headers).status_code == 200
        assert client.get('/v1/monitors', headers=headers).status_code == 200
        assert client.get('/v1/monitors', headers=headers).status_code == 429
        with pytest.raises(RateLimited):
            limiter.consume('alice')
        limiter.consume('bob')
        clock[0] += 60
        assert client.get('/v1/monitors', headers=headers).status_code == 200
        credentials.revoke('alice', identifier)
        assert client.get('/v1/monitors', headers=headers).status_code == 401


def test_rebounds_are_opt_in_and_damped_until_a_new_low():
    policy = AlertPolicy(notify_rebounds=True, min_drop_minor=1000)
    state = {}
    reasons = []
    for amount in (50000, 40000, 41000, 40000, 42000, 39000, 40000):
        state, reason = evaluate(policy, state, amount)
        reasons.append(reason)
    assert reasons == ['tracking_started', 'new_low', 'rebound', None, None, 'new_low', 'rebound']
    assert state['last_alert_minor'] == 39000


def test_account_preferences_suppress_queues_without_stopping_collection(service, clock, flight_url):
    monitor = service.create_monitor('alice', flight_url, 'prefs-regression')
    service.record(Reading(monitor['target_id'], 40000, 'USD', clock[0], 'fixture'), 'one')
    service.process_events()
    service.set_preferences('alice', True, [])
    service.set_preferences('alice', False, [])
    sink = Mock()
    assert service.deliver_due(sink) == 0
    sink.send.assert_not_called()
    service.set_preferences('alice', False, ['DEN-DFW'])
    clock[0] += 900
    service.record(Reading(monitor['target_id'], 35000, 'USD', clock[0], 'fixture'), 'two')
    service.process_events()
    assert len(service.list_deliveries('alice')) == 1
    assert service.get_monitor('alice', monitor['id'])['status'] == 'active'


def test_worker_restart_queues_and_shadow_suppresses_without_external_delivery(service, clock, flight_url):
    monitor = service.create_monitor('alice', flight_url, 'worker-shadow')
    provider = Mock()
    provider.collect.return_value = Reading(monitor['target_id'], 45000, 'USD', clock[0], 'fixture')
    result = Worker(service, provider).tick()
    assert result['collected'] == result['events_processed'] == 1
    assert result['alerts_sent'] == 0 and result['shadow'] is True
    assert service.list_deliveries('alice')[0]['status'] == 'suppressed'
    sink = Mock()
    assert Worker(service, provider, sink).tick()['alerts_sent'] == 0
    sink.send.assert_not_called()


def test_worker_honors_budget_before_starting_browser(service):
    provider = Mock()
    assert Worker(service, provider).tick(budget_seconds=60)['collected'] == 0
    provider.collect.assert_not_called()
    with pytest.raises(ValueError):
        Worker(service, provider).tick(max_targets=0)


def test_telegram_uses_server_destination_and_handles_failure():
    seen = []
    def route(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={'ok': True})
    sink = TelegramSink('123:' + 'a' * 25, {'alice': '111'}, httpx.MockTransport(route))
    delivery = {'tenant': 'alice', 'reason': 'new_low', 'monitor_id': 'abc', 'id': 'd' * 64,
                'observation': asdict(Reading('target', 48706, 'JPY', 123, 'fixture'))}
    assert sink.send(delivery)
    assert seen[0]['chat_id'] == '111'
    assert 'JPY 48,706' in seen[0]['text']
    assert 'parse_mode' not in seen[0]
    assert not sink.send({**delivery, 'tenant': 'bob'})
    failure = TelegramSink('123:' + 'a' * 25, {'alice': '111'}, httpx.MockTransport(
        lambda request: httpx.Response(429, json={'ok': False})))
    assert not failure.send(delivery)


def test_queue_head_promotion_is_atomic_with_concurrent_event_append(service, clock, flight_url):
    monitor = service.create_monitor('alice', flight_url, 'concurrent-append')
    service.record(Reading(monitor['target_id'], 50000, 'USD', clock[0], 'fixture'), 'one')
    service.process_events()
    sink = Mock()
    def send(delivery):
        clock[0] += 1
        service.record(Reading(monitor['target_id'], 40000, 'USD', clock[0], 'fixture'), 'two')
        service.process_events()
        return True
    sink.send.side_effect = send
    assert service.deliver_due(sink) == 1
    sink.send.side_effect = None
    sink.send.return_value = True
    assert service.deliver_due(sink) == 1
    assert [d['observation']['amount_minor'] for d in service.list_deliveries('alice')] == [50000, 40000]
    assert all(d['status'] == 'sent' for d in service.list_deliveries('alice'))


def test_terminal_delivery_retention_does_not_block_future_alerts(tmp_path, flight_url, clock):
    from gfpt_next.service import MonitoringService
    from gfpt_next.store import SQLiteStore
    store = SQLiteStore(tmp_path / 'retention.db')
    service = MonitoringService(store, lambda: clock[0])
    monitor = service.create_monitor('alice', flight_url, 'retention-test')
    service.record(Reading(monitor['target_id'], 50000, 'USD', clock[0], 'fixture'), 'one')
    service.process_events()
    sink = Mock()
    sink.send.return_value = True
    service.deliver_due(sink)
    # Exercise retention directly without pretending a departed flight can collect.
    delivery = store.get('delivery:' + service.list_deliveries('alice')[0]['id'])
    store.commit([delivery.update(delivery.data, expires_at=clock[0])])
    assert store.purge_expired(clock[0]) == 1
    clock[0] += 900
    service.record(Reading(monitor['target_id'], 40000, 'USD', clock[0], 'fixture'), 'two')
    service.process_events()
    assert service.deliver_due(sink) == 1


def test_lambda_runtime_defaults_to_shadow_and_rejects_other_events(service, monkeypatch):
    from gfpt_next import runtime
    context = Mock()
    context.get_remaining_time_in_millis.return_value = 180000
    with pytest.raises(ValueError):
        runtime.handler({'source': 'telegram'}, context)
    worker = Mock()
    worker.service = service
    worker.tick.return_value = {'collected': 1, 'shadow': True}
    monkeypatch.setattr(runtime, 'build_worker', lambda: worker)
    assert runtime.handler({'source': 'gfpt-next.scheduler'}, context)['shadow'] is True
    worker.tick.assert_called_once_with(max_targets=1, budget_seconds=150)
    assert service.store.get('health:worker').data['collected'] == 1


def test_runtime_only_loads_telegram_secret_when_delivery_is_enabled(service, monkeypatch):
    from gfpt_next import runtime
    monkeypatch.setenv('GFPT_NEXT_TABLE', 'gfpt-next-tests')
    monkeypatch.delenv('GFPT_NEXT_DELIVERY', raising=False)
    monkeypatch.setattr(runtime, 'DynamoStore', lambda *args, **kwargs: service.store)
    aws = Mock()
    monkeypatch.setattr(runtime.boto3, 'client', aws)
    assert runtime.build_worker().sink is None
    aws.assert_not_called()
    monkeypatch.setenv('GFPT_NEXT_DELIVERY', 'telegram')
    monkeypatch.setenv('GFPT_NEXT_TELEGRAM_SECRET_ARN', 'test-secret')
    aws.return_value.get_secret_value.return_value = {'SecretString': json.dumps({
        'bot_token': '123:' + 'a' * 25, 'recipients': {'alice': '111'}})}
    assert isinstance(runtime.build_worker().sink, TelegramSink)


def test_muted_prices_do_not_advance_the_last_queued_alert_baseline(service, clock, flight_url):
    monitor = service.create_monitor('alice', flight_url, 'muted-baseline', AlertPolicy(min_drop_minor=1000))
    service.record(Reading(monitor['target_id'], 50000, 'USD', clock[0], 'fixture'), 'one')
    service.process_events()
    sink = Mock()
    sink.send.return_value = True
    service.deliver_due(sink)
    service.set_preferences('alice', True, [])
    clock[0] += 900
    service.record(Reading(monitor['target_id'], 49000, 'USD', clock[0], 'fixture'), 'muted-low')
    service.process_events()
    service.set_preferences('alice', False, [])
    clock[0] += 900
    service.record(Reading(monitor['target_id'], 48900, 'USD', clock[0], 'fixture'), 'unmuted-low')
    service.process_events()
    assert [d['reason'] for d in service.list_deliveries('alice')] == ['tracking_started', 'new_low']


def test_repeated_preferences_update_does_not_suppress_queued_price_alert(service, clock, flight_url):
    monitor = service.create_monitor('alice', flight_url, 'idempotent-prefs')
    service.record(Reading(monitor['target_id'], 50000, 'USD', clock[0], 'fixture'), 'one')
    service.process_events()
    service.set_preferences('alice', False, [])
    service.set_preferences('alice', False, [])
    sink = Mock()
    sink.send.return_value = True
    assert service.deliver_due(sink) == 1


def test_telegram_alert_shows_the_flight_party_and_human_readable_time(service, clock, flight_url):
    monitor = service.create_monitor('alice', flight_url, 'telegram-context')
    service.record(Reading(monitor['target_id'], 30900, 'USD', clock[0], 'fixture',
                           fare_name='Economy', price_basis='total'), 'one')
    service.process_events()
    messages = []
    def route(request):
        messages.append(json.loads(request.content)['text'])
        return httpx.Response(200, json={'ok': True})
    sink = TelegramSink('123:' + 'a' * 25, {'alice': '111'}, httpx.MockTransport(route))
    assert service.deliver_due(sink) == 1
    assert 'DEN → DFW · 2027-03-14 · UA414' in messages[0]
    assert 'Total for 1 adult' in messages[0]
    assert '2026-11-02' in messages[0] and 'UTC' in messages[0]


@pytest.mark.parametrize('shadow', [False, True])
@pytest.mark.parametrize('stale_entries', [False, True])
def test_worker_processes_new_observation_and_alert_despite_index_lag(service, clock, flight_url, monkeypatch, shadow, stale_entries):
    from gfpt_next.store import Page
    monitor = service.create_monitor('alice', flight_url, 'index-lag-regression')
    original_page = service.store.page
    stale = {}
    if stale_entries:
        for partition in ('events_pending', 'deliveries_pending'):
            item = Document('completed:' + partition, partition, {})
            service.store.commit([item])
            stale[partition] = service.store.get(item.key)
            service.store.commit([stale[partition].update({}, partition='done')])
    def lagging_page(partition, *args, **kwargs):
        if partition in ('events_pending', 'deliveries_pending'):
            return Page([stale[partition]] if stale_entries else [], None)  # Missing new rows and stale old rows.
        return original_page(partition, *args, **kwargs)
    monkeypatch.setattr(service.store, 'page', lagging_page)
    provider = Mock()
    provider.collect.return_value = Reading(monitor['target_id'], 30900, 'USD', clock[0], 'fixture')
    sink = Mock()
    sink.send.return_value = True
    worker = Worker(service, provider, None if shadow else sink)
    result = worker.tick()
    assert result['collected'] == result['events_processed'] == 1
    assert result['alerts_sent'] == (0 if shadow else 1)
    assert result['alerts_suppressed'] == (1 if shadow else 0)
    assert service.list_deliveries('alice')[0]['status'] == ('suppressed' if shadow else 'sent')
    monkeypatch.setattr(service.store, 'page', original_page)
    # Once the index catches up, the same durable records cannot send twice.
    assert worker.tick()['alerts_sent'] == 0
    assert sink.send.call_count == (0 if shadow else 1)


def test_pending_events_never_expire_before_processing(service, clock, flight_url):
    monitor = service.create_monitor('alice', flight_url, 'pending-retention')
    service.record(Reading(monitor['target_id'], 30900, 'USD', clock[0], 'fixture'), 'one')
    event = service.store.page('events_pending').items[0]
    assert event.expires_at is None
    service.process_events()
    assert service.store.get(event.key).expires_at == clock[0] + 7 * 86400
