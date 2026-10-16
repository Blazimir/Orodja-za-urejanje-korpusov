#!/usr/bin/env python3
"""Paketna pretvorba Transcriber .trs (XML) datotek v .txt.

Privzeti izhod posnema Transcriberjev izvoz v besedilo:
  G009:  besedilo                       (dva presledka za dvopicjem)
  G006:  #1 prekrivanje #               (prekrivanje govora)
  G015:  [lang=German-] beseda [-lang=German]   (jezikovni vstavki)
  turni brez govorca se izpustijo (in prekinejo zaporedje istega govorca)

Primeri:
  python trs_v_txt.py mapa_s_trs                    # rezultat v mapa_s_trs/txt
  python trs_v_txt.py mapa_s_trs -o izhod           # rezultat v mapo "izhod"
  python trs_v_txt.py mapa_s_trs --nacin vrstice    # vsak odsek (Sync) v svojo vrstico
  python trs_v_txt.py mapa_s_trs --nacin cas        # z casovnimi oznakami
  python trs_v_txt.py Zila-P031.trs                 # ena sama datoteka
"""
import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# Kode jezikov v <Event type="language" desc="xx"> po standardu ISO 639-1
# (celoten seznam, brez potrebe po dodatni knjižnici). Če se pojavi koda, ki
# je tu ni (npr. iz ISO 639-2/3), jo dodaj spodaj v obliki "xx": "Ime".
JEZIKI = {
    "aa": "Afar", "ab": "Abkhazian", "ae": "Avestan", "af": "Afrikaans",
    "ak": "Akan", "am": "Amharic", "an": "Aragonese", "ar": "Arabic",
    "as": "Assamese", "av": "Avaric", "ay": "Aymara", "az": "Azerbaijani",
    "ba": "Bashkir", "be": "Belarusian", "bg": "Bulgarian", "bh": "Bihari",
    "bi": "Bislama", "bm": "Bambara", "bn": "Bengali", "bo": "Tibetan",
    "br": "Breton", "bs": "Bosnian", "ca": "Catalan", "ce": "Chechen",
    "ch": "Chamorro", "co": "Corsican", "cr": "Cree", "cs": "Czech",
    "cu": "Church Slavic", "cv": "Chuvash", "cy": "Welsh", "da": "Danish",
    "de": "German", "dv": "Divehi", "dz": "Dzongkha", "ee": "Ewe",
    "el": "Greek", "en": "English", "eo": "Esperanto", "es": "Spanish",
    "et": "Estonian", "eu": "Basque", "fa": "Persian", "ff": "Fulah",
    "fi": "Finnish", "fj": "Fijian", "fo": "Faroese", "fr": "French",
    "fy": "Western Frisian", "ga": "Irish", "gd": "Scottish Gaelic",
    "gl": "Galician", "gn": "Guarani", "gu": "Gujarati", "gv": "Manx",
    "ha": "Hausa", "he": "Hebrew", "hi": "Hindi", "ho": "Hiri Motu",
    "hr": "Croatian", "ht": "Haitian", "hu": "Hungarian", "hy": "Armenian",
    "hz": "Herero", "ia": "Interlingua", "id": "Indonesian",
    "ie": "Interlingue", "ig": "Igbo", "ii": "Sichuan Yi",
    "ik": "Inupiaq", "io": "Ido", "is": "Icelandic", "it": "Italian",
    "iu": "Inuktitut", "ja": "Japanese", "jv": "Javanese", "ka": "Georgian",
    "kg": "Kongo", "ki": "Kikuyu", "kj": "Kuanyama", "kk": "Kazakh",
    "kl": "Kalaallisut", "km": "Khmer", "kn": "Kannada", "ko": "Korean",
    "kr": "Kanuri", "ks": "Kashmiri", "ku": "Kurdish", "kv": "Komi",
    "kw": "Cornish", "ky": "Kyrgyz", "la": "Latin", "lb": "Luxembourgish",
    "lg": "Ganda", "li": "Limburgan", "ln": "Lingala", "lo": "Lao",
    "lt": "Lithuanian", "lu": "Luba-Katanga", "lv": "Latvian",
    "mg": "Malagasy", "mh": "Marshallese", "mi": "Maori", "mk": "Macedonian",
    "ml": "Malayalam", "mn": "Mongolian", "mr": "Marathi", "ms": "Malay",
    "mt": "Maltese", "my": "Burmese", "na": "Nauru", "nb": "Norwegian Bokmål",
    "nd": "North Ndebele", "ne": "Nepali", "ng": "Ndonga", "nl": "Dutch",
    "nn": "Norwegian Nynorsk", "no": "Norwegian", "nr": "South Ndebele",
    "nv": "Navajo", "ny": "Nyanja", "oc": "Occitan", "oj": "Ojibwa",
    "om": "Oromo", "or": "Oriya", "os": "Ossetian", "pa": "Punjabi",
    "pi": "Pali", "pl": "Polish", "ps": "Pashto", "pt": "Portuguese",
    "qu": "Quechua", "rm": "Romansh", "rn": "Rundi", "ro": "Romanian",
    "ru": "Russian", "rw": "Kinyarwanda", "sa": "Sanskrit", "sc": "Sardinian",
    "sd": "Sindhi", "se": "Northern Sami", "sg": "Sango", "si": "Sinhala",
    "sk": "Slovak", "sl": "Slovenian", "sm": "Samoan", "sn": "Shona",
    "so": "Somali", "sq": "Albanian", "sr": "Serbian", "ss": "Swati",
    "st": "Southern Sotho", "su": "Sundanese", "sv": "Swedish",
    "sw": "Swahili", "ta": "Tamil", "te": "Telugu", "tg": "Tajik",
    "th": "Thai", "ti": "Tigrinya", "tk": "Turkmen", "tl": "Tagalog",
    "tn": "Tswana", "to": "Tonga", "tr": "Turkish", "ts": "Tsonga",
    "tt": "Tatar", "tw": "Twi", "ty": "Tahitian", "ug": "Uyghur",
    "uk": "Ukrainian", "ur": "Urdu", "uz": "Uzbek", "ve": "Venda",
    "vi": "Vietnamese", "vo": "Volapük", "wa": "Walloon", "wo": "Wolof",
    "xh": "Xhosa", "yi": "Yiddish", "yo": "Yoruba", "za": "Zhuang",
    "zh": "Chinese", "zu": "Zulu",
}
neznani_jeziki = set()


