"""Harald's Messengers: the game brain.

Runs the whole visitor flow: cards (NFC or keyboard), challenge, story screen, badge.
Every part is optional: with no badge and no NFC reader it still runs on keyboard fakes.

Setup (once, inside the same venv as badge_bridge.py):
    pip install aiohttp bleak pyscard

Run (badge_bridge.py and stories.json must be in the same folder):
    python game.py
Then open http://localhost:8000 in a browser and press F11 for full screen.

Keys (press them in the browser window):
    T = Tokyo card tapped      L = London card tapped     B = blank card tapped
    S = challenge solved       F = challenge failed
    K = next language          R = reset for a new visitor

Hook for the camera puzzles: where a puzzle prints UNLOCKED, add
    import urllib.request
    urllib.request.urlopen("http://localhost:8000/solved")
"""

import asyncio
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

from aiohttp import web

try:
    from badge_bridge import Badge
except Exception as exc:  # bleak missing or badge_bridge.py not next to this file
    print(f"Badge support off: {exc}")
    Badge = None

HERE = Path(__file__).parent
PORT = 8000
CARDS_FILE = HERE / "cards.json"      # which NFC tag is which card (filled in by the game)
STORIES_FILE = HERE / "stories.json"  # the story of each copy, per language

LANGS = ["en", "da", "de", "it", "pt", "fa"]
LANG_NAMES = {"en": "English", "da": "Dansk", "de": "Deutsch", "it": "Italiano",
              "pt": "Português", "fa": "فارسی"}
RTL_LANGS = {"fa"}   # right-to-left languages
VERSION = "v10 (Tokyo: become the picture)"

# station -> (city name, badge stage number)
# Every copy a card can be addressed to: key -> (name on the card/stone, keyboard fake key)
STATIONS = {
    "tokyo": ("TOKYO", "t"), "london": ("LONDON", "l"), "paris": ("PARIS", "p"),
    "rouen": ("ROUEN", "o"), "utrecht": ("UTRECHT", "u"), "yorba": ("YORBA LINDA", "y"),
    "varde": ("VARDE", "v"), "hvidovre": ("HVIDOVRE", "h"), "viborg": ("VIBORG", "i"),
    "sanfrancisco": ("SAN FRANCISCO", "x"),
}
CHALLENGES = {"tokyo", "london"}   # these cities have a camera challenge; the others go straight to the story
LOST = {"sanfrancisco"}            # the copy that disappeared: its message never arrives
# Hot and cold: the badge reports the signal strength (RSSI) of the nearest station beacon.
# Calibrate with the numbers in the grey status line at the bottom of the screen:
PROX_COLD = -85   # RSSI when you stand far away (meter empty)
PROX_HOT = -50    # RSSI when the badge is right at the station (meter full)
MESSAGES_PER_RUN = 2               # sealed cards in each visitor's pouch (any cities), then the blank card

# city names on screen, per language (the stone and the cards keep the English spelling)
_SAME = {"paris": "Paris", "utrecht": "Utrecht", "varde": "Varde", "hvidovre": "Hvidovre", "viborg": "Viborg",
         "rouen": "Rouen", "yorba": "Yorba Linda"}
CITY = {
    "tokyo": {"en": "Tokyo", "da": "Tokyo", "de": "Tokio", "it": "Tokyo", "pt": "Tóquio", "fa": "توکیو"},
    "london": {"en": "London", "da": "London", "de": "London", "it": "Londra", "pt": "Londres", "fa": "لندن"},
    "sanfrancisco": {"en": "San Francisco", "da": "San Francisco", "de": "San Francisco",
                     "it": "San Francisco", "pt": "São Francisco", "fa": "سان فرانسیسکو"},
}
_FA = {"paris": "پاریس", "rouen": "روئن", "utrecht": "اوترخت", "yorba": "یوربا لیندا",
       "varde": "فارده", "hvidovre": "ویدووره", "viborg": "ویبورگ"}
for _k, _v in _SAME.items():
    CITY[_k] = {"en": _v, "da": _v, "de": _v, "it": _v, "pt": _v, "fa": _FA[_k]}
CITY["paris"]["it"] = "Parigi"


