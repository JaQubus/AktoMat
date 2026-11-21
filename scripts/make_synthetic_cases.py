"""Generator FIKCYJNYCH spraw testowych → data/synthetic/.

Wynik:
  data/synthetic/<case_id>.zip                  paczka wejściowa (odwołanie podpisane pyHanko, odpis KRS, przelew, dowód kopii)
  data/synthetic/ground_truth/<case_id>.yaml    wzorzec w formacie Zał. D (version 2, min_similarity, assert)
  data/synthetic/ground_truth/<case_id>.rules.yaml  oczekiwane wyniki F1–F13 (nasze rozszerzenie, do testów M5)
  data/synthetic/krs_mock/<krs>.json            odpowiedzi mocka KRS API (kształt zbliżony do api-krs.ms.gov.pl)

Wszystko jest wymyślone: firmy, osoby, numery (NIP/REGON z poprawną sumą kontrolną, KRS poza zakresem
istniejących numerów). Każdy PDF ma znak wodny „DANE FIKCYJNE". Certyfikat do podpisu jest lokalny,
samopodpisany i NIEKWALIFIKOWANY (ścieżka F4 → do weryfikacji ręcznej). Zmiana: QUALIFIED_SIM_CASES.

Założenia wzorca (pole `assert`): shift_weekend_holiday=true (sprawa 4: termin z soboty → poniedziałek).

Uruchomienie: cd backend && uv run python ../scripts/make_synthetic_cases.py
"""
from __future__ import annotations

import io
import json
import os
import random
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

REPO = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("SYNTH_OUT", REPO / "data" / "synthetic"))
CERT_DIR = REPO / "var" / "synthetic_certs"
QUALIFIED_SIM_CASES: tuple[str, ...] = ()  # id spraw podpisanych certyfikatem z QcCompliance (symulacja kwalifikowanego)
FAKE_PESEL = "44051401359"  # przykładowy PESEL ze specyfikacji; testuje maskowanie danych z certyfikatu

# ───────────────────────── identyfikatory ─────────────────────────


def nip_valid(rnd: random.Random) -> str:
    w = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    while True:
        d = [9, 9, 9] + [rnd.randint(0, 9) for _ in range(6)]  # prefiks 999 — nie istnieje urząd skarbowy
        c = sum(a * b for a, b in zip(d, w)) % 11
        if c != 10:
            return "".join(map(str, d)) + str(c)


def regon_valid(rnd: random.Random) -> str:
    w = (8, 9, 2, 3, 4, 5, 6, 7)
    d = [9, 9] + [rnd.randint(0, 9) for _ in range(6)]  # prefiks 99 — nieprawidłowy kod województwa
    c = sum(a * b for a, b in zip(d, w)) % 11 % 10
    return "".join(map(str, d)) + str(c)


# ───────────────────────── czcionki / PDF ─────────────────────────


def _register_fonts() -> None:
    cands = [
        (os.environ.get("FONT_REGULAR"), os.environ.get("FONT_BOLD")),
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ]
    for reg, bold in cands:
        if reg and bold and Path(reg).exists() and Path(bold).exists():
            pdfmetrics.registerFont(TTFont("F", reg))
            pdfmetrics.registerFont(TTFont("F-B", bold))
            pdfmetrics.registerFontFamily("F", normal="F", bold="F-B", italic="F", boldItalic="F-B")
            return
    raise SystemExit("Brak czcionki z polskimi znakami: ustaw FONT_REGULAR i FONT_BOLD (pliki .ttf).")


_register_fonts()
ST = {
    "n": ParagraphStyle("n", fontName="F", fontSize=10, leading=14, spaceAfter=4),
    "h": ParagraphStyle("h", fontName="F-B", fontSize=14, leading=18, spaceAfter=8, spaceBefore=6),
    "h2": ParagraphStyle("h2", fontName="F-B", fontSize=11, leading=15, spaceAfter=4, spaceBefore=8),
    "s": ParagraphStyle("s", fontName="F", fontSize=8, leading=10, textColor=colors.grey),
}


def pl_date(d: date) -> str:
    return d.strftime("%d.%m.%Y") + " r."


def money(x: float) -> str:
    return f"{x:,.2f}".replace(",", " ").replace(".", ",")


def _watermark(canvas, doc):
    canvas.saveState()
    canvas.setFont("F-B", 46)
    canvas.setFillColor(colors.Color(0.8, 0.1, 0.1, alpha=0.10))
    canvas.translate(A4[0] / 2, A4[1] / 2)
    canvas.rotate(35)
    canvas.drawCentredString(0, 0, "DANE FIKCYJNE")
    canvas.restoreState()
    canvas.setFont("F", 7)
    canvas.setFillColor(colors.grey)
    canvas.drawString(20 * mm, 10 * mm, "Dokument syntetyczny wygenerowany na potrzeby testów (HackNation 2026). Wszystkie dane są wymyślone.")
    canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, f"strona {doc.page}")


