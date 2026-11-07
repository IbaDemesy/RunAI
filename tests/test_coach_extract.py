import json

from runai.coach import (
    QUESTIONS,
    CoachProfile,
    Goal,
    extract_profile,
    extract_rule_based,
    llm_prompt,
    parse_llm_json,
    plausibility_issues,
)

CAMILLE = (
    "Je cours trois fois par semaine, à peu près vingt-cinq kilomètres. "
    "Ma plus longue sortie c'est 14 km en 1h20. "
    "J'ai fait le 10 km de Paris en 52 minutes il y a 4 mois. "
    "Je cours depuis 2 ans et j'ai 31 ans. "
    "J'aimerais battre mon chrono et courir à l'étranger."
)


def test_at_most_five_questions():
    assert len(QUESTIONS) == 5 and all(q.endswith(("?", ".")) for q in QUESTIONS)


def test_rule_based_extraction_full_answer():
    p = extract_rule_based(CAMILLE)
    assert p.sessions_per_week == 3 and p.weekly_km == 25
    assert p.longest_recent_run.distance_km == 14 and p.longest_recent_run.duration_min == 80
    assert p.recent_race.distance_km == 10 and p.recent_race.time_s == 52 * 60 and p.recent_race.months_ago == 4
    assert p.age == 31 and p.running_since_months == 24
    assert set(p.goals) == {Goal.chrono, Goal.voyage}


def test_rule_based_extraction_does_not_invent():
    p = extract_rule_based("Je cours deux fois par semaine, je ne sais pas du tout mon niveau, je voudrais faire mon premier 10 km.")
    assert p.sessions_per_week == 2
    assert p.recent_race is None and p.longest_recent_run is None and p.age is None
    assert p.goals == [Goal.premier_10k]


def test_rule_based_semi_word_and_cooper():
    p = extract_rule_based("J'ai couru le semi en 1h45 l'an dernier. Au test de Cooper j'ai fait 2600 mètres.")
    assert p.recent_race.distance_km == 21.0975 and p.recent_race.time_s == 6300 and p.recent_race.months_ago == 12
    assert p.cooper_m == 2600


def test_llm_prompt_contains_schema_and_parser_accepts_fenced_json():
    prompt = llm_prompt()
    assert "recent_race" in prompt and "null" in prompt
    answer = "```json\n" + json.dumps({"sessions_per_week": 3, "recent_race": {"distance_km": 10, "time_s": 3120, "months_ago": 4}, "goals": ["chrono"]}) + "\n```"
    p = parse_llm_json(answer)
    assert isinstance(p, CoachProfile) and p.recent_race.time_s == 3120


def test_plausibility_flags_measured_gladia_llm_error():
    # Mesure du 07/11 : Gladia a transcrit "14 10 km 1h20", audio_to_llm en a tiré 100 km en 80 min.
    llm_json = '{"sessions_per_week": 3, "weekly_km": 25, "longest_recent_run": {"distance_km": 100, "duration_min": 80}}'
    issues = plausibility_issues(parse_llm_json(llm_json))
    assert len(issues) == 2 and all(i.field == "longest_recent_run" for i in issues)
    assert plausibility_issues(extract_rule_based(CAMILLE)) == []


def test_ambiguous_measured_transcript_leaves_field_empty():
    transcript = "Je cours trois fois par semaine, à peu près 25 km. Ma plus longue sortie, c'est 14 10 km 1h20."
    p = extract_rule_based(transcript)
    assert p.longest_recent_run is None and "longest_recent_run" in p.missing_fields


def test_extract_profile_clears_implausible_fields_and_asks_again():
    llm_json = '{"sessions_per_week": 3, "weekly_km": 25, "longest_recent_run": {"distance_km": 100, "duration_min": 80}, "age": 31}'
    x = extract_profile("transcription", llm_json=llm_json)
    assert x.method == "llm"
    assert x.profile.longest_recent_run is None and x.profile.weekly_km == 25 and x.profile.age == 31
    assert x.cleared_fields == ["longest_recent_run"]
    assert x.follow_up_questions == [QUESTIONS[1]]


def test_extract_profile_falls_back_to_rules_on_bad_llm_output():
    x = extract_profile(CAMILLE, llm_json="désolé, je ne peux pas")
    assert x.method == "regles" and x.llm_error
    assert x.profile.recent_race.time_s == 52 * 60
    assert x.issues == [] and x.follow_up_questions == []


def test_number_words_and_ranges():
    p = extract_rule_based("Je cours trois fois par semaine, entre vingt et trente kilomètres par semaine. J'ai vingt et un ans.")
    assert p.weekly_km == 25 and p.age == 21
    assert extract_rule_based("Entre vingt et un et trente km par semaine.").weekly_km == 25.5
    assert extract_rule_based("Je fais deux et trois km par semaine").weekly_km == 3
