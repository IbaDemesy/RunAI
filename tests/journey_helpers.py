"""Reusable API drivers for product acceptance journeys."""

import time


def drive_framing(client, session, answers):
    """Answer open questions by slot name, selecting the first sourced candidate.

    Values in ``answers`` are API slot values (including None for no budget cap).
    Missing answers stop the driver rather than inventing user preferences.
    """
    for _ in range(20):
        if session["status"] == "ready_to_confirm":
            return session
        body = {"revision": session["revision"]}
        for question in session["open_questions"]:
            candidates = [c for c in question["choices"] if c.get("candidate_id")]
            if candidates:
                body.update(question_id=question["id"], choice_id=candidates[0]["id"])
                break
            values = {s: answers[s] for s in question["slots"] if s in answers}
            if values:
                body.update(question_id=question["id"], corrections=values)
                break
        else:
            return session
        response = client.post(f"/api/framings/{session['id']}/replies", json=body)
        assert response.status_code == 200, response.text
        session = response.json()
    raise AssertionError("Framing did not converge after 20 replies")


def poll_mission(client, mission_id, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/missions/{mission_id}")
        assert response.status_code == 200, response.text
        snapshot = response.json()
        if predicate(snapshot):
            return snapshot
        time.sleep(.005)
    raise AssertionError(f"Mission did not reach expected state: {snapshot}")
