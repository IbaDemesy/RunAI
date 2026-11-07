"""Contrats statiques ciblés, pas un analyseur DOM/JavaScript ni un audit navigateur."""

import re
from html.parser import HTMLParser


class Tags(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def html_basics(source, feedback=True):
    tags = Tags(source).tags
    errors = []
    if not any(t == "html" and a.get("lang") == "fr" for t, a in tags):
        errors.append("lang=fr absent")
    if not any(t == "meta" and a.get("name") == "viewport" and "width=device-width" in a.get("content", "") for t, a in tags):
        errors.append("viewport absent")
    if feedback and not any(a.get("id") == "feedback" and a.get("role") == "status" and a.get("aria-live") == "polite" for _, a in tags):
        errors.append("feedback non annoncé")
    return errors


def labelled_fields(source):
    fields = re.findall(r'const (\w+) = el\("(?:input|textarea)"\)', source)
    return [f"{name} sans label" for name in fields if f"fieldLabel.append({name})" not in source]


def css_accessibility(source):
    errors = []
    if not any(float(n) >= 2 for n in re.findall(r':focus-visible\s*\{[^}]*outline:\s*([\d.]+)px', source)):
        errors.append("outline focus < 2px")
    motion = re.search(r'@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{(.*?)(?:\n\}|$)', source, re.DOTALL)
    if not motion or not all(re.search(prop + r':\s*none\s*!important', motion[1]) for prop in ("animation", "transition")):
        errors.append("mouvement réduit non neutralisé")
    if not re.search(r'button\s*\{[^}]*min-height:\s*44px', source):
        errors.append("boutons < 44px")
    return errors


def external_links(source):
    return [] if re.search(r'(?:\.target\s*=|setAttribute\("target",)\s*"_blank"', source) and "noopener" in source else ["noopener absent"]


def reduced_motion_option(source):
    return [] if re.search(r'createJourneyView\(container,\s*\{ reducedMotion: matchMedia\("\(prefers-reduced-motion: reduce\)"\).matches', source) else ["option reducedMotion absente"]


def contrast_ratio(first, second):
    def luminance(value):
        value = value.lstrip("#")
        if len(value) == 3:
            value = "".join(c * 2 for c in value)
        channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
        return sum(c * weight for c, weight in zip(linear, (.2126, .7152, .0722)))
    a, b = sorted((luminance(first), luminance(second)))
    return (b + .05) / (a + .05)


def contrasts(source):
    root = re.search(r':root\s*\{([^}]+)', source)
    tokens = dict(re.findall(r'--([\w-]+):\s*([^;]+);', root[1] if root else ""))

    def resolve(name):
        value = tokens.get(name, name).strip()
        for _ in range(len(tokens)):
            ref = re.fullmatch(r'var\(--([\w-]+)\)', value)
            if not ref:
                break
            value = tokens.get(ref[1], "")
        return value if re.fullmatch(r'#[\da-fA-F]{3}(?:[\da-fA-F]{3})?', value) else None

    pairs = [(fg, bg, 4.5) for fg in ("ink", "ink-2", "ink-3") for bg in ("paper", "paper-2", "card")]
    pairs += [("#fff", "ink", 4.5), ("button-text", "ink", 4.5), ("ok", "#e3f1e8", 4.5), ("bad", "#fbe6e8", 4.5), ("ink", "accent", 4.5), ("ink", "gold-soft", 4.5), ("ink", "paper", 3)]
    errors = []
    for fg, bg, minimum in pairs:
        a, b = resolve(fg), resolve(bg)
        if not a or not b:
            errors.append(f"token absent/invalide : {fg}/{bg}")
        elif (ratio := contrast_ratio(a, b)) < minimum:
            errors.append(f"{fg}/{bg}: {ratio:.3f} < {minimum}")
    return errors


def defect(source, identifier):
    patterns = {
        "UX-01": [r'pendingFocus', r'input, textarea, button', r'heading\.tabIndex = -1', r'heading\.focus\(\)'],
        "UX-02": [r'if \(page === id\).*setAttribute\("aria-current", "page"\)'],
        "UX-03": [r'Choisir cette course.*candidate\.name', r'Votre réponse.*question\.text', r'Envoyer.*title'],
        "UX-04": [r'previousStatus = mission.status', r'previousStatus !== mission.status.*announce\('],
        "UX-05": [r'container.setAttribute\("role", "region"\)'],
        "UX-06": [r'screen.append\(el\("h1", "Mon séjour"\)\)', r'priority.append\(el\("h2"', r'block.append\(el\("h2", question.text\)'],
        "UX-07": [r'node.setAttribute\("aria-label",.*nouvel onglet'],
        "UX-08": [r'if \(!matchMedia\("\(prefers-reduced-motion: reduce\)"\).matches\).*button\("Lecture"'],
        "UX-09": [r'name="viewport"', r'id="status" role="status" aria-live="polite"'],
    }
    return [f"{identifier}: contrat absent {pattern}" for pattern in patterns[identifier] if not re.search(pattern, source)]


def c3_accessibility(source):
    patterns = [r'live.setAttribute\("role", "status"\)', r'live.setAttribute\("aria-live", "polite"\)', r'setAttribute\("aria-current", "step"\)', r'playButton.disabled = .*reduced\(\)', r'if \(focusChapter.*\.focus\(\)', r'if \(focusAction\)', r'replacement.focus\(\)']
    patterns += [re.escape(f'"{key}"') for key in ("ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End")]
    return [f"C3: contrat absent {p}" for p in patterns if not re.search(p, source)]
