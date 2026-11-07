"""Mesure de bout en bout : audio injecté en temps réel -> Gladia live -> intentions -> session H.

Usage : python spikes/voix/bench.py [--h] [--audio audio/scenario.wav] [--out results/run.json]
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from dotenv import load_dotenv  # noqa: E402
from gladia_live import GladiaLive, live_config  # noqa: E402
from intents import normalize  # noqa: E402
from pipeline import VoiceRemote, inject_realtime, read_pcm16  # noqa: E402

KEYWORDS = [("stop", "pause"), ("reprends", "resume"), ("non", "pause"), ("plutot", None),
            ("semi", None), ("valide", "validate")]


def keyword_latencies(vr: VoiceRemote) -> list[dict]:
    """Pour chaque mot-clé : 1er transcript qui le contient, latence fin du mot -> réception."""
    out = []
    for kw, _ in KEYWORDS:
        for tr in vr.transcripts:
            hit = next((w for w in tr["words"] if kw in normalize(w["w"] or "").split()), None)
            if hit is None and kw == "plutot":
                hit = next((w for w in tr["words"] if "plut" in normalize(w["w"] or "")), None)
            if hit is None and kw == "semi":
                hit = next((w for w in tr["words"] if "semi" in normalize(w["w"] or "")), None)
            if hit:
                out.append({"keyword": kw, "first_seen_in": "final" if tr["final"] else "partial",
                            "text": tr["text"], "word_end_audio_s": hit["e"],
                            "latency_word_end_to_msg_ms": round((tr["recv"] - (vr.t0 + hit["e"])) * 1000)})
                break
    return out


def final_latencies(vr: VoiceRemote) -> list[dict]:
    return [{"text": t["text"], "utt_end_audio_s": t["end"],
             "latency_utt_end_to_final_ms": round((t["recv"] - (vr.t0 + t["end"])) * 1000)}
            for t in vr.transcripts if t["final"]]


def partial_latencies(vr: VoiceRemote) -> dict:
    """Latence de chaque partiel : fin du dernier mot transcrit -> réception du message."""
    lat = [(t["recv"] - (vr.t0 + t["words"][-1]["e"])) * 1000 for t in vr.transcripts
           if not t["final"] and t["words"]]
    if not lat:
        return {"n": 0}
    lat.sort()
    return {"n": len(lat), "min_ms": round(lat[0]), "median_ms": round(statistics.median(lat)),
            "p90_ms": round(lat[int(0.9 * (len(lat) - 1))]), "max_ms": round(lat[-1])}


def intent_report(vr: VoiceRemote, phrases: list[dict]) -> list[dict]:
    rep = []
    for it in vr.intents:
        tr = next((t for t in vr.transcripts if t["recv"] == it["recv"]), None)
        last_word_end = tr["words"][-1]["e"] if tr and tr["words"] else None
        phrase = next((p for p in phrases if last_word_end and p["start"] - 0.5 <= last_word_end <= p["end"] + 1.5),
                      None)
        rep.append({"intent": it["intent"], "from_final": it["from_final"], "text": it["text"],
                    "msg_to_intent_ms": it["detect_after_msg_ms"],
                    "phrase_end_audio_s": phrase and phrase["end"],
                    "intent_before_phrase_end": bool(phrase and it["detect"] < vr.t0 + phrase["end"]),
                    "phrase_start_to_intent_ms": phrase and round((it["detect"] - (vr.t0 + phrase["start"])) * 1000),
                    "last_word_end_to_intent_ms": last_word_end and round((it["detect"] - (vr.t0 + last_word_end)) * 1000)})
    return rep


def action_report(vr: VoiceRemote, h) -> list[dict]:
    rep = []
    for a in vr.actions:
        r = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in a.items() if k not in ("start", "sent_at")}
        if h is not None and a.get("sent_at"):
            um = h.find_event_after(a["sent_at"] - 1, needle="dictee vocale")
            pol = h.find_event_after(um["recv"] if um else a["sent_at"], needle="semi", kinds={"policy_event"})
            r["user_message_event_seen_after_s"] = um and round(um["recv"] - a["sent_at"], 2)
            r["first_policy_event_mentioning_semi_after_s"] = pol and round(pol["recv"] - a["sent_at"], 2)
            r["first_policy_event_snippet"] = pol and pol["blob"][:600]
        rep.append(r)
    return rep


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--h", action="store_true", help="piloter une vraie session H (1 slot)")
    ap.add_argument("--audio", default=str(HERE / "audio" / "scenario_gtts.wav"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--observe-after-s", type=int, default=120)
    args = ap.parse_args()
    load_dotenv()
    meta = json.loads(Path(args.audio).with_suffix(".json").read_text())
    pcm = read_pcm16(args.audio)
    result: dict = {"audio": meta, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    h = None
    if args.h:
        from h_control import HControl
        h = HControl()
    try:
        if h:
            result["h_quota_before"] = await h.wait_quota()
            t = time.monotonic()
            result["h_session_id"] = await h.create()
            st, _dt, _ = await h.wait_status({"running"}, timeout_s=180, every_s=1)
            result["h_create_to_running_s"] = round(time.monotonic() - t, 1)
            for _ in range(90):
                st, steps = await h.status()
                if st != "running" or (steps or 0) >= 3:
                    break
                await asyncio.sleep(1)
            result["h_status_before_voice"] = {"status": st, "steps": steps}
            if st != "running":
                raise RuntimeError(f"session H pas en running avant la voix : {st}")
        vr = VoiceRemote(h=h)
        gl = GladiaLive(vr.on_gladia, live_config())
        await gl.start()
        result["gladia_session_id"] = gl.session_id
        result["gladia_init_plus_ws_connect_s"] = round(gl.init_latency_s, 3)

        def on_start(t0: float) -> None:
            vr.t0 = t0

        await inject_realtime(pcm, gl.send_audio, on_start)
        await gl.stop()
        await vr.drain()
        if h:
            # Laisser l'agent avancer pour voir s'il prend la correction en compte.
            end = time.monotonic() + args.observe_after_s
            while time.monotonic() < end:
                sent = [a for a in vr.actions if a.get("sent_at")]
                if sent and h.find_event_after(sent[0]["sent_at"], needle="semi", kinds={"policy_event"}):
                    break
                await asyncio.sleep(2)
            result["h_status_end"] = (await h.status())
        result["transcripts"] = [{k: v for k, v in t.items() if k not in ("recv", "words")} |
                                 {"t_rel_s": round(t["recv"] - vr.t0, 3)} for t in vr.transcripts]
        result["speech_start_latency_ms"] = [
            round((e["recv"] - (vr.t0 + e["time"])) * 1000) for e in vr.speech_events
            if e["type"] == "speech_start" and e["time"] is not None]
        result["partials"] = partial_latencies(vr)
        result["keywords"] = keyword_latencies(vr)
        result["finals"] = final_latencies(vr)
        result["intents"] = intent_report(vr, meta["phrases"])
        result["actions"] = action_report(vr, h)
        if h:
            result["h_events_timeline"] = [
                {"t_rel_s": round(e["recv"] - vr.t0, 2), "type": e["type"], "kind": e["kind"],
                 "snippet": e["blob"][:240]} for e in h.events if e["recv"] >= vr.t0 - 5]
    finally:
        if h:
            await h.cancel()
            await asyncio.sleep(2)
            result["h_quota_after_cancel"] = await h.wait_quota(max_wait_s=0)
    out = Path(args.out or HERE / "results" / f"run_{'h' if args.h else 'dry'}_{int(time.time())}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    summary = {k: result.get(k) for k in ("h_session_id", "gladia_session_id", "gladia_init_plus_ws_connect_s",
                                          "speech_start_latency_ms", "partials", "keywords", "intents", "actions")}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("->", out)


if __name__ == "__main__":
    asyncio.run(main())
