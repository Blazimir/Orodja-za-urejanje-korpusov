#!/usr/bin/env python3
"""
exb2trs.py – pretvornik EXMARaLDA Basic Transcription (.exb) -> Transcriber (.trs)

Uporaba:
  python exb2trs.py EXB TRS_nove                   (cela mapa)
  python exb2trs.py EXB\\Zila-P031.exb nova.trs     (ena datoteka)
  python exb2trs.py EXB TRS_nove --scribe Tanja    (ime transkriptorja v glavi)

Preslikava (izpeljana iz korpusa Zila):
  exb                                          trs
  -----------------------------------------    -----------------------------------------
  <speaker id=spk1><abbreviation>G006          <Speaker id=spk1 name=G006 .../>
  dogodek na plasti govorca                    <Sync time=t> + besedilo
  enaka intervala na dveh plasteh              <Turn speaker="spk1 spk2"> + <Who nb=..>
  dogodek na plasti [nn]                       izmena brez govorca
  [premor] [smeh] ...                          <Event desc=.. type="noise" .../>
  [de...]besedilo[...de]                       <Event desc="de" type="language" begin/end/>
  [anonim]                                     [anonim] (navadno besedilo)

V exb NI shranjeno (in ga zato ni v novem trs): scribe in version iz glave,
Background elementi (anonimizacijski piski), vrstni red govorcev v prekrivanju
(transkriptorjeva izbira – pretvornik uporabi pravilo, ki se z izvirnikom ujema v ~68 %)
in meje med zaporednimi izmenami istega govorca.
"""
import argparse
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

EVENTS = {"premor": "noise", "glas": "noise", "smeh": "noise", "zvok": "noise",
          "nerazumljivo": "noise", "dih": "noise", "jok": "noise",
          "de": "language", "it": "language", "la": "language", "en": "language", "fr": "language",
          "es": "language", "bo": "language", "ne": "language"}
LITERAL = {"anonim"}          # [oznake], ki so v trs navadno besedilo
SPEAKER_ATTRS = 'check="no" dialect="native" accent="" scope="local"'

TOKEN_RE = re.compile(r"\[(?P<begin>[^\[\]]+?)\.\.\.\]|\[\.\.\.(?P<end>[^\[\]]+?)\]|\[(?P<inst>[^\[\]]+)\]")


# --------------------------------------------------------------------------
# Branje exb
# --------------------------------------------------------------------------

def read_exb(path, warn):
    root = ET.parse(path).getroot()
    tlis = root.findall("./basic-body/common-timeline/tli")
    ids = [t.get("id") for t in tlis]
    times = [float(t.get("time")) if t.get("time") is not None else None for t in tlis]
    known = [i for i, t in enumerate(times) if t is not None]
    if not known:
        raise ValueError("časovnica nima nobene točke s časom")
    missing = [i for i, t in enumerate(times) if t is None]
    for i in missing:                                   # točke brez časa: linearna interpolacija
        p = max((k for k in known if k < i), default=None)
        n = min((k for k in known if k > i), default=None)
        times[i] = times[n] if p is None else times[p] if n is None else \
            times[p] + (i - p) / (n - p) * (times[n] - times[p])
    if missing:
        warn.append(f"{len(missing)} točk časovnice brez časa – interpolirano")

    # zapis časa kot v izvirnem trs: id točke (npr. T70-540) ohrani izvirni zapis "70.540"
    labels = []
    for tid, t in zip(ids, times):
        s = tid[1:].replace("-", ".") if tid and tid.startswith("T") else ""
        try:
            ok = abs(float(s) - t) < 1e-6
        except ValueError:
            ok = False
        labels.append(s if ok else (f"{t:.3f}".rstrip("0").rstrip(".") or "0"))

    order = {tid: i for i, tid in enumerate(ids)}
    speakers = [(sp.get("id"), (sp.findtext("abbreviation") or sp.get("id")).strip())
                for sp in root.findall("./head/speakertable/speaker")]
    ref = root.find("./head/meta-information/referenced-file")
    audio = Path(ref.get("url")).stem if ref is not None and ref.get("url") else Path(path).stem

    speech, nn, tier_order = [], [], []
    for tier in root.findall("./basic-body/tier"):
        spk, typ = tier.get("speaker"), tier.get("type")
        evs = []
        for e in tier.findall("event"):
            s, en = order[e.get("start")], order[e.get("end")]
            if times[en] <= times[s]:
                warn.append(f"dogodek {e.get('start')}–{e.get('end')} ima ničelno ali negativno dolžino – izpuščen")
                continue
            evs.append((s, en, (e.text or "").strip()))
        if typ == "t" and spk:
            tier_order.append(spk)
            speech += [(s, e, spk, x) for s, e, x in evs]
        elif typ == "d" and not spk and tier.get("category") == "nn":
            nn += evs
        elif evs:
            warn.append(f"plast {tier.get('id')} (type={typ}) nima ustreznice v trs – izpuščena")
    return {"times": times, "labels": labels, "ids": ids, "speakers": speakers, "audio": audio,
            "speech": speech, "nn": nn, "tier_order": tier_order}