# If these files are in this folder, the game starts them when the card is tapped.
# Set AUTO_LAUNCH to False to start the puzzles by hand.
AUTO_LAUNCH = True
PUZZLES = {"tokyo": "puzzle_become_picture.py", "london": "puzzle_row_longship.py"}

T = {
    "en": {
        "prox_title": "A stone is near",
        "prox_levels": ["Cold", "Warmer", "Hot", "You are there. Tap your card."],
        "eyebrow": "Message {n} of {total}",
        "photo_caption": "The {city} copy today",
        "brand": "Harald's Messengers",
        "welcome_title": "Welcome, messenger",
        "welcome_body": "Press the button on your badge to choose your language. "
                        "Then decode your first card and tap it on the reader.",
        "accepted": "Message for {city} accepted",
        "ch_tokyo": "Prove you are the messenger. In Tokyo only the pictures were copied, so become the picture: spread your arms wide like the figure on the stone, and hold still for 3 seconds.",
        "ch_london": "Prove you are the messenger. Row the longship: hands down by your knees, "
                     "then pull them up to your chest. Three strokes.",
        "delivered": "Message delivered to {city}",
        "next_card": "Decode your next card and tap it on the reader.",
        "next_blank": "One card is left. It is blank. Tap it on the reader.",
        "err_done": "This message was already delivered.",
        "err_left": "You still carry {n} sealed message(s). Deliver them first.",
        "try_again": "Not yet. Try again.",
        "final_title": "The last message is addressed to you",
        "final_body": "Type your name and press Enter.",
        "done_title": "You are the 13th copy",
        "done_body": "Your name, carved in runes.",
        "lost": "The message to {city} never arrived",
        "play_again": "Play again",
        "quit": "Quit",
        "quit_confirm": "Tap again to quit",
    },
    "da": {
        "prox_title": "En sten er nær",
        "prox_levels": ["Koldt", "Varmere", "Varmt", "Du er fremme. Læg dit kort på læseren."],
        "eyebrow": "Besked {n} af {total}",
        "photo_caption": "Kopien i {city} i dag",
        "brand": "Haralds sendebud",
        "welcome_title": "Velkommen, sendebud",
        "welcome_body": "Tryk på knappen på dit badge for at vælge sprog. "
                        "Afkod derefter dit første kort og læg det på læseren.",
        "accepted": "Besked til {city} modtaget",
        "ch_tokyo": "Bevis at du er sendebuddet. I Tokyo blev kun billederne kopieret, så bliv selv billedet: stræk armene ud som figuren på stenen, og hold dem stille i 3 sekunder.",
        "ch_london": "Bevis at du er sendebuddet. Ro langskibet: hænderne ned ved knæene, "
                     "og træk dem op til brystet. Tre tag.",
        "delivered": "Beskeden er leveret til {city}",
        "next_card": "Afkod dit næste kort og læg det på læseren.",
        "next_blank": "Der er ét kort tilbage. Det er blankt. Læg det på læseren.",
        "err_done": "Denne besked er allerede leveret.",
        "err_left": "Du bærer stadig {n} forseglet(e) besked(er). Lever dem først.",
        "try_again": "Ikke endnu. Prøv igen.",
        "final_title": "Den sidste besked er til dig",
        "final_body": "Skriv dit navn og tryk Enter.",
        "done_title": "Du er den 13. kopi",
        "done_body": "Dit navn, ristet i runer.",
        "lost": "Beskeden til {city} nåede aldrig frem",
        "play_again": "Spil igen",
        "quit": "Afslut",
        "quit_confirm": "Tryk igen for at afslutte",
    },
    "de": {
        "prox_title": "Ein Stein ist nah",
        "prox_levels": ["Kalt", "Wärmer", "Heiß", "Du bist da. Lege deine Karte auf."],
        "eyebrow": "Botschaft {n} von {total}",
        "photo_caption": "Die Kopie in {city} heute",
        "brand": "Haralds Boten",
        "welcome_title": "Willkommen, Bote",
        "welcome_body": "Drücke den Knopf an deinem Abzeichen, um deine Sprache zu wählen. "
                        "Entschlüssle dann deine erste Karte und lege sie auf das Lesegerät.",
        "accepted": "Botschaft für {city} angenommen",
        "ch_tokyo": "Beweise, dass du der Bote bist. In Tokio wurden nur die Bilder kopiert, also werde selbst zum Bild: Breite die Arme aus wie die Figur auf dem Stein und halte 3 Sekunden still.",
        "ch_london": "Beweise, dass du der Bote bist. Rudere das Langschiff: Hände runter zu den Knien, "
                     "dann zur Brust hochziehen. Drei Schläge.",
        "delivered": "Botschaft in {city} zugestellt",
        "next_card": "Entschlüssle deine nächste Karte und lege sie auf das Lesegerät.",
        "next_blank": "Eine Karte ist übrig. Sie ist leer. Lege sie auf das Lesegerät.",
        "err_done": "Diese Botschaft wurde schon zugestellt.",
        "err_left": "Du trägst noch {n} versiegelte Botschaft(en). Stelle sie zuerst zu.",
        "try_again": "Noch nicht. Versuch es noch einmal.",
        "final_title": "Die letzte Botschaft ist an dich gerichtet",
        "final_body": "Schreibe deinen Namen und drücke Enter.",
        "done_title": "Du bist die 13. Kopie",
        "done_body": "Dein Name, in Runen geritzt.",
        "lost": "Die Botschaft nach {city} kam nie an",
        "play_again": "Nochmal spielen",
        "quit": "Beenden",
        "quit_confirm": "Zum Beenden nochmal tippen",
    },
    "it": {
        "prox_title": "Una pietra è vicina",
        "prox_levels": ["Freddo", "Fuochino", "Fuoco", "Ci sei. Appoggia la tua carta."],
        "eyebrow": "Messaggio {n} di {total}",
        "photo_caption": "La copia di {city} oggi",
        "brand": "I messaggeri di Harald",
        "welcome_title": "Benvenuto, messaggero",
        "welcome_body": "Premi il pulsante sul tuo badge per scegliere la lingua. "
                        "Poi decifra la prima carta e appoggiala sul lettore.",
        "accepted": "Messaggio per {city} accettato",
        "ch_tokyo": "Dimostra di essere il messaggero. A Tokyo furono copiate solo le immagini, quindi diventa tu l'immagine: apri le braccia come la figura sulla pietra e resta fermo per 3 secondi.",
        "ch_london": "Dimostra di essere il messaggero. Rema sulla nave vichinga: mani giù alle ginocchia, "
                     "poi tirale su fino al petto. Tre colpi di remo.",
        "delivered": "Messaggio consegnato a {city}",
        "next_card": "Decifra la prossima carta e appoggiala sul lettore.",
        "next_blank": "Resta una carta. È bianca. Appoggiala sul lettore.",
        "err_done": "Questo messaggio è già stato consegnato.",
        "err_left": "Porti ancora {n} messaggio/i sigillato/i. Consegnali prima.",
        "try_again": "Non ancora. Riprova.",
        "final_title": "L'ultimo messaggio è indirizzato a te",
        "final_body": "Scrivi il tuo nome e premi Invio.",
        "done_title": "Sei la 13ª copia",
        "done_body": "Il tuo nome, inciso in rune.",
        "lost": "Il messaggio per {city} non è mai arrivato",
        "play_again": "Gioca ancora",
        "quit": "Esci",
        "quit_confirm": "Tocca di nuovo per uscire",
    },
    "pt": {
        "prox_title": "Uma pedra está perto",
        "prox_levels": ["Frio", "Mais quente", "Quente", "Chegou. Encoste o seu cartão."],
        "eyebrow": "Mensagem {n} de {total}",
        "photo_caption": "A cópia de {city} hoje",
        "brand": "Os mensageiros de Harald",
        "welcome_title": "Bem-vindo, mensageiro",
        "welcome_body": "Pressione o botão do seu crachá para escolher o idioma. "
                        "Depois decifre o seu primeiro cartão e encoste-o no leitor.",
        "accepted": "Mensagem para {city} recebida",
        "ch_tokyo": "Prove que é o mensageiro. Em Tóquio só as imagens foram copiadas, por isso torne-se a imagem: abra os braços como a figura na pedra e fique imóvel durante 3 segundos.",
        "ch_london": "Prove que é o mensageiro. Reme o barco viking: mãos em baixo, junto aos joelhos, "
                     "depois puxe-as até ao peito. Três remadas.",
        "delivered": "Mensagem entregue em {city}",
        "next_card": "Decifre o seu próximo cartão e encoste-o no leitor.",
        "next_blank": "Resta um cartão. Está em branco. Encoste-o no leitor.",
        "err_done": "Esta mensagem já foi entregue.",
        "err_left": "Ainda leva {n} mensagem(ns) selada(s). Entregue-as primeiro.",
        "try_again": "Ainda não. Tente outra vez.",
        "final_title": "A última mensagem é para si",
        "final_body": "Escreva o seu nome e prima Enter.",
        "done_title": "É a 13.ª cópia",
        "done_body": "O seu nome, gravado em runas.",
        "lost": "A mensagem para {city} nunca chegou",
        "play_again": "Jogar de novo",
        "quit": "Sair",
        "quit_confirm": "Toque de novo para sair",
    },
    "fa": {
        "prox_title": "سنگی نزدیک است",
        "prox_levels": ["سرد", "گرم‌تر", "داغ", "رسیدی. کارتت را بگذار."],
        "eyebrow": "پیام {n} از {total}",
        "photo_caption": "نسخه {city} امروز",
        "brand": "پیام‌رسانان هارالد",
        "welcome_title": "خوش آمدی، پیام‌رسان",
        "welcome_body": "دکمه روی نشانت را فشار بده تا زبانت را انتخاب کنی. "
                        "سپس اولین کارتت را رمزگشایی کن و روی دستگاه بگذار.",
        "accepted": "پیام برای {city} پذیرفته شد",
        "ch_tokyo": "ثابت کن که پیام‌رسان هستی. در توکیو فقط تصویرها کپی شدند، پس خودت تصویر شو: دست‌هایت را مثل پیکرِ روی سنگ باز کن و ۳ ثانیه بی‌حرکت بمان.",
        "ch_london": "ثابت کن که پیام‌رسان هستی. کشتی وایکینگ را پارو بزن: دست‌ها پایین کنار زانوها، "
                     "سپس آن‌ها را تا سینه بالا بکش. سه بار پارو.",
        "delivered": "پیام به {city} رسید",
        "next_card": "کارت بعدی‌ات را رمزگشایی کن و روی دستگاه بگذار.",
        "next_blank": "یک کارت مانده است. خالی است. آن را روی دستگاه بگذار.",
        "err_done": "این پیام قبلاً تحویل داده شده است.",
        "err_left": "هنوز {n} پیام مهرشده همراه داری. اول آن‌ها را تحویل بده.",
        "try_again": "هنوز نه. دوباره امتحان کن.",
        "final_title": "آخرین پیام برای توست",
        "final_body": "نامت را بنویس و Enter بزن.",
        "done_title": "تو نسخه سیزدهم هستی",
        "done_body": "نامت، حک‌شده با رونیک.",
        "lost": "پیام به {city} هرگز نرسید",
        "play_again": "دوباره بازی کن",
        "quit": "خروج",
        "quit_confirm": "برای خروج دوباره بزن",
    },
}

