import asyncio

from runai_orch.contracts import MissionState, TripRequest

TRIP = {"race_name": "10 km du Maine Libre", "race_date": "2027-03-07", "city": "Le Mans", "distance_km": 10}


def trip(**kw) -> TripRequest:
    return TripRequest(**{**TRIP, **kw})


async def wait_state(m, *states: MissionState, timeout: float = 5.0):
    async def _w():
        while m.state not in states:
            await asyncio.sleep(0.005)
    await asyncio.wait_for(_w(), timeout)
    return m