# --------------------------------------------------------------------------
# Gradnja izmen
# --------------------------------------------------------------------------

def build_turns(d, warn):
    evs = [(s, e) for s, e, *_ in d["speech"]] + [(s, e) for s, e, _ in d["nn"]]
    bounds = sorted({b for ev in evs for b in ev})
    inner = {b for b in bounds for s, e in evs if s < b < e}
    if inner:
        warn.append(f"{len(inner)} delnih prekrivanj – intervali združeni")
    bounds = [b for b in bounds if b not in inner]

    rank = {s: i for i, s in enumerate(d["tier_order"])}
    turns, prev = [], ()
    ivs = []
    for a, b in zip(bounds, bounds[1:]):
        spk = {}
        for s, e, sp, x in sorted(d["speech"]):
            if a <= s and e <= b:
                spk[sp] = (spk.get(sp, "") + " " + x).strip()
        ivs.append((a, b, spk, " ".join(x for s, e, x in d["nn"] if a <= s and e <= b)))

    for n, (a, b, spk, nn) in enumerate(ivs):
        nxt = set(ivs[n + 1][2]) if n + 1 < len(ivs) else set()
        if nn and spk:
            first = next(iter(spk))
            spk[first] = (nn + " " + spk[first]).strip()
            warn.append(f"dogodek na plasti nn pri {d['labels'][a]} se prekriva z govorom")
        if len(spk) <= 1:
            key = tuple(spk)
        elif set(prev) == set(spk):
            key = prev                      # prekrivanje se nadaljuje
        else:                               # najprej govorec, ki je govoril tik prej
            key = tuple(sorted(spk, key=lambda s: (s not in prev, s in nxt, rank.get(s, 99))))
        content = [(s, spk[s]) for s in key] if key else [(None, nn)]
        if turns and turns[-1]["spk"] == key:
            turns[-1]["syncs"].append((a, content))
            turns[-1]["end"] = b
        else:
            turns.append({"spk": key, "start": a, "end": b, "syncs": [(a, content)]})
        prev = key
    return turns


# --------------------------------------------------------------------------
# Zapis trs
# --------------------------------------------------------------------------

def text_items(text, unknown):
    """besedilo exb dogodka -> seznam ('text', niz) / ('tag', <Event .../>)"""
    out, pos = [], 0
    for m in TOKEN_RE.finditer(text):
        if m.group("inst") in LITERAL:
            continue
        if m.start() > pos:
            out.append(("text", text[pos:m.start()]))
        desc = m.group("begin") or m.group("end") or m.group("inst")
        ext = "begin" if m.group("begin") else "end" if m.group("end") else "instantaneous"
        typ = EVENTS.get(desc)
        if typ is None:
            typ = "noise" if ext == "instantaneous" else "language"
            unknown.add(desc)
        out.append(("tag", f'<Event desc={quoteattr(desc)} type="{typ}" extent="{ext}"/>', "Event"))
        pos = m.end()
    if pos < len(text):
        out.append(("text", text[pos:]))
    return out