# Younger Futhark, the rune row used on the Jelling stone. It has only 16 runes,
# so several Latin letters share one rune (for example D and T, or O and U).
RUNES = {
    "a": "ᛅ", "b": "ᛒ", "c": "ᚴ", "d": "ᛏ", "e": "ᛁ", "f": "ᚠ", "g": "ᚴ", "h": "ᚼ",
    "i": "ᛁ", "j": "ᛁ", "k": "ᚴ", "l": "ᛚ", "m": "ᛘ", "n": "ᚾ", "o": "ᚢ", "p": "ᛒ",
    "q": "ᚴ", "r": "ᚱ", "s": "ᛋ", "t": "ᛏ", "u": "ᚢ", "v": "ᚢ", "w": "ᚢ", "x": "ᚴᛋ",
    "y": "ᚢ", "z": "ᛋ", "æ": "ᛅ", "ø": "ᚢ", "å": "ᚢ", "ä": "ᛅ", "ö": "ᚢ", "ü": "ᚢ",
    "é": "ᛁ", "è": "ᛁ", "à": "ᛅ", "ò": "ᚢ", "ù": "ᚢ", "ì": "ᛁ",
    "á": "ᛅ", "â": "ᛅ", "ã": "ᛅ", "ê": "ᛁ", "í": "ᛁ", "î": "ᛁ", "ó": "ᚢ", "ô": "ᚢ",
    "õ": "ᚢ", "ú": "ᚢ", "ç": "ᛋ",
}