def build_pdf(flow: list) -> bytes:
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm,
                      bottomMargin=18 * mm, title="DANE FIKCYJNE").build(flow, onFirstPage=_watermark, onLaterPages=_watermark)
    return buf.getvalue()


def P(t: str, s: str = "n") -> Paragraph:
    return Paragraph(t, ST[s])


def kv_table(rows: list[tuple[str, str]], w=(55 * mm, 115 * mm)) -> Table:
    t = Table([[Paragraph(f"<b>{a}</b>", ST["n"]), Paragraph(b, ST["n"])] for a, b in rows], colWidths=w)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def to_scan(pdf: bytes) -> bytes:
    """PDF bez warstwy tekstowej: strona → obraz (szarość, lekki szum i przechył, JPEG)."""
    import pymupdf
    from PIL import Image, ImageFilter

    src = pymupdf.open(stream=pdf, filetype="pdf")
    out = pymupdf.open()
    rnd = random.Random(5)
    for pg in src:
        pix = pg.get_pixmap(dpi=130, colorspace=pymupdf.csGRAY)
        img = Image.frombytes("L", (pix.width, pix.height), pix.samples).rotate(0.7, fillcolor=255, expand=False)
        img = img.filter(ImageFilter.GaussianBlur(0.6))
        px = img.load()
        for _ in range(pix.width * pix.height // 40):
            x, y = rnd.randrange(pix.width), rnd.randrange(pix.height)
            px[x, y] = max(0, min(255, px[x, y] + rnd.randint(-45, 45)))
        b = io.BytesIO()
        img.save(b, "JPEG", quality=55)
        page = out.new_page(width=pg.rect.width, height=pg.rect.height)
        page.insert_image(page.rect, stream=b.getvalue())
    return out.tobytes()


# ───────────────────────── certyfikat i podpis ─────────────────────────


def make_cert(name: str, qualified: bool, slug: str) -> tuple[Path, Path]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    CERT_DIR.mkdir(parents=True, exist_ok=True)
    key_p, cert_p = CERT_DIR / f"{slug}.key.pem", CERT_DIR / f"{slug}.cert.pem"
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subj = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "PL"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "DANE FIKCYJNE - certyfikat testowy"),
        x509.NameAttribute(NameOID.COMMON_NAME, name),
        x509.NameAttribute(NameOID.SERIAL_NUMBER, f"PNOPL-{FAKE_PESEL}"),
    ])
    b = (x509.CertificateBuilder().subject_name(subj).issuer_name(subj).public_key(key.public_key())
         .serial_number(x509.random_serial_number())
         .not_valid_before(datetime(2025, 6, 1, tzinfo=timezone.utc)).not_valid_after(datetime(2030, 6, 1, tzinfo=timezone.utc))
         .add_extension(x509.KeyUsage(True, True, False, False, False, False, False, False, False), critical=True))
    if qualified:  # QCStatements { id-etsi-qcs-QcCompliance 0.4.0.1862.1.1 }
        b = b.add_extension(x509.UnrecognizedExtension(x509.ObjectIdentifier("1.3.6.1.5.5.7.1.3"),
                                                       bytes.fromhex("300A3008060604008E460101")), critical=False)
    cert = b.sign(key, hashes.SHA256())
    key_p.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    cert_p.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return key_p, cert_p


@contextmanager
def frozen_time(dt: datetime):
    import pyhanko.sign.signers.pdf_cms as pc
    import pyhanko.sign.signers.pdf_signer as ps

    class FDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return dt if tz is None else dt.astimezone(tz)

    old = (ps.datetime, pc.datetime)
    ps.datetime = pc.datetime = FDT
    try:
        yield
    finally:
        ps.datetime, pc.datetime = old


def sign_pdf(pdf: bytes, signer_name: str, when: datetime, qualified: bool, slug: str) -> bytes:
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import signers

    key_p, cert_p = make_cert(signer_name, qualified, slug)
    signer = signers.SimpleSigner.load(str(key_p), str(cert_p), key_passphrase=None)
    meta = signers.PdfSignatureMetadata(field_name="Podpis1", reason="Wniesienie odwołania do KIO", location="Polska")
    with frozen_time(when):
        out = signers.PdfSigner(meta, signer=signer).sign_pdf(IncrementalPdfFileWriter(io.BytesIO(pdf)))
    return out.getvalue()


def check_signature(pdf: bytes, expected: datetime) -> None:
    import logging
    logging.disable(logging.CRITICAL)  # walidator loguje „self-signed” — dla certyfikatu testowego to oczekiwane
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature

    sig = PdfFileReader(io.BytesIO(pdf)).embedded_signatures[0]
    st = validate_pdf_signature(sig)
    assert st.intact and st.valid, "podpis nieważny kryptograficznie"
    got = sig.self_reported_timestamp
    assert got and abs((got - expected).total_seconds()) < 2, f"zły czas podpisu {got} != {expected}"


