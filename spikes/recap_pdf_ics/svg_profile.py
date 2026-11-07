"""Profil altimetrique du parcours en SVG inline (aucune dependance)."""

from html import escape

from models import CourseProfile

W, H = 720, 210
PAD_L, PAD_R, PAD_T, PAD_B = 40, 12, 26, 28


def elevation_gain(profile: CourseProfile) -> int:
    pts = profile.points
    return round(sum(max(0.0, b.alt_m - a.alt_m) for a, b in zip(pts, pts[1:])))


def render_profile_svg(profile: CourseProfile) -> str:
    pts = profile.points
    km_max = pts[-1].km
    alt_max = max(p.alt_m for p in pts)
    alt_top = max(20, (int(alt_max / 20) + 1) * 20)
    pw, ph = W - PAD_L - PAD_R, H - PAD_T - PAD_B

    def x(km: float) -> float:
        return PAD_L + km / km_max * pw

    def y(alt: float) -> float:
        return PAD_T + ph - alt / alt_top * ph

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" class="profile">']
    for a in range(0, alt_top + 1, 20):
        out.append(f'<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{y(a):.1f}" y2="{y(a):.1f}" stroke="#e5e7eb"/>')
        out.append(f'<text x="{PAD_L - 6}" y="{y(a) + 3:.1f}" text-anchor="end" class="ax" font-size="8" fill="#6b7280">{a} m</text>')
    step = 3 if km_max > 12 else 1
    k = 0
    while k <= km_max + 0.01:
        out.append(f'<text x="{x(k):.1f}" y="{H - 8}" text-anchor="middle" class="ax" font-size="8" fill="#6b7280">{k:g} km</text>')
        k += step
    for k0, k1, label in profile.climbs:
        out.append(f'<rect x="{x(k0):.1f}" y="{PAD_T}" width="{x(k1) - x(k0):.1f}" height="{ph}" fill="#fed7aa" opacity=".55"/>')
        out.append(f'<text x="{x(k0) - 4:.1f}" y="{PAD_T + 12}" text-anchor="end" class="climb" font-size="9" fill="#c2410c" font-weight="700">{escape(label)}</text>')
    line = " ".join(f"{x(p.km):.1f},{y(p.alt_m):.1f}" for p in pts)
    area = f"{x(0):.1f},{y(0):.1f} {line} {x(km_max):.1f},{y(0):.1f}"
    out.append(f'<polygon points="{area}" fill="#c7d2fe" opacity=".7"/>')
    out.append(f'<polyline points="{line}" fill="none" stroke="#4338ca" stroke-width="2"/>')
    for km in profile.aid_stations_km:
        out.append(f'<line x1="{x(km):.1f}" x2="{x(km):.1f}" y1="{PAD_T}" y2="{y(0):.1f}" stroke="#0ea5e9" stroke-dasharray="3 3"/>')
        out.append(f'<circle cx="{x(km):.1f}" cy="{PAD_T - 6}" r="7" fill="#0ea5e9"/>')
        out.append(f'<text x="{x(km):.1f}" y="{PAD_T - 3}" text-anchor="middle" class="aid" font-size="8" fill="#fff" font-weight="700">R</text>')
    for km, label in profile.annotations:
        alt = min(pts, key=lambda p: abs(p.km - km)).alt_m
        out.append(f'<line x1="{x(km):.1f}" x2="{x(km):.1f}" y1="{y(alt) - 4:.1f}" y2="{y(alt) - 22:.1f}" stroke="#7c3aed"/>')
        out.append(f'<text x="{x(km):.1f}" y="{y(alt) - 26:.1f}" text-anchor="middle" class="annot" font-size="8" fill="#7c3aed">{escape(label)}</text>')
    out.append("</svg>")
    return "".join(out)
