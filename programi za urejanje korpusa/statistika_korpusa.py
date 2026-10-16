#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
statistika_korpusa.py - statisticni prikaz govornega korpusa (EXB + WAV)

Skripta rekurzivno pregleda mapo, prebere vse .exb (EXMARaLDA) in .wav datoteke
ter izpise 15 statisticnih postavk v .txt datoteko.

Uporaba:
    python statistika_korpusa.py              (brez argumentov odpre okno)
    python statistika_korpusa.py MAPA_KORPUSA
    python statistika_korpusa.py MAPA_KORPUSA -o rog_statistika.txt
    python statistika_korpusa.py MAPA_KORPUSA --word-tier pog
    python statistika_korpusa.py MAPA_KORPUSA --speaker-key abbreviation

Potrebuje samo standardno knjiznico Pythona (3.8+).

Izdelava .exe (Windows):
    pip install pyinstaller
    pyinstaller --onefile --windowed --name StatistikaKorpusa statistika_korpusa.py
"""

import argparse
import sys
from types import SimpleNamespace
import re
import statistics
import struct
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

# =============================================================================
# NASTAVITVE - tu prilagodis imena polj in pravila stetja
# =============================================================================

# Plast (category, type="t"), iz katere se stejejo besede. Vzame se prva, ki obstaja.
# Lahko jo dolocis tudi rocno z --word-tier.
WORD_TIER_PRIORITY = ["std", "norm", "pog", "trs", "word", "tok", "v"]

# Mozna imena polj v <ud-information attribute-name="..."> (velike/male crke niso pomembne)
# Plast (category), kjer en dogodek = ena poved
SENTENCE_TIER_CATEGORIES = ["sentenceId", "sentence", "sentences", "povedi"]

GENRE_FIELDS = ["GENRE", "DOMAIN", "ZVRST"]
YEAR_FIELDS = ["DATE", "DATUM", "RECORDING_DATE", "DATUM_SNEMANJA",
               "YEAR", "LETO", "LETO_SNEMANJA", "RECORDING_YEAR"]
AGE_FIELDS = ["AGE", "STAROST", "AGE_GROUP", "STAROSTNA_SKUPINA"]
BIRTH_YEAR_FIELDS = ["BIRTH_YEAR", "YEAR_OF_BIRTH", "LETNICA_ROJSTVA", "LETO_ROJSTVA"]
REGION_FIELDS = ["REGION", "REGIJA", "STATISTICAL_REGION", "STATISTICNA_REGIJA",
                 "PERM-RESD", "RESIDENCE", "BIVALISCE"]
# Vrstni red v datumih z / ali . : "DMY" (13/ 7/ 1905 = 13. julij) ali "MDY" (ameriski)
DATE_ORDER = "DMY"

# Ce statisticne regije ni, se izpiseta drzava in kraj stalnega bivalisca (ce obstajata)
COUNTRY_FIELDS = ["PERM-RESD-COUNTRY", "COUNTRY", "DRZAVA"]
SETTLEMENT_FIELDS = ["PERM-RESD-SETTLEMENT", "SETTLEMENT", "KRAJ", "NASELJE"]
SEX_FIELDS = ["SEX", "SPOL", "GENDER"]

# Vrednosti, ki stejejo kot manjkajoce
MISSING_VALUES = {"", "-", "--", "?", "u", "x", "na", "n/a", "neznano", "unknown",
                  "ni podatka", "none", "null", "unkown", "unspecified", "/"}

# Pravila stetja besed
REMOVE_BRACKETED = True   # odstrani [smeh], <nerazumljivo>, {sum}, [0.5], [eee] ... pred stetjem
# Izjeme: oznake v oklepajih, ki so prave besede (npr. anonimizirana imena)
KEEP_BRACKETED = [r"\[name:[^\]]*\]"]
# Dogodki z besedo, daljsi od tega (s), se pri racunanju trajanja ignorirajo
# (npr. beseda, ki se konca na zadnji tocki casovnice = konec posnetka)
MAX_EVENT_SEC = 30
FILLERS = set()           # npr. {"eee", "mhm", "aaa"} - ce jih ne zelis steti kot besede

# =============================================================================

BRACKET_RE = re.compile(r"\[[^\]]*\]|<[^>]*>|\{[^}]*\}")
EDGE_PUNCT_RE = re.compile(r"^[^\w]+|[^\w-]+$")   # koncni "-" (bo-, splet-) ostane
KEEP_RE = re.compile("|".join(KEEP_BRACKETED)) if KEEP_BRACKETED else None
YEAR_RE = re.compile(r"(?<!\d)(1[89]\d\d|20\d\d)(?!\d)")
NO_DATA = "ni podatka"


# ----------------------------- pomozne funkcije -----------------------------

def norm(v):
    return (v or "").strip()


def is_missing(v):
    return v is None or norm(v).lower() in MISSING_VALUES


def get_field(d, names):
    for n in names:
        v = d.get(n.upper())
        if not is_missing(v):
            return norm(v)
    return None


def extract_year(v):
    m = YEAR_RE.search(v or "")
    return int(m.group(1)) if m else None


def norm_sex(v):
    v = norm(v).lower()
    if v in ("m", "moški", "moski", "male", "man", "mož"):
        return "moški"
    if v in ("f", "ž", "z", "ženski", "zenski", "female", "woman", "w"):
        return "ženski"
    return None


def decade(age):
    d = (age // 10) * 10
    return f"{d}–{d + 9}"


def exact_age(age_raw, birth_raw, rec_year):
    """Tocna starost (int) ali None."""
    if birth_raw and rec_year:
        b = extract_year(birth_raw)
        if b and rec_year >= b:
            return rec_year - b
    if age_raw and re.fullmatch(r"\d{1,3}", age_raw):
        return int(age_raw)
    return None


def parse_range(label):
    """'30 do 59 let', '45-57', '18–34' -> (30, 59); 'nad 60 let' -> (60, 200)."""
    m = re.match(r"^\s*(\d{1,3})\s*(?:-|–|do)\s*(\d{1,3})", label)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"^\s*(?:nad|over|\+)\s*(\d{1,3})", label, re.I)
    if m:
        return int(m.group(1)), 200
    return None


def year_from_date(raw):
    """Leto iz datuma. Prepozna Excelovo napako, ko je bilo leto (npr. 2025) vpisano kot
    stevilo in pretvorjeno v datum (17. 7. 1905). Vrne (leto, opis_popravka ali None)."""
    if not raw:
        return None, None
    y = extract_year(raw)
    m = re.search(r"(\d{1,2})\s*[/.]\s*(\d{1,2})\s*[/.]\s*(\d{4})", raw)
    if m and y and 1899 <= y <= 1910:
        a, b, yy = map(int, m.groups())
        orders = ((b, a), (a, b)) if DATE_ORDER == "DMY" else ((a, b), (b, a))   # (mesec, dan)
        for mo, da in orders:
            try:
                serial = (date(yy, mo, da) - date(1899, 12, 30)).days
            except ValueError:
                continue
            if 1900 <= serial <= 2100:
                return serial, f"'{raw}' je verjetno Excelova pretvorba števila {serial}"
    return y, None


def words_in(text):
    out = []
    if KEEP_RE is not None:
        out.extend(KEEP_RE.findall(text))
        text = KEEP_RE.sub(" ", text)
    if REMOVE_BRACKETED:
        text = BRACKET_RE.sub(" ", text)
    for tok in text.split():
        w = EDGE_PUNCT_RE.sub("", tok)
        if not w or not re.search(r"[^\W_]", w):
            continue                       # samo locila / znaki
        if w.lower() in FILLERS:
            continue
        out.append(w)
    return out


def wav_duration(path):
    """Trajanje v sekundah iz glave WAV (RIFF/RF64), brez branja zvoka."""
    try:
        size_on_disk = path.stat().st_size
        with open(path, "rb") as f:
            hdr = f.read(12)
            if len(hdr) < 12 or hdr[:4] not in (b"RIFF", b"RF64") or hdr[8:12] != b"WAVE":
                return None
            byte_rate = data_size = ds64_size = None
            while True:
                ch = f.read(8)
                if len(ch) < 8:
                    break
                cid, size = ch[:4], struct.unpack("<I", ch[4:])[0]
                if cid == b"data":
                    data_size = ds64_size if (size == 0xFFFFFFFF and ds64_size) else size
                    data_size = min(data_size, size_on_disk - f.tell())
                    break
                body = f.read(size)
                if cid == b"fmt " and len(body) >= 12:
                    byte_rate = struct.unpack("<I", body[8:12])[0]
                elif cid == b"ds64" and len(body) >= 16:
                    ds64_size = struct.unpack("<Q", body[8:16])[0]
                if size % 2:
                    f.seek(1, 1)
            if byte_rate and data_size:
                return data_size / byte_rate
    except OSError:
        pass
    return None


def union_len(intervals):
    total, cur_a, cur_b = 0.0, None, None
    for a, b in sorted(intervals):
        if cur_b is None or a > cur_b:
            if cur_b is not None:
                total += cur_b - cur_a
            cur_a, cur_b = a, b
        else:
            cur_b = max(cur_b, b)
    if cur_b is not None:
        total += cur_b - cur_a
    return total


def fmt_int(n):
    return f"{n:,}".replace(",", ".")


def fmt_num(x, dec=1):
    return f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_pct(part, total):
    return (fmt_num(100 * part / total) + " %") if total else "–"


def fmt_dur(sec):
    m = int(round(sec / 60))
    return f"{m // 60} h {m % 60} min"


def table(headers, rows, indent="   "):
    rows = [[str(c) for c in r] for r in rows]
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)]

    def line(r):
        return indent + "  ".join(
            (c.ljust(w) if i == 0 else c.rjust(w)) for i, (c, w) in enumerate(zip(r, widths)))
    return [line(headers), indent + "  ".join("-" * w for w in widths)] + [line(r) for r in rows]


def group_sort_key(g):
    if g == NO_DATA:
        return (2, 0, g)
    m = re.match(r"\d+", g)
    return (0, int(m.group()), g) if m else (1, 0, g.lower())


def find_files(root, ext):
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ext)


def make_speaker_key(sid, sp, mode):
    m = mode.lower()
    if m == "id":
        return sid
    if m == "abbreviation":
        return sp["abbr"] or sid
    if m == "auto":
        return get_field(sp["ud"], ["PRS-ID"]) or sid
    return get_field(sp["ud"], [mode]) or sid


# ------------------------------- branje EXB -------------------------------

def parse_exb(path):
    root = ET.parse(path).getroot()
    meta, ref = {}, None
    mi = root.find("head/meta-information")
    if mi is not None:
        for rf in mi.findall("referenced-file"):
            if rf.get("url"):
                ref = rf.get("url")
                break
        for ud in mi.findall("ud-meta-information/ud-information"):
            meta[norm(ud.get("attribute-name")).upper()] = norm(ud.text)

    speakers = {}
    for sp in root.findall("head/speakertable/speaker"):
        sex_el = sp.find("sex")
        speakers[sp.get("id")] = {
            "abbr": norm(sp.findtext("abbreviation")),
            "sex": sex_el.get("value") if sex_el is not None else "",
            "ud": {norm(u.get("attribute-name")).upper(): norm(u.text)
                   for u in sp.findall("ud-speaker-information/ud-information")},
        }

    tli = {}
    for t in root.iter("tli"):
        try:
            tli[t.get("id")] = float(t.get("time"))
        except (TypeError, ValueError):
            pass
    times = list(tli.values())

    tiers = [{
        "speaker": tier.get("speaker"),
        "category": norm(tier.get("category")),
        "type": norm(tier.get("type")).lower(),
        "events": [ev.text or "" for ev in tier.findall("event")],
        "spans": [(tli.get(ev.get("start")), tli.get(ev.get("end"))) for ev in tier.findall("event")],
    } for tier in root.iter("tier")]

    return {
        "meta": meta, "ref": ref, "speakers": speakers, "tiers": tiers,
        "timeline_dur": (max(times) - min(times)) if len(times) >= 2 else None,
    }


# --------------------------------- glavno ---------------------------------

def generate(mapa, output, word_tier=None, speaker_key="auto", log=print):
    """Izracuna statistiko korpusa v mapi `mapa` in jo zapise v `output`.
    `log` je funkcija za sporocila o napredku. Vrne kratek povzetek (dict)."""
    args = SimpleNamespace(mapa=mapa, output=output, word_tier=word_tier, speaker_key=speaker_key)

    root = Path(args.mapa)
    warnings = []

    log(f"Iščem datoteke v: {root}")
    exb_files = find_files(root, ".exb")
    wav_files = find_files(root, ".wav")
    log(f"Najdenih {len(exb_files)} EXB in {len(wav_files)} WAV datotek.")
    if not exb_files:
        raise ValueError("V izbrani mapi (in podmapah) ni nobene .exb datoteke.")
    wav_by_name = {p.name.lower(): p for p in wav_files}
    wav_by_stem = {p.stem.lower(): p for p in wav_files}

    # --- WAV trajanja ---
    wav_dur = {}
    for p in wav_files:
        d = wav_duration(p)
        if d is None:
            warnings.append(f"WAV ni bilo mogoče prebrati: {p}")
        else:
            wav_dur[p] = d

    # --- branje EXB ---
    docs = []
    log("Berem EXB datoteke ...")
    for i_exb, p in enumerate(exb_files, 1):
        if i_exb % 25 == 0 or i_exb == len(exb_files):
            log(f"   {i_exb}/{len(exb_files)}")
        try:
            d = parse_exb(p)
            d["file"] = p
            docs.append(d)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"EXB ni bilo mogoče prebrati ({e}): {p}")

    # --- izbira plasti za besede ---
    t_cats = Counter(t["category"] for d in docs for t in d["tiers"] if t["type"] == "t")
    t_cats_lower = {c.lower(): c for c in t_cats}
    if args.word_tier:
        word_cat = args.word_tier
        if word_cat.lower() not in t_cats_lower:
            warnings.append(f"Plast '{word_cat}' (type=\"t\") ni najdena v nobeni datoteki.")
    else:
        word_cat = next((t_cats_lower[c] for c in WORD_TIER_PRIORITY if c in t_cats_lower), None)
        if word_cat is None and t_cats:
            word_cat = t_cats.most_common(1)[0][0]
    if word_cat is None:
        warnings.append("Ni nobene plasti type=\"t\" - besed ni mogoče šteti.")

    # --- obdelava ---
    speakers = {}            # kljuc -> podatki o govorcu
    long_events = 0
    date_fixes = []
    has_sentence_tier = False
    SENT_CATS = {c.lower() for c in SENTENCE_TIER_CATEGORIES}
    recs = []
    type_counter = Counter()
    used_wavs = set()
    categories = set()
    conflicts = set()

    for d in docs:
        meta = d["meta"]
        # povezava z WAV
        wav = None
        if d["ref"]:
            wav = wav_by_name.get(re.split(r"[\\/]", d["ref"])[-1].lower())
        if wav is None:
            wav = wav_by_stem.get(d["file"].stem.lower())
        if wav is not None:
            used_wavs.add(wav)
        else:
            warnings.append(f"EXB brez pripadajoče WAV datoteke: {d['file'].name}")

        rec_year, fix = year_from_date(get_field(meta, YEAR_FIELDS))
        if fix:
            date_fixes.append(f"{d['file'].name}: {fix} -> uporabljeno leto {rec_year}")
        genre = get_field(meta, GENRE_FIELDS)
        genre = genre.lower() if genre else None

        # govorci iz tabele
        id2key = {}
        for sid, sp in d["speakers"].items():
            key = make_speaker_key(sid, sp, args.speaker_key)
            id2key[sid] = key
            ud = sp["ud"]
            info = {
                "sex": norm_sex(sp["sex"]) or norm_sex(get_field(ud, SEX_FIELDS) or ""),
                "age_raw": get_field(ud, AGE_FIELDS),
                "birth_raw": get_field(ud, BIRTH_YEAR_FIELDS),
                "region": get_field(ud, REGION_FIELDS),
                "country": get_field(ud, COUNTRY_FIELDS),
                "settlement": get_field(ud, SETTLEMENT_FIELDS),
            }
            s = speakers.setdefault(key, {"sex": None, "age_raw": None, "birth_raw": None,
                                          "region": None, "country": None, "settlement": None,
                                          "rec_year": None, "ud": {},
                                          "words": 0, "files": set()})
            for k, v in info.items():
                if v is None:
                    continue
                if s[k] is None:
                    s[k] = v
                elif s[k] != v:
                    conflicts.add(key)
            if s["rec_year"] is None:
                s["rec_year"] = rec_year
            for k, v in ud.items():
                if is_missing(s["ud"].get(k)):
                    s["ud"][k] = v
            s["files"].add(d["file"].name)

        # plasti
        rec_words = Counter()
        starts, ends, intervals = [], [], []
        rec_sentences = 0
        for t in d["tiers"]:
            categories.add((t["category"], t["type"]))
            if t["category"].lower() in SENT_CATS:
                rec_sentences += sum(1 for ev in t["events"] if ev.strip())
                has_sentence_tier = True
            if word_cat is None or t["type"] != "t" or t["category"].lower() != word_cat.lower():
                continue
            ws = [w for ev in t["events"] for w in words_in(ev)]
            for (a, b), ev in zip(t["spans"], t["events"]):
                if a is None or b is None or not words_in(ev):
                    continue
                if b - a > MAX_EVENT_SEC:
                    long_events += 1
                    continue
                starts.append(a); ends.append(b)
                intervals.append((a, b))
            type_counter.update(w.lower() for w in ws)
            sid = t["speaker"]
            if not sid:
                warnings.append(f"Plast brez govorca v {d['file'].name}")
                key = "(brez govorca)"
            elif sid in id2key:
                key = id2key[sid]
            else:
                warnings.append(f"Govorec '{sid}' ni v tabeli govorcev: {d['file'].name}")
                key = sid
                speakers.setdefault(key, {"sex": None, "age_raw": None, "birth_raw": None,
                                          "region": None, "country": None, "settlement": None,
                                          "rec_year": rec_year, "ud": {},
                                          "words": 0, "files": set()})
            rec_words[key] += len(ws)
            if key in speakers:
                speakers[key]["words"] += len(ws)

        dur = wav_dur.get(wav) if wav else None
        recs.append({
            "file": d["file"], "meta": meta, "genre": genre, "year": rec_year, "wav": wav,
            "dur": dur if dur is not None else (d["timeline_dur"] or 0.0),
            "timeline_dur": d["timeline_dur"] or 0.0,
            "trans_dur": (max(ends) - min(starts)) if starts and ends and max(ends) > min(starts) else 0.0,
            "speech_dur": union_len(intervals),
            "sentences": rec_sentences,
            "words": sum(rec_words.values()),
            "n_speakers": sum(1 for v in rec_words.values() if v > 0),
        })

    if long_events:
        warnings.append(f"Dogodkov z besedo, daljših od {MAX_EVENT_SEC} s (izpuščeni pri trajanju): {long_events}")
    for p in wav_files:
        if p not in used_wavs:
            warnings.append(f"WAV brez pripadajoče EXB datoteke: {p.name}")
    for key in sorted(conflicts):
        warnings.append(f"Govorec '{key}' ima v različnih datotekah različne metapodatke "
                        f"(uporabljena prva vrednost).")

    active = {k: s for k, s in speakers.items() if s["words"] > 0}
    silent = sorted(k for k, s in speakers.items() if s["words"] == 0)
    if speakers and sum(bool(re.fullmatch(r"SPK\d+", k)) for k in speakers) > len(speakers) / 2:
        warnings.append("ID-ji govorcev so videti lokalni (SPK0, SPK1 ...), zato isti govorec v "
                        "več datotekah morda ni prepoznan. Poskusi --speaker-key abbreviation.")

    for s in active.values():
        s["age_exact"] = exact_age(s["age_raw"], s["birth_raw"], s["rec_year"])
        s["age"] = None if s["age_exact"] is not None else (" ".join(s["age_raw"].split()) if s["age_raw"] else None)
    # Skupine iz korpusa, ki jih ima vsaj 2 govorca (posamezni razponi niso skupine)
    grp_count = Counter(s["age"] for s in active.values() if s["age"])
    groups = {g: parse_range(g) for g, c in grp_count.items() if c >= 2 and parse_range(g)}
    for s in active.values():
        a = s["age_exact"]
        if a is None:
            continue
        fit = [g for g, (lo, hi) in groups.items() if lo <= a <= hi]
        s["age"] = fit[0] if len(fit) == 1 else decade(a)

    total_words = sum(type_counter.values())
    n_act = len(active)

    # ================================ IZPIS ================================
    L = []
    L += ["STATISTIKA KORPUSA", "=" * 70,
          f"Mapa:                 {root.resolve()}",
          f"Izdelano:             {datetime.now():%d. %m. %Y %H:%M}",
          f"Plast za besede:      {word_cat} (type=\"t\")",
          f"Ključ govorca:        {args.speaker_key}",
          "Opomba: demografske porazdelitve upoštevajo govorce z vsaj eno besedo.", ""]

    L += ["1. Število posnetkov",
          f"   WAV datotek: {fmt_int(len(wav_files))}",
          f"   EXB datotek: {fmt_int(len(docs))}", ""]

    L += ["2. Skupno trajanje posnetkov",
          f"   Seštevek WAV:            {fmt_dur(sum(wav_dur.values()))}",
          f"   Iz časovnice EXB:        {fmt_dur(sum(r['timeline_dur'] for r in recs))}",
          f"   Prepisani del:           {fmt_dur(sum(r['trans_dur'] for r in recs))}",
          f"   Govorni čas:             {fmt_dur(sum(r['speech_dur'] for r in recs))}",
          "   (prepisani del = od prve do zadnje besede v posnetku;",
          "    govorni čas = seštevek časov, ko kdo govori; prekrivanja štejejo enkrat)", ""]

    L += ["3. Število različnih govorcev",
          f"   Z vsaj eno besedo:       {fmt_int(n_act)}",
          f"   Vsi v tabelah govorcev:  {fmt_int(len(speakers))}", ""]

    L += ["4. Število besednih pojavnic in povedi",
          f"   Besede:  {fmt_int(total_words)}",
          f"   Povedi:  {fmt_int(sum(r['sentences'] for r in recs)) if has_sentence_tier else 'ni podatka (plast s povedmi ni najdena)'}",
          ""]
    L += ["5. Število različnih besednih oblik (brez razlikovanja velikih/malih črk)",
          f"   {fmt_int(len(type_counter))}", ""]

    def dist_section(title, field):
        cnt = Counter((s.get(field) or NO_DATA) for s in active.values())
        rows = [[g, fmt_int(n), fmt_pct(n, n_act)] for g, n in sorted(cnt.items(), key=lambda x: group_sort_key(x[0]))]
        return [title] + table(["skupina", "govorci", "delež"], rows) + [""]

    L += dist_section("6. Porazdelitev govorcev po spolu", "sex")
    L += dist_section("7. Porazdelitev govorcev po starostnih skupinah", "age")
    geo = [(lab, f) for lab, f in (("regija", "region"), ("država", "country"), ("kraj", "settlement"))
           if any(s.get(f) for s in active.values())] or [("regija", "region")]
    L += ["8. Porazdelitev govorcev po kraju stalnega bivališča"]
    for lab, f in geo:
        cnt = Counter((s.get(f) or NO_DATA) for s in active.values())
        rows = [[g, fmt_int(n), fmt_pct(n, n_act)] for g, n in sorted(cnt.items(), key=lambda x: group_sort_key(x[0]))]
        L += [f"   {lab.capitalize()}:"] + table([lab, "govorci", "delež"], rows, indent="      ") + [""]

    L += ["9. Število in delež besed po demografskih skupinah"]
    for label, field in [("spol", "sex"), ("starost", "age")] + geo:
        cnt = Counter()
        for s in active.values():
            cnt[s.get(field) or NO_DATA] += s["words"]
        rows = [[g, fmt_int(n), fmt_pct(n, total_words)] for g, n in sorted(cnt.items(), key=lambda x: group_sort_key(x[0]))]
        L += [f"   {label.capitalize()}:"] + table([label, "besede", "delež"], rows, indent="      ") + [""]

    L += ["10. Posnetki po vrstah govornih dogodkov (GENRE/DOMAIN)"]
    g = defaultdict(lambda: [0, 0.0, 0, 0.0])
    for r in recs:
        x = g[r["genre"] or NO_DATA]
        x[0] += 1; x[1] += r["dur"]; x[2] += r["words"]; x[3] += r["trans_dur"]
    rows = [[k, fmt_int(v[0]), fmt_dur(v[1]), fmt_dur(v[3]), fmt_int(v[2])] for k, v in sorted(g.items(), key=lambda x: group_sort_key(x[0]))]
    L += table(["zvrst", "posnetki", "trajanje WAV", "prepisano", "besede"], rows) + [""]

    L += ["11. Porazdelitev posnetkov po številu govorcev (z vsaj eno besedo)"]
    cnt = Counter(r["n_speakers"] for r in recs)
    rows = [[str(n), fmt_int(c), fmt_pct(c, len(recs))] for n, c in sorted(cnt.items())]
    L += table(["št. govorcev", "posnetki", "delež"], rows) + [""]

    L += ["12. Porazdelitev besed po govorcih"]
    wl = [s["words"] for s in active.values()]
    if wl:
        L += [f"   Povprečje: {fmt_num(statistics.mean(wl))}",
              f"   Mediana:   {fmt_num(statistics.median(wl))}",
              f"   Razpon:    {fmt_int(min(wl))} – {fmt_int(max(wl))}",
              "",
              "   Legenda:",
              "   - Povprečje: vse besede, deljene s številom govorcev.",
              "   - Mediana: vrednost na sredini, če govorce razvrstimo po številu besed;",
              "     polovica govorcev je izrekla manj besed, polovica več.",
              "   - Razpon: število besed govorca z najmanj in govorca z največ besedami.", ""]
    else:
        L += ["   Ni podatkov.", ""]

    L += ["13. Posnetki po letih snemanja"]
    y = defaultdict(lambda: [0, 0.0, 0.0])
    for r in recs:
        x = y[str(r["year"]) if r["year"] else NO_DATA]
        x[0] += 1; x[1] += r["dur"]; x[2] += r["trans_dur"]
    rows = [[k, fmt_int(v[0]), fmt_dur(v[1]), fmt_dur(v[2])] for k, v in sorted(y.items(), key=lambda x: group_sort_key(x[0]))]
    L += table(["leto", "posnetki", "trajanje WAV", "prepisano"], rows) + [""]

    L += ["14. Plasti v korpusu (category, type)"]
    order = {"t": 0, "a": 1, "d": 2}
    for c, t in sorted(categories, key=lambda x: (order.get(x[1], 9), x[0].lower())):
        L.append(f"   {c} ({t})")
    L.append("")

    L += ["15. Manjkajoči metapodatki"]
    n_rec = len(recs)
    rows = [
        ["zvrst (GENRE/DOMAIN)", fmt_int(sum(r["genre"] is None for r in recs)), fmt_pct(sum(r["genre"] is None for r in recs), n_rec)],
        ["leto snemanja", fmt_int(sum(r["year"] is None for r in recs)), fmt_pct(sum(r["year"] is None for r in recs), n_rec)],
        ["WAV datoteka", fmt_int(sum(r["wav"] is None for r in recs)), fmt_pct(sum(r["wav"] is None for r in recs), n_rec)],
    ]
    L += [f"   Posnetki (N = {fmt_int(n_rec)}):"] + table(["kategorija", "manjka", "delež"], rows, indent="      ") + [""]
    rows = [[lab, fmt_int(sum(s.get(f) is None for s in active.values())),
             fmt_pct(sum(s.get(f) is None for s in active.values()), n_act)]
            for lab, f in [("spol", "sex"), ("starost", "age")] + geo]
    L += [f"   Govorci (N = {fmt_int(n_act)}):"] + table(["kategorija", "manjka", "delež"], rows, indent="      ") + [""]

    rec_keys = sorted({k for r in recs for k in r["meta"]})
    if rec_keys:
        rows = [[k, fmt_int(sum(is_missing(r["meta"].get(k)) for r in recs)),
                 fmt_pct(sum(is_missing(r["meta"].get(k)) for r in recs), n_rec)] for k in rec_keys]
        L += ["   Vsa polja posnetkov (ud-meta-information):"] + table(["polje", "manjka", "delež"], rows, indent="      ") + [""]
    sp_keys = sorted({k for s in active.values() for k in s["ud"]})
    if sp_keys:
        rows = [[k, fmt_int(sum(is_missing(s["ud"].get(k)) for s in active.values())),
                 fmt_pct(sum(is_missing(s["ud"].get(k)) for s in active.values()), n_act)] for k in sp_keys]
        L += ["   Vsa polja govorcev (ud-speaker-information):"] + table(["polje", "manjka", "delež"], rows, indent="      ") + [""]

    L += ["OPOZORILA", "=" * 70]
    if silent:
        warnings.append(f"Govorci brez besed (niso upoštevani): {len(silent)} - " + ", ".join(silent[:30])
                        + (" ..." if len(silent) > 30 else ""))
    L += [f"   - {w}" for w in warnings] or ["   Ni opozoril."]

    Path(args.output).write_text("\n".join(L) + "\n", encoding="utf-8")
    log(f"Statistika zapisana v: {args.output}")
    return {"exb": len(docs), "wav": len(wav_files), "words": total_words,
            "speakers": n_act, "warnings": len(warnings), "output": str(args.output)}


def main():
    ap = argparse.ArgumentParser(description="Statistika govornega korpusa (EXB + WAV).")
    ap.add_argument("mapa", help="mapa s korpusom (pregleda se rekurzivno)")
    ap.add_argument("-o", "--output", default="statistika_korpusa.txt", help="izhodna .txt datoteka")
    ap.add_argument("--word-tier", help="category plasti za stetje besed (npr. std ali pog)")
    ap.add_argument("--speaker-key", default="auto",
                    help="po cem se prepozna isti govorec: auto (privzeto; PRS-ID, ce obstaja, "
                         "sicer id), id, abbreviation ali ime ud-polja govorca (npr. PRS-ID)")
    a = ap.parse_args()
    generate(a.mapa, a.output, a.word_tier, a.speaker_key)


# ------------------------------ graficni vmesnik ------------------------------

def gui():
    import os
    import queue
    import subprocess
    import threading
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter.scrolledtext import ScrolledText

    win = tk.Tk()
    win.title("Statistika govornega korpusa")
    win.geometry("680x520")
    win.minsize(560, 420)

    corpus_var = tk.StringVar()
    out_var = tk.StringVar()
    tier_var = tk.StringVar()
    key_var = tk.StringVar(value="auto")
    msgs = queue.Queue()
    state = {"output": None}

    frm = ttk.Frame(win, padding=10)
    frm.pack(fill="both", expand=True)
    frm.columnconfigure(0, weight=1)

    def choose_corpus():
        d = filedialog.askdirectory(title="Izberi mapo s korpusom")
        if d:
            corpus_var.set(d)
            if not out_var.get():
                out_var.set(d)

    def choose_out():
        d = filedialog.askdirectory(title="Izberi izhodno mapo")
        if d:
            out_var.set(d)

    ttk.Label(frm, text="Mapa s korpusom (EXB in WAV se poiščejo v vseh podmapah):").grid(row=0, column=0, columnspan=2, sticky="w")
    ttk.Entry(frm, textvariable=corpus_var).grid(row=1, column=0, sticky="ew", pady=(2, 8))
    ttk.Button(frm, text="Izberi ...", command=choose_corpus).grid(row=1, column=1, padx=(6, 0), pady=(2, 8))

    ttk.Label(frm, text="Izhodna mapa:").grid(row=2, column=0, columnspan=2, sticky="w")
    ttk.Entry(frm, textvariable=out_var).grid(row=3, column=0, sticky="ew", pady=(2, 8))
    ttk.Button(frm, text="Izberi ...", command=choose_out).grid(row=3, column=1, padx=(6, 0), pady=(2, 8))

    opt = ttk.LabelFrame(frm, text="Nastavitve (neobvezno)", padding=8)
    opt.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 8))
    ttk.Label(opt, text="Plast za štetje besed:").grid(row=0, column=0, sticky="w")
    ttk.Entry(opt, textvariable=tier_var, width=18).grid(row=0, column=1, sticky="w", padx=6)
    ttk.Label(opt, text="prazno = samodejno").grid(row=0, column=2, sticky="w")
    ttk.Label(opt, text="Prepoznavanje govorca:").grid(row=1, column=0, sticky="w", pady=(6, 0))
    ttk.Combobox(opt, textvariable=key_var, values=["auto", "id", "abbreviation", "PRS-ID"],
                 width=16).grid(row=1, column=1, sticky="w", padx=6, pady=(6, 0))
    ttk.Label(opt, text="auto = PRS-ID, če obstaja").grid(row=1, column=2, sticky="w", pady=(6, 0))

    logbox = ScrolledText(frm, height=12, state="disabled", wrap="word")
    logbox.grid(row=5, column=0, columnspan=2, sticky="nsew")
    frm.rowconfigure(5, weight=1)

    btns = ttk.Frame(frm)
    btns.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    btns.columnconfigure(0, weight=1)
    run_btn = ttk.Button(btns, text="Izračunaj statistiko")
    run_btn.grid(row=0, column=0, sticky="ew", ipady=4)
    open_btn = ttk.Button(btns, text="Odpri rezultat", state="disabled")
    open_btn.grid(row=0, column=1, padx=(6, 0), ipady=4)

    def write(line):
        logbox.configure(state="normal")
        logbox.insert("end", line + "\n")
        logbox.see("end")
        logbox.configure(state="disabled")

    def poll():
        try:
            while True:
                kind, val = msgs.get_nowait()
                if kind == "log":
                    write(val)
                elif kind == "done":
                    run_btn.configure(state="normal")
                    state["output"] = val["output"]
                    open_btn.configure(state="normal")
                    words = f"{val['words']:,}".replace(",", ".")
                    note = f", opozorila: {val['warnings']} (glej konec datoteke)" if val["warnings"] else ""
                    write(f"Končano. Posnetki: {val['exb']}, govorci: {val['speakers']}, besede: {words}{note}")
                elif kind == "error":
                    run_btn.configure(state="normal")
                    write("NAPAKA: " + val)
                    messagebox.showerror("Napaka", val)
        except queue.Empty:
            pass
        win.after(100, poll)

    def worker(corpus, output, tier, key):
        try:
            res = generate(corpus, output, tier or None, key or "auto",
                           log=lambda m: msgs.put(("log", m)))
            msgs.put(("done", res))
        except Exception as e:  # noqa: BLE001
            msgs.put(("error", str(e)))

    def run():
        corpus = corpus_var.get().strip()
        outdir = out_var.get().strip()
        if not corpus or not Path(corpus).is_dir():
            messagebox.showwarning("Manjka mapa", "Izberi mapo s korpusom.")
            return
        if not outdir or not Path(outdir).is_dir():
            messagebox.showwarning("Manjka mapa", "Izberi izhodno mapo.")
            return
        name = Path(corpus).name or "korpus"
        output = Path(outdir) / f"statistika_{name}_{datetime.now():%Y-%m-%d_%H%M}.txt"
        run_btn.configure(state="disabled")
        open_btn.configure(state="disabled")
        logbox.configure(state="normal")
        logbox.delete("1.0", "end")
        logbox.configure(state="disabled")
        threading.Thread(target=worker, daemon=True,
                         args=(corpus, str(output), tier_var.get().strip(), key_var.get().strip())).start()

    def open_result():
        p = state["output"]
        if not p:
            return
        if sys.platform.startswith("win"):
            os.startfile(p)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])

    run_btn.configure(command=run)
    open_btn.configure(command=open_result)
    write("Izberi mapo s korpusom in izhodno mapo, nato klikni »Izračunaj statistiko«.")
    poll()
    win.mainloop()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main()
    else:
        gui()