# Persian letters, written as the Latin letter that sounds closest, then turned into runes.
PERSIAN = {
    "ا": "a", "آ": "a", "ب": "b", "پ": "p", "ت": "t", "ث": "s", "ج": "j", "چ": "k",
    "ح": "h", "خ": "k", "د": "d", "ذ": "z", "ر": "r", "ز": "z", "ژ": "z", "س": "s",
    "ش": "s", "ص": "s", "ض": "d", "ط": "t", "ظ": "z", "ع": "a", "غ": "g", "ف": "f",
    "ق": "k", "ک": "k", "ك": "k", "گ": "g", "ل": "l", "م": "m", "ن": "n", "و": "v",
    "ه": "h", "ی": "i", "ي": "i", "ئ": "i", "ؤ": "v", "أ": "a", "ة": "h",
}


def to_runes(name):
    text = "".join(PERSIAN.get(c, c) for c in name.lower().strip())
    out = []
    i = 0
    while i < len(text):
        if text[i:i + 2] == "th":
            out.append("ᚦ")
            i += 2
            continue
        ch = text[i]
        if ch in RUNES:
            out.append(RUNES[ch])
        elif ch in " -":
            out.append(" ᛫ ")  # word divider
        i += 1
    return "".join(out)



# Harald's inscription from the Great Jelling Stone (DR 42), written in Younger Futhark.
# It runs around the edge of the stone on the screen, like the red band on the real copies.
_BAND_LATIN = ("haraltr : kunukR : baþ : kaurua : kubl : þausi : aft : kurm : faþur : sin : "
               "auk : aft : þąurui : muþur : sina : sa : haraltr : ias : sąR : uan : tanmaurk : "
               "ala : auk : nuruiak : auk : tani : karþi : kristną")
