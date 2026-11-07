import asyncio
from types import SimpleNamespace

import pytest

from runai.app.tasks import TripBrief
from runai.models import Race
from runai.search.logistics_sweep import sweep_logistics

RACE = Race(name="Marathon", city="Paris", country="France", start_location="Champs-Elysees")
BRIEF = TripBrief(race_label="Marathon", city="Paris", country="France", origin="Lyon")
HOTEL = {"name": "Hotel", "official_url": "https://hotel.example", "distance_km": 1,
         "source_url": "https://hotel.example/location"}
OPERATOR = {"name": "SNCF", "official_url": "https://sncf.com", "mode": "train"}


class Client:
    def __init__(self, hotels=None, operators=None):
        self.outputs = [{"race_form_url": "https://njuko.net/marathon/select_competition",
                         "hotels": hotels if hotels is not None else [HOTEL]},
                        {"transport_operators": operators if operators is not None else [OPERATOR]}]
        self.search_calls = 0

    def create_tasks(self, tasks):
        assert len(tasks) == 2
        assert "hotels near Champs-Elysees" in tasks[0].query
        return [SimpleNamespace(id=str(i), status="pending") for i in range(2)]

    def get_task(self, task_id):
        return SimpleNamespace(status="completed", output=self.outputs[int(task_id)])

    def search(self, **kwargs):
        index = self.search_calls
        self.search_calls += 1
        return self.outputs[index]


def run(client, timeout_s=15):
    return asyncio.run(sweep_logistics(RACE, BRIEF, client, timeout_s))


def test_success():
    result = run(Client())
    assert len(result.hotels) == len(result.transport_operators) == 1
    assert result.race_form_url.host == "njuko.net"
    assert result.calls == 2 and result.estimated_cost_usd == .03
    assert result.latency_s >= 1
    assert len(result.source_urls) == 4


def test_filtering():
    bad_hotels = [HOTEL | {"official_url": f"https://{host}/hotel"}
                  for host in ("booking.com", "sub.expedia.com", "ahotu.com")]
    bad_hotels += [HOTEL | {"source_url": "https://hotels.com/example"}]
    result = run(Client(hotels=bad_hotels + [HOTEL] * 6,
                        operators=[OPERATOR | {"official_url": "https://flytap.com"}]))
    assert len(result.hotels) == 5
    assert not result.transport_operators
    assert all("booking" not in str(url) for url in result.source_urls)


def test_not_provided():
    client = Client(hotels=[HOTEL | {"distance_km": "Not provided in sources",
                                    "source_url": "Not provided"},
                            HOTEL | {"official_url": "Not provided"}],
                    operators=[OPERATOR | {"mode": "Not provided"}])
    client.outputs[0]["race_form_url"] = "Not provided by source"
    result = run(client)
    assert result.race_form_url is None
    assert len(result.hotels) == 1 and result.hotels[0].distance_km is None
    assert not result.transport_operators


def test_timeout_returns_empty():
    result = run(Client(), timeout_s=.01)
    assert not result.hotels and not result.transport_operators and result.race_form_url is None
    assert result.latency_s > 0


def test_tasks_error_falls_back():
    class BrokenTasks(Client):
        def create_tasks(self, tasks):
            raise RuntimeError("Tasks unavailable")

    client = BrokenTasks()
    result = run(client)
    assert client.search_calls == 2 and result.calls == 4
    assert len(result.hotels) == 1


def test_empty_results():
    assert not run(Client(hotels=[], operators=[])).hotels


def test_search_error_propagates():
    class Broken(Client):
        def create_tasks(self, tasks):
            raise RuntimeError("unavailable")

        def search(self, **kwargs):
            raise RuntimeError("unavailable")

    with pytest.raises(RuntimeError, match="unavailable"):
        run(Broken())