# ───────────────────────── definicje spraw ─────────────────────────


@dataclass
class Person:
    imie: str
    nazwisko: str
    funkcja: str

    @property
    def full(self) -> str:
        return f"{self.imie} {self.nazwisko}"


@dataclass
class Case:
    id: str
    opis: str
    firma: str
    forma: str  # "sp" / "sa"
    domena: str
    ulica: str
    kod: str
    miasto: str
    tel: str
    zarzad: list[Person]
    signer: Person
    signer_w_organie: bool
    typ: str  # Dostawy / Usługi / Roboty budowlane
    przedmiot: str
    zam_nazwa: str
    zam_ulica: str
    zam_kod: str
    zam_miasto: str
    czynnosc: date
    czynnosc_opis: str
    podpis_dt: datetime
    wpis_wniesione: float
    wpis_data: date
    seed: int
    prokurenci: list[Person] = field(default_factory=list)
    skan_przelewu: bool = False
    neutralne_nazwy: bool = False
    zagniezdzony_zip: bool = False
    podfolder: bool = False
    krs: str = ""
    nip: str = ""
    regon: str = ""
    zam_nip: str = ""
    zam_regon: str = ""
    ted: str = ""
    bzp: str = ""

    @property
    def forma_pelna(self) -> str:
        return "Spółka z ograniczoną odpowiedzialnością" if self.forma == "sp" else "Spółka akcyjna"

    @property
    def nazwa_krs(self) -> str:
        return self.firma + (" Spółka z ograniczoną odpowiedzialnością" if self.forma == "sp" else " Spółka Akcyjna")

    @property
    def nazwa(self) -> str:  # tak jak w Zał. C: „BUD-POL Spółka z o.o."
        return self.firma + (" Spółka z o.o." if self.forma == "sp" else " S.A.")

    @property
    def wymagany_wpis(self) -> float:
        return {"Roboty budowlane": 20000.0}.get(self.typ, 15000.0)  # wszystkie sprawy powyżej progów UE

    @property
    def zasady(self) -> str:
        return "Do składania oświadczeń woli w imieniu Spółki upoważniony jest każdy Członek Zarządu samodzielnie"

    @property
    def epuap(self) -> str:
        return "/" + self.domena.split(".")[0].replace("-", "") + "/SkrytkaESP"

    @property
    def email(self) -> str:
        return f"biuro@{self.domena}"