_BAND_MAP = {"a": "ᛅ", "b": "ᛒ", "f": "ᚠ", "h": "ᚼ", "i": "ᛁ", "k": "ᚴ", "l": "ᛚ", "m": "ᛘ",
             "n": "ᚾ", "r": "ᚱ", "R": "ᛦ", "s": "ᛋ", "t": "ᛏ", "u": "ᚢ", "þ": "ᚦ", "ą": "ᚬ",
             ":": "᛬", " ": ""}
BAND_RUNES = "".join(_BAND_MAP.get(c, c) for c in _BAND_LATIN)


def stone_lines(text):
    """Words of a name or city, each turned into runes, one word per line."""
    return [to_runes(w) for w in text.replace("-", " ").split() if to_runes(w)][:3]


class Game:
    def __init__(self):
        self.badge = None
        self.badge_ok = False
        self.nfc_ok = False
        self.cards = json.loads(CARDS_FILE.read_text()) if CARDS_FILE.exists() else {}
        self.stories = json.loads(STORIES_FILE.read_text(encoding="utf-8")) if STORIES_FILE.exists() else {}
        self.unknown_uid = None
        self.puzzle_proc = None
        self.lang = "en"
        self.last_button = 0.0
        self.reset(tell_badge=False)

    # ---------- state ----------
    def reset(self, tell_badge=True):
        self.phase = "start"      # start, challenge, story, final_name, done
        self.station = None
        self.delivered = []
        self.name = ""
        self.runes = ""
        self.error = ""
        self.error_at = 0.0
        self.prox_station, self.prox_rssi, self.prox_at = None, 0, 0.0
        self.stop_puzzle()
        if tell_badge:
            self.to_badge("RESET")
        print("Reset: ready for a new visitor")

    def t(self, key, **kw):
        return T[self.lang][key].format(**kw)

    # ---------- hot and cold ----------
    def walking(self):
        """True while the visitor is looking for a station (badge should tick)."""
        return self.phase == "start" or (self.phase == "story" and len(self.delivered) < MESSAGES_PER_RUN)

    def badge_message(self, message):
        """Text from the badge, e.g. 'PROX:TOKYO:-63' or 'PROX:NONE'."""
        parts = message.split(":")
        if parts[0] != "PROX":
            print(f"Badge says: {message}")
            return
        station = parts[1].lower() if len(parts) > 1 else "none"
        if station in STATIONS and len(parts) > 2:
            try:
                self.prox_station, self.prox_rssi, self.prox_at = station, int(parts[2]), time.time()
            except ValueError:
                pass
        else:
            self.prox_station = None

    def prox_view(self):
        """The hot and cold meter for the screen, or None."""
        fresh = self.prox_station and time.time() - self.prox_at < 3
        if not fresh or not self.walking() or self.prox_station in self.delivered:
            return None
        heat = (self.prox_rssi - PROX_COLD) / (PROX_HOT - PROX_COLD)
        heat = max(0.0, min(1.0, heat))
        level = 0 if heat < 0.34 else 1 if heat < 0.67 else 2 if heat < 0.92 else 3
        return {"heat": round(heat, 2), "runes": " ".join(stone_lines(STATIONS[self.prox_station][0])),
                "title": self.t("prox_title"), "label": T[self.lang]["prox_levels"][level],
                "raw": f"{self.prox_station} {self.prox_rssi}"}

    def set_error(self, text, buzz=True):
        self.error = text
        self.error_at = time.time()
        if buzz:
            self.to_badge("ERR")

    def view(self):
        """Everything the screen needs, already in the visitor's language."""
        if self.error and time.time() - self.error_at > 4:
            self.error = ""
        title, body, story = "", "", ""
        if self.phase == "start":
            title, body = self.t("welcome_title"), self.t("welcome_body")
        elif self.phase == "challenge":
            city = CITY[self.station][self.lang]
            title, body = self.t("accepted", city=city), self.t("ch_" + self.station)
        elif self.phase == "story":
            city = CITY[self.station][self.lang]
            title = self.t("delivered", city=city)
            if self.station in LOST:
                title = self.t("lost", city=city)
            story = self.stories.get(self.station, {}).get(self.lang) \
                or self.stories.get(self.station, {}).get("en", "")
            body = self.t("next_blank") if len(self.delivered) >= MESSAGES_PER_RUN else self.t("next_card")
        elif self.phase == "final_name":
            title, body = self.t("final_title"), self.t("final_body")
        elif self.phase == "done":
            title, body = self.t("done_title"), self.t("done_body")
        return {
            "phase": self.phase, "lang": self.lang, "station": self.station,
            "langs": [{"code": c, "name": LANG_NAMES[c]} for c in LANGS],
            "title": title, "body": body, "story": story, "error": self.error,
            "delivered": self.delivered, "total": MESSAGES_PER_RUN,
            "name": self.name, "runes": self.runes,
            "badge": self.badge_ok, "nfc": self.nfc_ok, "unknown_uid": self.unknown_uid,
            "play_again": self.t("play_again"), "quit": self.t("quit"),
            "quit_confirm": self.t("quit_confirm"),
            "dir": "rtl" if self.lang in RTL_LANGS else "ltr", "version": VERSION,
            "band": BAND_RUNES, **self.stone_view(),
            "lost": self.phase == "story" and self.station in LOST,
            "photo": self.photo(),
            "eyebrow": self.eyebrow(),
            "prox": self.prox_view(),
            "photo_caption": self.t("photo_caption", city=CITY[self.station][self.lang]) if self.station else "",
        }

    def eyebrow(self):
        """Small line above the title."""
        if self.phase in ("challenge", "story"):
            n = len(self.delivered) + (1 if self.phase == "challenge" else 0)
            return self.t("eyebrow", n=n, total=MESSAGES_PER_RUN)
        return self.t("brand")

    def photo(self):
        """Photo of the real copy (images/<city>.jpg), shown next to its story."""
        if self.phase == "story" and (HERE / "images" / f"{self.station}.jpg").is_file():
            return f"/images/{self.station}.jpg"
        return ""

    def stone_view(self):
        """What is carved in the middle of the stone on the right."""
        if self.phase in ("challenge", "story"):
            city = STATIONS[self.station][0]
            return {"stone": stone_lines(city), "caption": city, "thirteen": False}
        if self.phase == "done":
            return {"stone": stone_lines(self.name), "caption": self.name, "thirteen": True}
        if self.phase == "final_name":
            return {"stone": ["ᛁᚢᚢ"], "caption": "?", "thirteen": True}
        return {"stone": ["ᚼᛅᚱᛅᛚᛏᚱ"], "caption": "Harald", "thirteen": False}

    # ---------- badge ----------
    def to_badge(self, command):
        async def _send():
            try:
                if self.badge is not None and self.badge_ok:
                    await self.badge.send(command)
                else:
                    print(f"[no badge] {command}")
            except Exception as exc:
                print(f"Badge send failed: {exc}")
        try:
            asyncio.get_running_loop().create_task(_send())
        except RuntimeError:
            pass  # called before the loop started

    def next_language(self):
        self.lang = LANGS[(LANGS.index(self.lang) + 1) % len(LANGS)]
        print(f"Language: {self.lang}")

    def badge_button(self):
        """Badge button pressed. Presses closer than 0.6 s count as one,
        because a bouncy button can send two signals for one press."""
        now = time.time()
        if now - self.last_button < 0.6:
            print("Badge button: ignored a double signal")
            return
        self.last_button = now
        self.next_language()

    # ---------- camera puzzles ----------
    def start_puzzle(self, station):
        self.stop_puzzle()
        script = HERE / PUZZLES.get(station, "")
        if AUTO_LAUNCH and script.is_file():
            try:
                self.puzzle_proc = subprocess.Popen([sys.executable, str(script)], cwd=str(HERE))
                print(f"Started {script.name}")
            except Exception as exc:
                print(f"Could not start {script.name}: {exc}")

    def stop_puzzle(self):
        proc = getattr(self, "puzzle_proc", None)
        if proc is not None and proc.poll() is None:
            proc.terminate()
        self.puzzle_proc = None

    # ---------- game events ----------
    def card(self, card):
        """A card was tapped: 'tokyo', 'london' or 'blank'."""
        print(f"Card: {card}")
        if self.phase in ("final_name", "done"):
            return
        if card == "blank":
            left = MESSAGES_PER_RUN - len(self.delivered)
            if left > 0:
                self.set_error(self.t("err_left", n=left))
            else:
                self.stop_puzzle()
                self.phase = "final_name"
            return
        if card not in STATIONS:
            return
        if card in self.delivered:
            self.set_error(self.t("err_done"))
            return
        if len(self.delivered) >= MESSAGES_PER_RUN:
            self.set_error(self.t("next_blank"))
            return
        self.stop_puzzle()
        self.station = card
        if card in CHALLENGES:
            self.phase = "challenge"
            self.start_puzzle(card)
        else:
            self.deliver()

    def solved(self):
        if self.phase != "challenge":
            return
        print(f"Solved: {self.station}")
        self.stop_puzzle()
        self.deliver()

    def deliver(self):
        """The message for self.station is delivered: story on screen, badge lights up."""
        self.delivered.append(self.station)
        self.phase = "story"
        self.to_badge(f"STAGE:{min(len(self.delivered), 2)}")

    def failed(self):
        if self.phase == "challenge":
            self.set_error(self.t("try_again"), buzz=False)

    def set_name(self, name):
        if self.phase != "final_name":
            return
        name = name.strip()[:20]
        runes = to_runes(name)
        if not runes.strip():
            return
        self.name, self.runes = name, runes
        self.phase = "done"
        self.to_badge("STAGE:3")
        print(f"Name: {name} -> {runes}")

    def key(self, key):
        key = key.lower()
        assign = {fake: station for station, (_name, fake) in STATIONS.items()}
        assign["b"] = "blank"
        if key in assign and self.unknown_uid:
            # A new NFC tag was just tapped: this key says which card it is
            self.cards[self.unknown_uid] = assign[key]
            CARDS_FILE.write_text(json.dumps(self.cards, indent=2))
            print(f"Tag {self.unknown_uid} saved as {assign[key]}")
            self.unknown_uid = None
            return
        if key in assign:
            self.card(assign[key])
        elif key == "s":
            self.solved()
        elif key == "f":
            self.failed()
        elif key == "k":
            self.next_language()
        elif key in "1234":
            # fake hot and cold without beacons: 1 = cold ... 4 = at the Tokyo station
            self.badge_message(f"PROX:TOKYO:{[-85, -72, -60, -48][int(key) - 1]}")
        elif key == "0":
            self.badge_message("PROX:NONE")
        elif key == "r":
            self.reset()

    def on_tag(self, uid):
        """Called when the NFC reader sees a tag."""
        card = self.cards.get(uid)
        if card:
            self.unknown_uid = None
            self.card(card)
        else:
            self.unknown_uid = uid
            print(f"New tag {uid}: press a city key or B in the browser to name it")