def oznaka_dogodka(el):
    opis = el.get("desc") or ""
    if el.get("type") == "language":
        if opis not in JEZIKI:
            neznani_jeziki.add(opis)
        opis = "lang=" + JEZIKI.get(opis, opis)
    obseg = el.get("extent")
    if obseg == "begin":
        return f"[{opis}-]"
    if obseg == "end":
        return f"[-{opis}]"
    return f"[{opis}]"


def imena_govorcev(root):
    return {s.get("id"): (s.get("name") or s.get("id")) for s in root.iter("Speaker")}


def razcleni_turn(turn, dogodki):
    """Vrne seznam odsekov (po en na <Sync>) za en Turn.

    Vsak odsek je seznam (indeks_govorca, cas, besedilo), urejen po govorcih.
    Besedilo brez <Who> pripada prvemu govorcu turna; <Who nb="k"> preklopi na
    k-tega. Ce v istem odseku govori vec govorcev, je to prekrivanje in se
    besedilo zapise kot "#k besedilo #".
    """
    odseki = []
    cas = float(turn.get("startTime", 0))
    trenutni = {}
    tren = 0

    def dodaj(t):
        if t and t.strip():
            trenutni.setdefault(tren, []).append(" ".join(t.split()))

    def zapri():
        prekrivanje = len(trenutni) > 1
        deli = []
        for i in sorted(trenutni):
            b = " ".join(trenutni[i])
            if prekrivanje:
                b = f"#{i + 1} {b} #"
            deli.append((i, cas, b))
        if deli:
            odseki.append(deli)
        trenutni.clear()

    dodaj(turn.text)
    for el in turn:
        if el.tag == "Sync":
            zapri()
            cas = float(el.get("time", cas))
            tren = 0
        elif el.tag == "Who":
            tren = int(el.get("nb") or el.get("nr") or 1) - 1
        elif el.tag == "Event" and dogodki:
            dodaj(oznaka_dogodka(el))
        elif el.tag == "Comment" and dogodki and el.get("desc"):
            dodaj(f"[{el.get('desc')}]")
        dodaj(el.tail)
    zapri()
    return odseki