CASES = [
    Case(id="case_01_poprawna", opis="Wszystko poprawne", firma="Trzcinowski Instalacje", forma="sp",
         domena="trzcinowski-instalacje.example", ulica="ul. Lipowa 14/3", kod="40-101", miasto="Katowice", tel="+48 32 555 01 01",
         zarzad=[Person("Jan Paweł", "Dąbrowski", "PREZES ZARZĄDU")], signer=Person("Jan Paweł", "Dąbrowski", "PREZES ZARZĄDU"),
         signer_w_organie=True, typ="Usługi", przedmiot="Utrzymanie czystości w obiektach użyteczności publicznej na terenie gminy",
         zam_nazwa="Gmina Brzozowice Wielkie", zam_ulica="ul. Rynek 1", zam_kod="26-100", zam_miasto="Brzozowice Wielkie",
         czynnosc=date(2025, 12, 30), czynnosc_opis="odrzucenie oferty", podpis_dt=datetime(2026, 1, 8, 9, 14, 21, tzinfo=timezone.utc),
         wpis_wniesione=15000.0, wpis_data=date(2026, 1, 8), seed=1),
    Case(id="case_02_zla_kwota_wpisu", opis="Wpis 7 500 zł zamiast 15 000 zł (powyżej progu UE)", firma="Nordwik Logistyka", forma="sa",
         domena="nordwik-logistyka.example", ulica="ul. Portowa 7", kod="80-001", miasto="Gdańsk", tel="+48 58 555 02 02",
         zarzad=[Person("Ewelina", "Kozłowska-Mazur", "PREZES ZARZĄDU"), Person("Tomasz", "Rutkowski", "CZŁONEK ZARZĄDU")],
         signer=Person("Ewelina", "Kozłowska-Mazur", "PREZES ZARZĄDU"), signer_w_organie=True, typ="Dostawy",
         przedmiot="Dostawa pojazdów specjalistycznych dla jednostek ochrony przeciwpożarowej",
         zam_nazwa="Powiat Zawadzki-Zachodni", zam_ulica="ul. Starostwo 3", zam_kod="47-100", zam_miasto="Zawada Zachodnia",
         czynnosc=date(2026, 1, 12), czynnosc_opis="wybór oferty najkorzystniejszej", podpis_dt=datetime(2026, 1, 21, 12, 2, 40, tzinfo=timezone.utc),
         wpis_wniesione=7500.0, wpis_data=date(2026, 1, 20), seed=2, podfolder=True),
    Case(id="case_03_prokurent_bez_pelnomocnictwa", opis="Podpis prokurenta spoza zarządu, brak pełnomocnictwa", firma="Wiśniewska Budownictwo",
         forma="sp", domena="wisniewska-budownictwo.example", ulica="ul. Mokra 12", kod="00-100", miasto="Warszawa", tel="+48 22 555 03 03",
         zarzad=[Person("Anna", "Wiśniewska", "PREZES ZARZĄDU")], signer=Person("Marek", "Zieliński", "PROKURENT"),
         signer_w_organie=False, prokurenci=[Person("Marek", "Zieliński", "PROKURENT")], typ="Roboty budowlane",
         przedmiot="Przebudowa i rozbudowa budynku szkoły podstawowej wraz z infrastrukturą towarzyszącą",
         zam_nazwa="Gmina Kowalewo Dolne", zam_ulica="ul. Szkolna 2", zam_kod="87-300", zam_miasto="Kowalewo Dolne",
         czynnosc=date(2026, 2, 3), czynnosc_opis="odrzucenie oferty", podpis_dt=datetime(2026, 2, 12, 14, 30, 5, tzinfo=timezone.utc),
         wpis_wniesione=20000.0, wpis_data=date(2026, 2, 11), seed=3),
    Case(id="case_04_termin_w_sobote", opis="Termin upływa w sobotę 24.01.2026, odwołanie wniesione w poniedziałek 26.01.2026", firma="Żurawski Systemy",
         forma="sp", domena="zurawski-systemy.example", ulica="ul. Fabryczna 21", kod="90-001", miasto="Łódź", tel="+48 42 555 04 04",
         zarzad=[Person("Łukasz", "Żurawski", "PREZES ZARZĄDU")], signer=Person("Łukasz", "Żurawski", "PREZES ZARZĄDU"),
         signer_w_organie=True, typ="Usługi", przedmiot="Świadczenie usług wsparcia technicznego systemów informatycznych urzędu",
         zam_nazwa="Urząd Miasta Dębniki Wielkie", zam_ulica="pl. Wolności 5", zam_kod="33-100", zam_miasto="Dębniki Wielkie",
         czynnosc=date(2026, 1, 14), czynnosc_opis="odrzucenie oferty", podpis_dt=datetime(2026, 1, 26, 8, 41, 9, tzinfo=timezone.utc),
         wpis_wniesione=15000.0, wpis_data=date(2026, 1, 23), seed=4, neutralne_nazwy=True, zagniezdzony_zip=True),
    Case(id="case_05_skan_przelewu", opis="Potwierdzenie przelewu jako skan (PDF z obrazem, bez warstwy tekstowej)", firma="Mirosławiec Elektro-Dom",
         forma="sa", domena="miroslawiec-elektro.example", ulica="ul. Słoneczna 9", kod="60-101", miasto="Poznań", tel="+48 61 555 05 05",
         zarzad=[Person("Małgorzata", "Śliwińska", "PREZES ZARZĄDU")], signer=Person("Małgorzata", "Śliwińska", "PREZES ZARZĄDU"),
         signer_w_organie=True, typ="Dostawy", przedmiot="Dostawa urządzeń elektrycznych i osprzętu dla zasobów komunalnych",
         zam_nazwa="Wodociągi i Kanalizacja Górne Łąki Sp. z o.o.", zam_ulica="ul. Wodna 10", zam_kod="62-200", zam_miasto="Górne Łąki",
         czynnosc=date(2026, 2, 17), czynnosc_opis="unieważnienie postępowania", podpis_dt=datetime(2026, 2, 26, 10, 5, 33, tzinfo=timezone.utc),
         wpis_wniesione=15000.0, wpis_data=date(2026, 2, 25), seed=5, skan_przelewu=True),
]

PROGOWE_ART = "10 dni (art. 515 ust. 1 pkt 1 lit. a PZP)"
KRS_BASE = 9000100  # 0009000100+ : powyżej zakresu istniejących numerów KRS


def prep(c: Case, idx: int) -> None:
    rnd = random.Random(c.seed * 7919)
    c.krs = f"{KRS_BASE + idx * 11:010d}"
    c.nip, c.regon = nip_valid(rnd), regon_valid(rnd)
    c.zam_nip, c.zam_regon = nip_valid(rnd), regon_valid(rnd)
    n = 480000 + rnd.randint(1000, 9999)
    c.ted, c.bzp = f"{n}-2025", f"2025/BZP 00{n}/01"


# ───────────────────────── terminy (niezależnie od rules.py) ─────────────────────────