# ---------- NFC reader (runs in its own thread) ----------
def nfc_loop(loop, game):
    try:
        from smartcard.System import readers
    except ImportError:
        print("NFC off: pyscard is not installed (keyboard fakes still work)")
        return
    last = None
    while True:
        uid = None
        try:
            found = readers()
            game.nfc_ok = bool(found)
        except Exception:
            found = []
            game.nfc_ok = False
        if found:
            try:
                conn = found[0].createConnection()
                conn.connect()
                data, sw1, _sw2 = conn.transmit([0xFF, 0xCA, 0x00, 0x00, 0x00])
                conn.disconnect()
                if sw1 == 0x90:
                    uid = "".join(f"{b:02X}" for b in data)
            except Exception:
                uid = None  # no card on the reader: normal
        if uid and uid != last:
            loop.call_soon_threadsafe(game.on_tag, uid)
        last = uid
        time.sleep(0.3 if found else 2)


# ---------- badge connection (keeps retrying) ----------
async def tracking_loop(game):
    """Tells the badge when to tick (walking to a station) and when to be quiet."""
    while True:
        want = game.walking()
        if game.badge_ok and getattr(game, "tracking_sent", None) != want:
            game.tracking_sent = want
            game.to_badge(f"TRACK:{1 if want else 0}")
        await asyncio.sleep(0.5)


