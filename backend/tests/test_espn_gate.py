"""Pacing and back-off of requests to ESPN (data_pipeline/espn.py)."""

import httpx
import pytest

from data_pipeline.espn import ESPNClient, ESPNError, ESPNRateLimited, RequestGate


class FakeTime:
    """A clock that only moves when something sleeps or the test advances it."""

    def __init__(self):
        self.now = 1000.0
        self.slept: list[float] = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(round(seconds, 3))
        self.now += seconds


@pytest.fixture
def time():
    return FakeTime()


def _gate(time, interval=0.25):
    return RequestGate(interval, clock=time.clock, sleep=time.sleep)


def test_requests_are_spaced_by_the_minimum_interval(time):
    gate = _gate(time)

    for _ in range(4):
        gate.wait_turn()

    assert time.slept == [0.25, 0.25, 0.25]  # the first goes straight away


def test_a_request_after_a_quiet_spell_does_not_wait(time):
    gate = _gate(time)
    gate.wait_turn()
    time.now += 10

    gate.wait_turn()

    assert time.slept == []


def test_after_a_back_off_requests_fail_fast_instead_of_sleeping(time):
    gate = _gate(time)
    gate.back_off(30)

    with pytest.raises(ESPNRateLimited):
        gate.wait_turn()
    assert time.slept == []

    time.now += 31
    gate.wait_turn()  # the pause is over


def test_repeated_back_offs_pause_longer_up_to_a_cap_and_success_resets_them(time):
    gate = _gate(time)

    assert [gate.back_off() for _ in range(6)] == [60, 120, 240, 480, 900, 900]

    gate.succeeded()
    assert gate.back_off() == 60


def test_a_retry_after_from_espn_is_respected_but_capped(time):
    gate = _gate(time)

    assert gate.back_off(45) == 45
    assert gate.back_off(99999) == 900


def _client(handler, time):
    transport = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://site.api.espn.com"
    )
    return ESPNClient(client=transport, gate=_gate(time))


def test_a_429_stops_all_further_requests_until_the_pause_is_over(time):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(429, headers={"Retry-After": "120"})

    client = _client(handler, time)

    with pytest.raises(ESPNRateLimited, match="holding off 120s"):
        client.scoreboard("football", "nfl")
    with pytest.raises(ESPNRateLimited):
        client.scoreboard("football", "nfl")

    assert len(calls) == 1  # the second never left the building


def test_a_503_also_counts_as_being_told_to_slow_down(time):
    client = _client(lambda request: httpx.Response(503), time)

    with pytest.raises(ESPNRateLimited):
        client.injuries("football", "nfl")


def test_other_errors_do_not_pause_anything(time):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(404)

    client = _client(handler, time)

    for _ in range(2):
        with pytest.raises(ESPNError) as error:
            client.injuries("football", "nfl")
        assert not isinstance(error.value, ESPNRateLimited)
    assert len(calls) == 2


def test_a_successful_request_after_the_pause_works_normally(time):
    answers = iter([httpx.Response(429), httpx.Response(200, json={"events": []})])
    client = _client(lambda request: next(answers), time)

    with pytest.raises(ESPNRateLimited):
        client.scoreboard("football", "nfl")
    time.now += 61

    assert client.scoreboard("football", "nfl") == {"events": []}


def test_the_summary_falls_back_to_the_cdn_on_an_ordinary_failure_but_not_when_rate_limited(time):
    def cdn_client(handler):
        return httpx.Client(
            transport=httpx.MockTransport(handler), base_url="https://cdn.espn.com"
        )

    def build(site_status):
        cdn_calls = []

        def cdn(request):
            cdn_calls.append(1)
            return httpx.Response(200, json={"gamepackageJSON": {"header": {}}})

        client = _client(lambda request: httpx.Response(site_status), time)
        client._cdn_client = cdn_client(cdn)
        return client, cdn_calls

    client, cdn_calls = build(403)
    assert client.summary("football", "nfl", "1") == {"header": {}}
    assert cdn_calls == [1]

    client, cdn_calls = build(429)
    with pytest.raises(ESPNRateLimited):
        client.summary("football", "nfl", "1")
    assert cdn_calls == []
