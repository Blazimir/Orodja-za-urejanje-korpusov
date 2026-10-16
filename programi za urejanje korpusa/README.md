# Orodja za urejanje govornih korpusov

Tri orodja za delo z govornimi korpusi v formatih **EXMARaLDA** (`.exb`) in **Transcriber** (`.trs`):

| Program | Kaj naredi |
|---|---|
| **EXB-TRS pretvornik** | pretvori `.exb` v `.trs` |
| **TRS-TXT pretvornik** | paketno pretvori `.trs` v navadno besedilo `.txt` |
| **Statistika korpusa** | iz `.exb` in `.wav` datotek izračuna statistiko korpusa |

Orodja so bila preizkušena na korpusih **Zila** in **ROG-Art**.

## Namestitev

**Windows:** prenesi `.exe` datoteke iz razdelka [Releases](../../releases) in jih zaženi. Python ni potreben.

**Python:** potrebuješ Python 3.8 ali novejši. Dodatni paketi niso potrebni, ker programi uporabljajo samo standardno knjižnico.

```bash
git clone https://github.com/UPORABNIK/IME-REPOZITORIJA.git
```

---

## EXB-TRS pretvornik

Pretvori datoteke EXMARaLDA Basic Transcription (`.exb`) v format Transcriber (`.trs`).

```bash
python EXB-TRS_pretvornik.py EXB TRS_nove                   # cela mapa
python EXB-TRS_pretvornik.py EXB/Zila-P031.exb nova.trs     # ena datoteka
python EXB-TRS_pretvornik.py EXB TRS_nove --scribe Tanja    # ime transkriptorja v glavi
```

### Preslikava

| `.exb` | `.trs` |
|---|---|
| govorec (`<abbreviation>`) | `<Speaker name=...>` |
| dogodek na plasti govorca | `<Sync time=...>` + besedilo |
| enaka intervala na dveh plasteh | `<Turn speaker="spk1 spk2">` + `<Who nb=...>` |
| dogodek na plasti `[nn]` | izmena brez govorca |
| `[premor]`, `[smeh]` ... | `<Event type="noise">` |
| `[de...]besedilo[...de]` | `<Event type="language">` z `begin`/`end` |
| `[anonim]` | ostane navadno besedilo |

### Omejitve

Nekateri podatki v `.exb` niso shranjeni, zato jih pretvornik ne more obnoviti:

- `scribe` in `version` iz glave izvirne `.trs` datoteke,
- elementi `Background` (npr. anonimizacijski piski),
- meje med zaporednimi izmenami istega govorca,
- vrstni red govorcev pri prekrivanju govora. Pretvornik uporabi pravilo, ki se z izvirnikom ujema v približno 68 % primerov.

Pretvornik ob tem izpiše opozorila, npr. za točke časovnice brez časa (te se linearno interpolirajo), delna prekrivanja (intervali se združijo) in neznane oznake v oglatih oklepajih.

---

## TRS-TXT pretvornik

Paketno pretvori `.trs` datoteke v `.txt`. Privzeti izhod posnema Transcriberjev izvoz v besedilo:

```
G009:  besedilo
G006:  #1 prekrivanje #
G015:  [lang=German-] beseda [-lang=German]
```

```bash
python TRS-TXT_pretvornik.py mapa_s_trs                    # rezultat v mapa_s_trs/txt
python TRS-TXT_pretvornik.py mapa_s_trs -o izhod           # rezultat v mapo "izhod"
python TRS-TXT_pretvornik.py mapa_s_trs --nacin vrstice    # vsak odsek (Sync) v svojo vrstico
python TRS-TXT_pretvornik.py mapa_s_trs --nacin cas        # s časovnimi oznakami
python TRS-TXT_pretvornik.py Zila-P031.trs                 # ena sama datoteka
```

| Možnost | Pomen |
|---|---|
| `-o`, `--izhod` | izhodna mapa (privzeto podmapa `txt`) |
| `--nacin` | `turni` (privzeto), `vrstice` ali `cas` |
| `--brez-dogodkov` | izpusti oznake, kot so `[glas]`, `[premor]`, `[lang=...]` |
| `--tudi-brez-govorca` | ohrani izmene brez govorca (Transcriber jih izpusti) |
| `-r`, `--rekurzivno` | išči tudi po podmapah |

Kode jezikov se pretvorijo v imena po standardu ISO 639-1. Če program naleti na neznano kodo, izpiše opozorilo, kodo pa lahko dodaš v slovar `JEZIKI` na začetku skripte.

---

## Statistika korpusa

Rekurzivno pregleda mapo s korpusom, prebere vse `.exb` in `.wav` datoteke ter v `.txt` datoteko izpiše 15 statističnih postavk:

1. število posnetkov
2. skupno trajanje posnetkov
3. število različnih govorcev
4. število besednih pojavnic in povedi
5. število različnih besednih oblik
6. porazdelitev govorcev po spolu
7. porazdelitev govorcev po starostnih skupinah
8. porazdelitev govorcev po kraju stalnega bivališča
9. število in delež besed po demografskih skupinah
10. posnetki po vrstah govornih dogodkov
11. porazdelitev posnetkov po številu govorcev
12. porazdelitev besed po govorcih
13. posnetki po letih snemanja
14. plasti v korpusu
15. manjkajoči metapodatki

Brez argumentov se odpre okno, v katerem izbereš mapo s korpusom in izhodno mapo:

```bash
python statistika_korpusa.py
```

Uporaba v ukazni vrstici:

```bash
python statistika_korpusa.py MAPA_KORPUSA
python statistika_korpusa.py MAPA_KORPUSA -o rog_statistika.txt
python statistika_korpusa.py MAPA_KORPUSA --word-tier pog
python statistika_korpusa.py MAPA_KORPUSA --speaker-key abbreviation
```

| Možnost | Pomen |
|---|---|
| `-o`, `--output` | izhodna `.txt` datoteka |
| `--word-tier` | plast (`category`), iz katere se štejejo besede, npr. `std` ali `pog` |
| `--speaker-key` | po čem se prepozna isti govorec: `auto` (privzeto), `id`, `abbreviation` ali ime polja govorca, npr. `PRS-ID` |

### Prilagajanje drugim korpusom

Na začetku skripte je razdelek **NASTAVITVE**, kjer lahko prilagodiš imena polj v metapodatkih (spol, starost, regija, datum ...), vrstni red iskanja plasti za štetje besed, vrednosti, ki štejejo kot manjkajoče, in pravila štetja besed (npr. ali se mašila, kot sta *eee* in *mhm*, štejejo kot besede).

---

## Avtor

[Ime Priimek], izdelano v okviru praktičnega usposabljanja z delom (PUD) na [ustanova], 2026.

## Licenca

Glej datoteko [LICENSE](LICENSE).