async def badge_loop(game):
    if Badge is None:
        return
    while True:
        connected = game.badge is not None and game.badge.client is not None \
            and game.badge.client.is_connected
        if not connected:
            game.badge_ok = False
            try:
                badge = Badge(on_button=game.badge_button, on_message=game.badge_message)
                await badge.connect(timeout=8.0)
                game.badge = badge
                game.badge_ok = True
                game.tracking_sent = None
            except Exception as exc:
                print(f"Badge not connected ({exc}). Retrying...")
        await asyncio.sleep(4)


# ---------- web server ----------
PAGE_FILE = HERE / "page.html"   # the screen; edit it and just reload the browser


def make_app(game):
    async def index(_request):
        return web.Response(text=PAGE_FILE.read_text(encoding="utf-8"), content_type="text/html",
                            headers={"Cache-Control": "no-store"})

    async def state(_request):
        return web.json_response(game.view())

    async def key(request):
        data = await request.json()
        game.key(str(data.get("key", ""))[:1])
        return web.json_response({"ok": True})

    async def name(request):
        data = await request.json()
        game.set_name(str(data.get("name", "")))
        return web.json_response({"ok": True})

    async def solved(_request):
        game.solved()
        return web.Response(text="ok")

    async def reset(_request):
        game.reset()
        return web.json_response({"ok": True})

    async def failed(_request):
        game.failed()
        return web.Response(text="ok")

    app = web.Application()
    if (HERE / "images").is_dir():
        app.router.add_static("/images", HERE / "images")
    app.add_routes([
        web.get("/", index), web.get("/state", state),
        web.post("/key", key), web.post("/name", name), web.post("/reset", reset),
        web.get("/solved", solved), web.get("/failed", failed),
    ])
    return app


async def main():
    game = Game()
    loop = asyncio.get_running_loop()
    threading.Thread(target=nfc_loop, args=(loop, game), daemon=True).start()
    asyncio.create_task(badge_loop(game))
    asyncio.create_task(tracking_loop(game))
    runner = web.AppRunner(make_app(game))
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    print(f"Game running. Open http://localhost:{PORT} in a browser (F11 = full screen).")
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Stopped")
