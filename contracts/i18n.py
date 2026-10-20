"""Multilingual texts (French / English). Shared by the whole team.

Principle: an agent never writes a sentence directly in one language. It writes a list of
MESSAGES: a key of the catalog + the raw values to put in it, e.g.

    Msg(key="cmp.scale.ok", params={"n_cur": 31, "n_prev": 29})

The catalogs i18n/en.yaml and i18n/fr.yaml hold the sentences with their placeholders. The
SAME message is rendered in any language at display time (API ?lang=fr, Streamlit selector).
English is the CANONICAL language: the plain text fields of the contracts (message, narrative...)
and the audit journal stay in English, so hashes, searches and tests never depend on the reader.

No LLM here on purpose: numbers are formatted by code, so a translation can never change a value.

Placeholders:  {name}         the value as text (a list is joined with ", ")
               {name:kind}    a formatted value, kinds below (French: 1 234,5 and +34,6 %)
    int   integer, no grouping        f0 / f1 / f2 / f3 / f4   fixed decimals, no grouping
    num0  grouped, 0 decimals         num2   grouped, 2 decimals (money)
    auto  num0 if integer else num2   pct / pct0   share 34.6% / 35%     spct   signed +34.6%
    t     the value is a catalog key: rendered in the same language
    msg   the value is a message (or a list of messages): rendered in the same language
    msgs  a list of messages, joined by ", "
"""
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from contracts.common import Contract

LANGS = ("fr", "en")
CANONICAL = "en"                     # language of the stored texts and of the journal
DEFAULT_LANG = "fr"                  # language shown when the reader says nothing
LANGUAGE_NAME = {"fr": "French", "en": "English"}       # what the LLM prompts expect
CATALOG_DIR = Path(__file__).resolve().parent.parent / "i18n"
PLACEHOLDER = re.compile(r"\{(\w+)(?::(\w+))?\}")
NBSP = " "


class Msg(Contract):
    """One sentence (or piece of sentence) to render in any language."""
    key: str
    params: dict[str, Any] = Field(default_factory=dict)


def lang_code(language: str | None) -> str:
    """'fr', 'French', 'français', 'en-US'... -> 'fr' / 'en'. Unknown -> DEFAULT_LANG."""
    if not language:
        return DEFAULT_LANG
    x = language.strip().lower()
    for code, name in LANGUAGE_NAME.items():
        if x.startswith(code) or x == name.lower() or (code == "fr" and x.startswith("fran")):
            return code
    return DEFAULT_LANG


def language_name(language: str | None) -> str:
    return LANGUAGE_NAME[lang_code(language)]