def deadline(c: Case, shift: bool = True) -> date:
    d = c.czynnosc + timedelta(days=10)  # powyżej progów UE, komunikacja elektroniczna
    while shift and d.weekday() >= 5:  # w danych brak świąt w okolicy terminów (sprawdzane asercją)
        d += timedelta(days=1)
    return d


# ───────────────────────── dokumenty ─────────────────────────


def doc_odwolanie(c: Case) -> bytes:
    sig = c.signer
    f = [P("ODWOŁANIE", "h"),
         P("wnoszone do Prezesa Krajowej Izby Odwoławczej za pośrednictwem Zamawiającego"),
         P("Odwołujący", "h2"),
         kv_table([("Nazwa", c.nazwa), ("Adres", f"{c.ulica}, {c.kod} {c.miasto}"), ("NIP", c.nip), ("REGON", c.regon),
                   ("KRS", c.krs), ("E-mail", c.email), ("Telefon", c.tel), ("Adres do doręczeń (ePUAP)", c.epuap)]),
         P("Zamawiający", "h2"),
         kv_table([("Nazwa", c.zam_nazwa), ("Adres", f"{c.zam_ulica}, {c.zam_kod} {c.zam_miasto}"), ("NIP", c.zam_nip)]),
         P("Postępowanie", "h2"),
         P(f"Dotyczy postępowania o udzielenie zamówienia publicznego: <b>{c.przedmiot}</b>. Rodzaj zamówienia: {c.typ.lower()}. "
           f"Tryb: przetarg nieograniczony. Wartość zamówienia przekracza progi unijne. Ogłoszenie o zamówieniu opublikowano w BZP pod numerem "
           f"{c.bzp} oraz w Dzienniku Urzędowym Unii Europejskiej pod numerem {c.ted}."),
         P("Zaskarżona czynność", "h2"),
         P(f"Odwołanie dotyczy czynności Zamawiającego polegającej na: <b>{c.czynnosc_opis}</b>. Informację o czynności Zamawiający przekazał "
           f"drogą elektroniczną w dniu {pl_date(c.czynnosc)}"),
         P("Zarzuty", "h2"),
         P("1. Naruszenie art. 226 ust. 1 pkt 5 ustawy Pzp przez błędne uznanie, że oferta Odwołującego jest niezgodna z warunkami zamówienia."),
         P("2. Naruszenie art. 16 pkt 1 ustawy Pzp przez prowadzenie postępowania w sposób naruszający zasadę uczciwej konkurencji "
           "i równego traktowania wykonawców."),
         P("Żądania", "h2"),
         P(f"Odwołujący wnosi o uwzględnienie odwołania oraz nakazanie Zamawiającemu unieważnienia czynności: {c.czynnosc_opis}, "
           "a następnie powtórzenia badania i oceny ofert."),
         P("Okoliczności faktyczne i prawne", "h2"),
         P("Odwołujący złożył ofertę w terminie, spełniając warunki udziału w postępowaniu. Zamawiający w uzasadnieniu czynności wskazał, że "
           "treść oferty nie odpowiada wymaganiom specyfikacji warunków zamówienia, nie wskazując, które z wymagań miałoby nie być spełnione. "
           "Takie uzasadnienie nie pozwala na weryfikację zasadności czynności i narusza zasady przejrzystości postępowania. Odwołujący "
           "posiada interes w uzyskaniu zamówienia i może ponieść szkodę w postaci utraty możliwości jego uzyskania."),
         P("Wpis i przekazanie kopii", "h2"),
         P(f"Wpis od odwołania w wysokości {money(c.wpis_wniesione)} zł uiszczono przelewem w dniu {pl_date(c.wpis_data)} "
           f"Kopię odwołania przekazano Zamawiającemu w dniu {pl_date(c.podpis_dt.date())} drogą elektroniczną."),
         P("Załączniki", "h2"),
         P("1. Odpis aktualny z KRS Odwołującego. 2. Potwierdzenie przelewu wpisu. 3. Dowód przekazania kopii odwołania Zamawiającemu."
           + (" Pełnomocnictwo: brak załącznika." if not c.signer_w_organie else "")),
         Spacer(1, 12),
         P(f"{c.miasto}, dnia {pl_date(c.podpis_dt.date())}"),
         P(f"Podpisano elektronicznie: {sig.full}, {sig.funkcja.lower()}"),
         ]
    return build_pdf(f)