def emit(items):
    """Transcriberjevo oblikovanje: med dvema oznakama brez besedila vmes je prazna vrstica
    (razen med <Sync> in <Who>)."""
    lines, prev = [], None
    for it in items:
        if it[0] == "tag":
            if prev is not None and prev[0] == "tag" and not (prev[2] == "Sync" and it[2] == "Who"):
                lines.append("")
            lines.append(it[1])
        else:
            lines.append(escape(it[1]))
        prev = it
    return lines


def write_trs(d, turns, out_path, scribe, unknown):
    L = d["labels"]
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<!DOCTYPE Trans SYSTEM "trans-14.dtd">',
           f'<Trans scribe={quoteattr(scribe)} audio_filename={quoteattr(d["audio"])} version="1" '
           f'version_date="{date.today():%y%m%d}">', "<Speakers>"]
    out += [f"<Speaker id={quoteattr(i)} name={quoteattr(n)} {SPEAKER_ATTRS}/>" for i, n in d["speakers"]]
    out += ["</Speakers>", "<Episode>",
            f'<Section type="report" startTime="{L[turns[0]["start"]]}" endTime="{L[turns[-1]["end"]]}">']
    for k, t in enumerate(turns):
        times = f'startTime="{L[t["start"]]}" endTime="{L[t["end"]]}"'
        if not t["spk"]:
            out.append(f"<Turn {times}>")
        elif k == 0:
            out.append(f'<Turn {times} speaker="{" ".join(t["spk"])}">')
        else:
            out.append(f'<Turn speaker="{" ".join(t["spk"])}" {times}>')
        items = []
        for a, content in t["syncs"]:
            items.append(("tag", f'<Sync time="{L[a]}"/>', "Sync"))
            for nb, (_, txt) in enumerate(content, 1):
                if len(t["spk"]) > 1:
                    items.append(("tag", f'<Who nb="{nb}"/>', "Who"))
                items += text_items(txt, unknown)
        items.append(("tag", "</Turn>", "/Turn"))
        out += emit(items)
    out += ["</Section>", "</Episode>", "</Trans>", ""]
    Path(out_path).write_text("\n".join(out), encoding="utf-8")


def convert(exb, trs, scribe):
    warn, unknown = [], set()
    d = read_exb(exb, warn)
    turns = build_turns(d, warn)
    if not turns:
        raise ValueError("datoteka nima nobenega dogodka")
    write_trs(d, turns, trs, scribe, unknown)
    if unknown:
        warn.append("neznane oznake: " + ", ".join(sorted(unknown)))
    return warn


def main():
    ap = argparse.ArgumentParser(description="Pretvorba EXMARaLDA .exb v Transcriber .trs")
    ap.add_argument("vhod", help="datoteka .exb ali mapa z .exb")
    ap.add_argument("izhod", help="datoteka .trs ali mapa za izhod")
    ap.add_argument("--scribe", default="exb2trs", help="ime transkriptorja v glavi trs")
    a = ap.parse_args()
    src, dst = Path(a.vhod), Path(a.izhod)
    if src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        jobs = [(p, dst / (p.stem + ".trs")) for p in sorted(src.glob("*.exb"))]
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        jobs = [(src, dst)]
    ok = 0
    for exb, trs in jobs:
        try:
            for w in convert(exb, trs, a.scribe):
                print(f"{exb.name}: {w}")
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"NAPAKA {exb.name}: {e}", file=sys.stderr)
    print(f"Pretvorjenih {ok}/{len(jobs)} datotek v {dst}")


if __name__ == "__main__":
    main()