def from_accept_language(header: str | None) -> str | None:
    """First supported language of an HTTP Accept-Language header ('fr-FR,fr;q=0.9,en;q=0.8')."""
    for part in (header or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in LANGS:
            return code
    return None


_FR_WORDS = {"le", "la", "les", "des", "du", "un", "une", "est", "pourquoi", "quoi", "comment", "quel",
             "quelle", "dans", "pour", "par", "sur", "avec", "été", "ce", "cette", "d'où", "vient", "chiffre",
             "comparaison", "et", "au", "aux", "qui", "que", "ont", "a-t-elle", "a-t-il", "combien"}
_EN_WORDS = {"the", "is", "are", "why", "what", "how", "which", "in", "for", "by", "on", "with", "was",
             "were", "this", "that", "where", "does", "did", "from", "come", "number", "comparison",
             "and", "of", "to", "who", "has", "have", "blocked", "much"}


def detect_language(text: str, default: str = DEFAULT_LANG) -> str:
    """French or English, from common words and accents. A short or unclear text -> default."""
    words = re.findall(r"[a-zàâçéèêëîïôûùüÿœ'-]+", text.lower())
    fr = sum(w in _FR_WORDS for w in words) + 2 * len(re.findall(r"[àâçéèêëîïôûùœ]", text.lower()))
    en = sum(w in _EN_WORDS for w in words)
    return "fr" if fr > en else "en" if en > fr else default


# ---- catalogs ---------------------------------------------------------------------------------
def _flatten(tree: dict, prefix: str = "") -> dict[str, str]:
    out = {}
    for k, v in tree.items():
        key = f"{prefix}{k}"
        out.update(_flatten(v, key + ".") if isinstance(v, dict) else {key: str(v)})
    return out


@lru_cache(maxsize=None)
def catalog(lang: str) -> dict[str, str]:
    path = CATALOG_DIR / f"{lang}.yaml"
    return _flatten(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def check_catalogs() -> list[str]:
    """Every key exists in every language, with the same placeholders. [] = all good."""
    problems = []
    cats = {lang: catalog(lang) for lang in LANGS}
    ref = cats[CANONICAL]
    for lang, cat in cats.items():
        for key in ref.keys() - cat.keys():
            problems.append(f"{lang}: missing key '{key}'")
        for key in cat.keys() - ref.keys():
            problems.append(f"{lang}: key '{key}' is not in {CANONICAL}")
        for key in ref.keys() & cat.keys():
            a, b = set(PLACEHOLDER.findall(ref[key])), set(PLACEHOLDER.findall(cat[key]))
            if a != b:
                problems.append(f"{lang}: '{key}' placeholders {sorted(b)} differ from {sorted(a)}")
    return problems


# ---- formatting -----------------------------------------------------------------------------
def _fr_number(text: str) -> str:
    """'1,234.56' -> '1 234,56' (non-breaking space)."""
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", NBSP)


def fmt(value: Any, kind: str | None, lang: str) -> str:
    if kind == "t":
        return render(Msg(key=str(value)), lang)
    if kind == "msg":                              # a nested message (or several, joined by a space)
        return render(value, lang)
    if kind == "msgs":                             # several nested messages, joined by ", "
        return ", ".join(render(m, lang) for m in value)
    if value is None:
        return "n/a" if lang == "en" else "n.d."
    if kind is None:
        return ", ".join(map(str, value)) if isinstance(value, (list, tuple, set)) else str(value)
    v = float(value)
    if kind == "auto":
        kind = "num0" if v.is_integer() else "num2"
    spec = {"int": "{:.0f}", "f0": "{:.0f}", "f1": "{:.1f}", "f2": "{:.2f}", "f4": "{:.4f}",
            "f3": "{:.3f}", "num0": "{:,.0f}", "num2": "{:,.2f}", "pct": "{:.1%}", "pct0": "{:.0%}", "spct": "{:+.1%}"}
    if kind not in spec:
        raise ValueError(f"Unknown placeholder kind '{kind}'")
    text = spec[kind].format(v)
    if lang == "fr":
        text = _fr_number(text)
        if text.endswith("%"):
            text = text[:-1] + NBSP + "%"
    return text


def render(parts: "Msg | list[Msg] | None", lang: str = CANONICAL) -> str:
    """The text of one message, or of several joined by a space, in `lang`."""
    if parts is None:
        return ""
    if isinstance(parts, (Msg, dict)):
        parts = [parts]
    lang = lang if lang in LANGS else DEFAULT_LANG
    out = []
    for m in parts:
        m = m if isinstance(m, Msg) else Msg.model_validate(m)
        template = catalog(lang).get(m.key) or catalog(CANONICAL).get(m.key)
        if template is None:
            raise KeyError(f"Message '{m.key}' is in no catalog (i18n/*.yaml)")
        out.append(PLACEHOLDER.sub(lambda g: fmt(m.params[g.group(1)], g.group(2), lang), template))
    return " ".join(t for t in out if t)


# ---- localizing a whole contract ----------------------------------------------------------------
def localize(obj: Any, lang: str) -> Any:
    """A copy of a contract where every text that has a message version (field X + field X_parts)
    is rendered in `lang`. Works on any contract, nested lists included.
    A text written by the LLM (X_lang set) is kept when it is already in `lang`; otherwise the
    template is shown instead and X_source (if any) becomes "template"."""
    lang = lang if lang in LANGS else DEFAULT_LANG
    if isinstance(obj, list):
        return [localize(x, lang) for x in obj]
    if not isinstance(obj, BaseModel):
        return obj
    update = {}
    fields = type(obj).model_fields
    for name in fields:
        value = getattr(obj, name)
        if isinstance(value, (BaseModel, list)) and not name.endswith("_parts"):
            new = localize(value, lang)
            if new is not value:
                update[name] = new
    for name in fields:
        if not name.endswith("_parts") or not getattr(obj, name):
            continue
        base = name.removesuffix("_parts")
        written_in = getattr(obj, f"{base}_lang", None)
        if written_in is not None and written_in == lang:
            continue                                    # LLM text already in this language
        update[base] = render(getattr(obj, name), lang)
        if written_in is not None:
            update[f"{base}_lang"] = lang
            if f"{base}_source" in fields:
                update[f"{base}_source"] = "template"
    return obj.model_copy(update=update) if update else obj