def doc_krs(c: Case) -> bytes:
    stan = c.podpis_dt.date() - timedelta(days=1)
    f = [P("ODPIS AKTUALNY z Rejestru Przedsiębiorców Krajowego Rejestru Sądowego", "h"),
         P("(WYDRUK TESTOWY — DANE FIKCYJNE, numer KRS nie istnieje w rejestrze)", "s"),
         kv_table([("Numer KRS", c.krs), ("Stan na dzień", pl_date(stan))]),
         P("Dział 1", "h2"),
         kv_table([("1. Oznaczenie formy prawnej", c.forma_pelna), ("2. Numer REGON / NIP", f"REGON: {c.regon}, NIP: {c.nip}"),
                   ("3. Firma", c.nazwa_krs),
                   ("4. Siedziba i adres", f"miejscowość {c.miasto}, "
                                           f"{c.ulica}, {c.kod} {c.miasto}"),
                   ("5. Adres poczty elektronicznej", c.email)]),
         PageBreak(),
         P("Dział 2", "h2"),
         kv_table([("1. Nazwa organu uprawnionego do reprezentacji", "ZARZĄD"), ("2. Sposób reprezentacji", c.zasady)]),
         P("Skład organu", "h2")]
    rows = [["Lp.", "Nazwisko", "Imiona", "Funkcja w organie"]]
    for i, p in enumerate(c.zarzad, 1):
        rows.append([str(i), p.nazwisko, p.imie, p.funkcja])
    t = Table(rows, colWidths=[12 * mm, 55 * mm, 45 * mm, 55 * mm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("FONTNAME", (0, 0), (-1, -1), "F"), ("FONTSIZE", (0, 0), (-1, -1), 9)]))
    f.append(t)
    f.append(P("Prokurenci", "h2"))
    if c.prokurenci:
        for p in c.prokurenci:
            f.append(P(f"{p.nazwisko} {p.imie} — prokura samodzielna"))
    else:
        f.append(P("Brak wpisanych prokurentów."))
    return build_pdf(f)


def doc_przelew(c: Case) -> bytes:
    f = [P("Bank Przykładowy S.A. (dane fikcyjne)", "h"),
         P("POTWIERDZENIE WYKONANIA PRZELEWU KRAJOWEGO", "h2"),
         kv_table([("Status", "Zrealizowany"), ("Data operacji", pl_date(c.wpis_data)),
                   ("Nadawca", f"{c.nazwa}, {c.ulica}, {c.kod} {c.miasto}"),
                   ("Odbiorca", "Urząd Zamówień Publicznych — wpis od odwołania"),
                   ("Rachunek odbiorcy", "00 0000 0000 0000 0000 0000 0000 (numer fikcyjny)"),
                   ("Kwota", f"{money(c.wpis_wniesione)} PLN"),
                   ("Tytuł przelewu", f"Wpis od odwołania — postępowanie {c.bzp} — {c.nazwa}")])]
    return build_pdf(f)


def doc_kopia(c: Case) -> bytes:
    t = datetime.combine(c.podpis_dt.date(), datetime.min.time()).replace(hour=9, minute=14)
    f = [P("Wydruk wiadomości e-mail (dane fikcyjne)", "h"),
         kv_table([("Od", c.email), ("Do", f"zamowienia@{c.zam_miasto.lower().replace(' ', '-')}.example"),
                   ("Data wysłania", f"{pl_date(t.date())}, godz. {t:%H:%M}"),
                   ("Temat", f"Kopia odwołania — postępowanie {c.bzp}"),
                   ("Załączniki", "Odwolanie_podpisane.pdf (kopia odwołania wniesionego do Prezesa KIO)")]),
         Spacer(1, 8),
         P("Niniejszym przekazuję Zamawiającemu kopię odwołania wniesionego do Prezesa Krajowej Izby Odwoławczej, zgodnie z obowiązkiem "
           "przekazania kopii odwołania Zamawiającemu."),
         P(f"Wiadomość wysłano w dniu {pl_date(t.date())}. Potwierdzenie wysłania: wysłano do serwera pocztowego odbiorcy.")]
    return build_pdf(f)


# ───────────────────────── wzorce ─────────────────────────


