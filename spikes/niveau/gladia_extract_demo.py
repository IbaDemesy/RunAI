"""Mesure : voix (synthese espeak-ng, profil fictif) -> Gladia pre-enregistre -> profil JSON.

Deux extractions comparees sur la meme transcription :
- audio_to_llm de Gladia (Alpha) avec le prompt + schema de RunnerProfile ;
- parseur a regles local (secours, sans LLM).
Usage : GLADIA_API_KEY=... python gladia_extract_demo.py [fichier.wav]

HTTP brut (httpx) : gladiaio-sdk 2.2.1 plante au decodage de la reponse quand
audio_to_llm est active (KeyError: 'success' dans dataclasses_json, mesure le 07/11).
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from runner_level import assess
from voice_extract import (
    CUSTOM_VOCABULARY,
    extract_rule_based,
    llm_prompt,
    parse_llm_json,
    plausibility_issues,
)

HERE = Path(__file__).parent
API = "https://api.gladia.io/v2"
ANSWERS = (
    "Je cours trois fois par semaine, à peu près vingt-cinq kilomètres. "
    "Ma plus longue sortie, c'est quatorze kilomètres en une heure vingt. "
    "J'ai fait le dix kilomètres de Paris en cinquante-deux minutes il y a quatre mois. "
    "Je cours depuis deux ans et j'ai trente et un ans. "
    "J'aimerais battre mon chrono et courir à l'étranger."
)


def synthesize(path: Path, words_per_min: int = 150) -> None:
    subprocess.run(["espeak-ng", "-v", "fr", "-s", str(words_per_min), "-w", str(path), ANSWERS], check=True)


def main() -> None:
    load_dotenv()
    audio = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "results" / "camille_answers.wav"
    audio.parent.mkdir(exist_ok=True)
    if not audio.exists():
        synthesize(audio)

    options = {
        "language_config": {"languages": ["fr"]},
        "custom_vocabulary": True,
        "custom_vocabulary_config": {"vocabulary": CUSTOM_VOCABULARY},
        "audio_to_llm": True,
        "audio_to_llm_config": {"prompts": [llm_prompt()]},
    }
    headers = {"x-gladia-key": os.environ["GLADIA_API_KEY"]}
    with httpx.Client(timeout=60, headers=headers) as http:
        start = time.perf_counter()
        with audio.open("rb") as f:
            upload = http.post(f"{API}/upload", files={"audio": (audio.name, f, "audio/wav")})
        upload.raise_for_status()
        job = http.post(f"{API}/pre-recorded", json={"audio_url": upload.json()["audio_url"], **options})
        job.raise_for_status()
        job_id = job.json()["id"]
        while True:
            data = http.get(f"{API}/pre-recorded/{job_id}").json()
            if data["status"] in ("done", "error"):
                break
            time.sleep(0.5)
        elapsed = time.perf_counter() - start

    result = data.get("result") or {}
    transcript = result["transcription"]["full_transcript"]
    rule_profile = extract_rule_based(transcript)
    a2l = result.get("audio_to_llm") or {}
    first = (a2l.get("results") or [{}])[0]
    llm_raw = (first.get("results") or {}).get("response")
    llm_profile, llm_error = None, None
    try:
        llm_profile = parse_llm_json(llm_raw or "")
    except Exception as exc:  # noqa: BLE001
        llm_error = f"{type(exc).__name__}: {exc}"[:300]

    out = {
        "job_id": job_id,
        "status": data["status"],
        "audio_duration_s": result.get("metadata", {}).get("audio_duration"),
        "wall_time_s": round(elapsed, 2),
        "transcription_time_s": result.get("metadata", {}).get("transcription_time"),
        "audio_to_llm_exec_time_s": a2l.get("exec_time"),
        "audio_to_llm_success": a2l.get("success"),
        "audio_to_llm_error": a2l.get("error"),
        "audio_to_llm_item": {k: v for k, v in first.items() if k != "results"},
        "transcript": transcript,
        "llm_raw": llm_raw,
        "llm_profile": llm_profile.model_dump(mode="json") if llm_profile else None,
        "llm_parse_error": llm_error,
        "llm_plausibility_issues": plausibility_issues(llm_profile) if llm_profile else None,
        "rule_profile": rule_profile.model_dump(mode="json"),
        "rule_plausibility_issues": plausibility_issues(rule_profile),
        "assessment_from_rules": assess(rule_profile, weeks_available=14).model_dump(mode="json"),
    }
    target = HERE / "results" / f"gladia_run_{audio.stem}.json"
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: out[k] for k in list(out)[:9]}, ensure_ascii=False, indent=2))
    print("transcript:", transcript)
    print("llm_raw:", llm_raw)
    print("llm_parse_error:", llm_error)
    print("rule_profile:", rule_profile.model_dump_json())
    print("plausibility llm:", out["llm_plausibility_issues"], "rules:", out["rule_plausibility_issues"])


if __name__ == "__main__":
    main()