def pretvori(pot, nacin="turni", dogodki=True, tudi_brez_govorca=False):
    root = ET.parse(pot).getroot()  # upošteva encoding iz glave XML
    govorci = imena_govorcev(root)
    bloki = []  # [ime, [(cas, besedilo), ...]]
    zadnji = None
    for turn in root.iter("Turn"):
        ids = (turn.get("speaker") or "").split()
        if not ids and not tudi_brez_govorca:
            zadnji = None  # turn brez govorca prekine zaporedje istega govorca
            continue
        imena = [govorci.get(i, i) for i in ids] or ["(no speaker)"]
        for odsek in razcleni_turn(turn, dogodki):
            for k, (i, cas, t) in enumerate(odsek):
                ime = imena[i] if i < len(imena) else "?"
                # Samo prvi del odseka se lahko spoji s prejsnjo vrstico istega
                # govorca; deli istega odseka (prekrivanje) ostanejo ločeni.
                if k == 0 and zadnji is not None and zadnji[0] == ime:
                    zadnji[1].append((cas, t))
                else:
                    zadnji = [ime, [(cas, t)]]
                    bloki.append(zadnji)

    vrstice = []
    for ime, odseki in bloki:
        if nacin == "turni":
            vrstice.append(f"{ime}:  " + " ".join(t for _, t in odseki))
        elif nacin == "vrstice":
            for k, (_, t) in enumerate(odseki):
                vrstice.append(f"{ime}:  {t}" if k == 0 else " " * 8 + t)
        elif nacin == "cas":
            for c, t in odseki:
                m, sek = divmod(c, 60)
                vrstice.append(f"[{int(m):02d}:{sek:05.2f}] {ime}:  {t}")
    return "\n".join(vrstice) + "\n"


def main():
    p = argparse.ArgumentParser(description="Pretvorba .trs v .txt")
    p.add_argument("vhod", help="mapa z .trs datotekami ali ena .trs datoteka")
    p.add_argument("-o", "--izhod", help="izhodna mapa (privzeto: podmapa 'txt')")
    p.add_argument("--nacin", choices=["turni", "vrstice", "cas"], default="turni")
    p.add_argument("--brez-dogodkov", action="store_true",
                   help="izpusti oznake [glas], [premor], [lang=...] ipd.")
    p.add_argument("--tudi-brez-govorca", action="store_true",
                   help="ohrani turne brez govorca (Transcriber jih izpusti)")
    p.add_argument("-r", "--rekurzivno", action="store_true",
                   help="išči tudi po podmapah")
    a = p.parse_args()

    vhod = Path(a.vhod)
    if vhod.is_file():
        datoteke = [vhod]
        izhod = Path(a.izhod) if a.izhod else vhod.parent
    else:
        iskanje = vhod.rglob if a.rekurzivno else vhod.glob
        datoteke = sorted(f for f in iskanje("*") if f.suffix.lower() == ".trs")
        izhod = Path(a.izhod) if a.izhod else vhod / "txt"
    izhod.mkdir(parents=True, exist_ok=True)

    ok, napake = 0, []
    for f in datoteke:
        try:
            besedilo = pretvori(f, a.nacin, not a.brez_dogodkov, a.tudi_brez_govorca)
            (izhod / (f.stem + ".txt")).write_text(besedilo, encoding="utf-8")
            ok += 1
        except Exception as e:
            napake.append((f.name, e))
    print(f"Pretvorjenih: {ok}/{len(datoteke)}  ->  {izhod}")
    if neznani_jeziki:
        print("Opozorilo: neznane kode jezikov (dodaj v JEZIKI):",
              ", ".join(sorted(neznani_jeziki)), file=sys.stderr)
    for ime, e in napake:
        print(f"  NAPAKA {ime}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