def ground_truth(c: Case) -> dict:
    dl = deadline(c)
    sig_name = c.signer.full
    qualified = c.id in QUALIFIED_SIM_CASES
    braki = (c.wpis_wniesione != c.wymagany_wpis) or (not c.signer_w_organie)
    a = {
        "naglowek.sygnatura": None,
        "naglowek.braki_formalne": bool(braki),
        "informacje_ogolne.zamowienie": f"{c.typ}: {c.przedmiot}",
        "informacje_ogolne.tryb_postepowania": "Przetarg nieograniczony",
        "informacje_ogolne.publikator": f"TED powyżej progu UE: {c.ted}",
        "informacje_ogolne.czynnosc": f"Czynność z dnia {c.czynnosc.isoformat()}: {c.czynnosc_opis}",
        "informacje_ogolne.termin_na_wniesienie": dl.isoformat(),
        "informacje_ogolne.wniesione_w_terminie": c.podpis_dt.date() <= dl,
        "informacje_ogolne.wpis.wymagane": c.wymagany_wpis,
        "informacje_ogolne.wpis.wniesione": c.wpis_wniesione,
        "informacje_ogolne.wpis.data_wplaty": c.wpis_data.isoformat(),
        "informacje_ogolne.wpis.prawidlowy": abs(c.wpis_wniesione - c.wymagany_wpis) < 0.01,
        "odwolujacy.konsorcjum": False,
        "odwolujacy.nazwa": c.nazwa,
        "odwolujacy.forma_prawna": c.forma_pelna,
        "odwolujacy.adres.ulica": c.ulica,
        "odwolujacy.adres.kod_pocztowy": c.kod,
        "odwolujacy.adres.miasto": c.miasto,
        "odwolujacy.email": c.email,
        "odwolujacy.telefon": c.tel,
        "odwolujacy.nip": c.nip,
        "odwolujacy.regon": c.regon,
        "odwolujacy.krs": c.krs,
        "odwolujacy.bae": None,
        "odwolujacy.epuap": c.epuap,
        "reprezentacja.zasady": c.zasady,
        "reprezentacja.organ": "ZARZĄD",
        "reprezentacja.podpisujacy.imie_nazwisko": sig_name,
        "reprezentacja.podpisujacy.typ_podpisu": "kwalifikowany" if qualified else "niekwalifikowany",
        "reprezentacja.podpisujacy.data_podpisu": c.podpis_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reprezentacja.podpisujacy.podpis_wazny": True,
        "reprezentacja.pelnomocnictwo_wymagane": not c.signer_w_organie,
        "zamawiajacy.nazwa": c.zam_nazwa,
        "zamawiajacy.adres.ulica": c.zam_ulica,
        "zamawiajacy.adres.miasto": c.zam_miasto,
        "zamawiajacy.nip": c.zam_nip,
        "weryfikacja.numer_ogloszenia": c.ted,
        "weryfikacja.data_czynnosci": c.czynnosc.isoformat(),
        "weryfikacja.termin_ustawowy": PROGOWE_ART,
        "weryfikacja.termin_wyliczony": dl.isoformat(),
        "weryfikacja.wniesione_w_terminie": c.podpis_dt.date() <= dl,
        "weryfikacja.wpis_prawidlowy": abs(c.wpis_wniesione - c.wymagany_wpis) < 0.01,
        "weryfikacja.dowod_przekazania_kopii": True,
        "weryfikacja.braki_formalne": bool(braki),
    }
    return {"version": 2, "min_similarity": 0.55, "assert": a}


def expected_rules(c: Case) -> dict:
    q = c.id in QUALIFIED_SIM_CASES
    S, N, D, W = "spełnione", "niespełnione", "nie_dotyczy", "do_weryfikacji_ręcznej"
    wpis_ok = abs(c.wpis_wniesione - c.wymagany_wpis) < 0.01
    r = {"F1": S, "F2": S if wpis_ok else N, "F3": S, "F4": S if q else W,
         "F5": S if c.signer_w_organie else N, "F6": D if c.signer_w_organie else N,
         "F7": D if c.signer_w_organie else W, "F8": S, "F9": S, "F10": S, "F11": S, "F12": S, "F13": D}
    notes = {"F1": "case_04: S tylko przy shift_weekend_holiday=true (termin 24.01.2026 = sobota → 26.01.2026)" if c.id.startswith("case_04")
             else "", "F4": "certyfikat samopodpisany, niekwalifikowany; zaufania nie da się ustalić offline → ręcznie" if not q else "",
             "F13": "postępowanie wszczęte przed 13.03.2026",
             "F2": "wymagane 15 000 zł (powyżej progu UE), wniesiono 7 500 zł" if not wpis_ok else "",
             "F3": "", "F7": "brak pełnomocnictwa — nie ma czego opłacić" if not c.signer_w_organie else ""}
    return {"case_id": c.id, "opis": c.opis, "shift_weekend_holiday": True, "kryteria": r,
            "notatki": {k: v for k, v in notes.items() if v},
            "uwagi": ["Skan potwierdzenia przelewu: oczekiwana flaga jakości OCR w audit_trail"] if c.skan_przelewu else []}


def krs_mock(c: Case) -> dict:
    def osoba(p: Person) -> dict:
        im = p.imie.split()
        return {"nazwisko": {"nazwiskoICzlon": p.nazwisko}, "imiona": {"imie": im[0], **({"imieDrugie": im[1]} if len(im) > 1 else {})}}

    street, nr = c.ulica.replace("ul. ", "").rsplit(" ", 1)
    nrd, _, nrl = nr.partition("/")
    return {"odpis": {"rodzaj": "Aktualny", "naglowekA": {"rejestr": "RejP", "numerKRS": c.krs, "stanZDnia": (c.podpis_dt.date() - timedelta(days=1)).strftime("%d.%m.%Y")},
            "dane": {"dzial1": {"danePodmiotu": {"formaPrawna": c.forma_pelna.upper(), "identyfikatory": {"regon": c.regon, "nip": c.nip},
                                                 "nazwa": c.nazwa_krs.upper()},
                                "siedzibaIAdres": {"adres": {"ulica": f"ul. {street}", "nrDomu": nrd, **({"nrLokalu": nrl} if nrl else {}),
                                                              "kodPocztowy": c.kod, "miejscowosc": c.miasto, "kraj": "POLSKA"}},
                                "adresStronyInternetowej": None},
                     "dzial2": {"reprezentacja": {"nazwaOrganu": "ZARZĄD", "sposobReprezentacji": c.zasady,
                                                  "sklad": [{**osoba(p), "funkcjaWOrganie": p.funkcja} for p in c.zarzad]},
                                "prokurenci": [{**osoba(p), "rodzajProkury": "SAMODZIELNA"} for p in c.prokurenci]}}},
            "_uwaga": "DANE FIKCYJNE — mock KRS API (kształt zbliżony do prawdziwego; do weryfikacji z żywym API)"}


# ───────────────────────── budowa paczek ─────────────────────────


def build_case(c: Case, idx: int) -> None:
    prep(c, idx)
    dl_raw = c.czynnosc + timedelta(days=10)
    assert c.podpis_dt.date() <= deadline(c)
    for d in (c.czynnosc, dl_raw, deadline(c), c.podpis_dt.date(), c.wpis_data):  # brak świąt stałych w okolicy terminów
        assert (d.month, d.day) not in {(1, 1), (1, 6), (5, 1), (5, 3), (12, 25), (12, 26), (11, 1), (11, 11)}, f"święto: {d}"
    qualified = c.id in QUALIFIED_SIM_CASES
    odw = doc_odwolanie(c)
    odw = sign_pdf(odw, c.signer.full, c.podpis_dt, qualified, c.id)
    check_signature(odw, c.podpis_dt)
    przelew = doc_przelew(c)
    if c.skan_przelewu:
        przelew = to_scan(przelew)
    slug = c.firma.split()[0]
    if c.neutralne_nazwy:
        names = {"odw": "pismo.pdf", "krs": "wydruk_1.pdf", "przelew": "wydruk_2.pdf", "kopia": "wydruk_3.pdf"}
    else:
        names = {"odw": f"Odwolanie_{slug}_{c.podpis_dt:%d.%m.%Y}.pdf", "krs": f"Odpis_Aktualny_KRS_{c.krs}.pdf",
                 "przelew": "Potwierdzenie_przelewu_wpisu.pdf" if not c.skan_przelewu else "Potwierdzenie_przelewu_skan.pdf",
                 "kopia": "Dowod_przekazania_kopii.pdf"}
    prefix = "zalaczniki/" if c.podfolder else ""
    OUT.mkdir(parents=True, exist_ok=True)
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(names["odw"], odw)
        rest = {names["krs"]: doc_krs(c), names["przelew"]: przelew, names["kopia"]: doc_kopia(c)}
        if c.zagniezdzony_zip:
            inner = io.BytesIO()
            with zipfile.ZipFile(inner, "w", zipfile.ZIP_DEFLATED) as zi:
                for k, v in rest.items():
                    zi.writestr(k, v)
            z.writestr("zalaczniki.zip", inner.getvalue())
        else:
            for k, v in rest.items():
                z.writestr(prefix + k, v)
    (OUT / f"{c.id}.zip").write_bytes(zbuf.getvalue())
    gt_dir = OUT / "ground_truth"
    gt_dir.mkdir(exist_ok=True)
    dump = dict(allow_unicode=True, sort_keys=False, default_flow_style=False, width=1000)
    (gt_dir / f"{c.id}.yaml").write_text(f"# {c.id}: {c.opis}\n# DANE FIKCYJNE. Założenie: shift_weekend_holiday=true\n" + yaml.safe_dump(ground_truth(c), **dump), encoding="utf-8")
    (gt_dir / f"{c.id}.rules.yaml").write_text(yaml.safe_dump(expected_rules(c), **dump), encoding="utf-8")
    mock_dir = OUT / "krs_mock"
    mock_dir.mkdir(exist_ok=True)
    (mock_dir / f"{c.krs}.json").write_text(json.dumps(krs_mock(c), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{c.id:42s} zip={len(zbuf.getvalue()) // 1024:4d} KB  KRS={c.krs} NIP={c.nip} podpis={c.podpis_dt:%Y-%m-%d} termin={deadline(c)}")


def main() -> None:
    for i, c in enumerate(CASES):
        build_case(c, i)
    (OUT / "README.md").write_text("# Dane syntetyczne — FIKCYJNE\n\nWszystkie firmy, osoby, numery i dokumenty w tym katalogu są wymyślone "
                                   "(wygenerowane przez `scripts/make_synthetic_cases.py`). Nie są to prawdziwe sprawy.\n", encoding="utf-8")


if __name__ == "__main__":
    main()
