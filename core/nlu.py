"""
Простой NLU на основе ключевых слов.
Достаточно для MVP; при необходимости заменить на LLM-based NLU.
"""

from __future__ import annotations
import re
from typing import Optional
import dateparser


# ── Ключевые слова ────────────────────────────────────────────────────────────

_LANG_RU = {"русский", "по-русски", "рус", "русском", "russia", "rus"}
_LANG_KZ = {"казахский", "казакша", "қазақ", "қазақша", "казак", "kaz", "каз"}

_YES = {"да", "ок", "окей", "хорошо", "согласен", "согласна", "верно", "подтверждаю",
        "подходит", "годится", "yes", "иә", "жарайды", "дұрыс", "солай", "болады"}
_NO  = {"нет", "не", "нет нет", "отмена", "отменить", "не хочу", "не подходит",
        "no", "жоқ", "болмайды", "керек емес"}

_APPOINTMENT = {"запись", "записаться", "записать", "прием", "приём", "попасть",
                "к врачу", "врачу", "жазылу", "жазылғым", "жазылайын", "қабылдау"}
_QUESTION    = {"вопрос", "спросить", "узнать", "информация", "помогите",
                "сұрақ", "білгім", "сұрағым"}
_TRANSFER    = {"оператор", "человека", "живого", "сотрудника", "специалиста",
                "operator", "операторға"}
_REPEAT      = {"повторите", "ещё раз", "не слышу", "не понял", "қайтала", "қайтадан"}

_SPECS = {
    "therapist":       ["терапевт"],
    "surgeon":         ["хирург"],
    "cardiologist":    ["кардиолог"],
    "neurologist":     ["невролог", "нейролог"],
    "pediatrician":    ["педиатр"],
    "gynecologist":    ["гинеколог"],
    "urologist":       ["уролог"],
    "ophthalmologist": ["офтальмолог", "окулист", "глазной"],
    "dermatologist":   ["дерматолог"],
    "endocrinologist": ["эндокринолог"],
}


# ── Публичные функции ─────────────────────────────────────────────────────────

def detect_language(text: str) -> Optional[str]:
    """Вернуть 'ru' или 'kz', либо None если не распознано."""
    t = _norm(text)
    if _any_in(t, _LANG_KZ):
        return "kz"
    if _any_in(t, _LANG_RU):
        return "ru"
    return None


def detect_yes_no(text: str) -> Optional[bool]:
    t = _norm(text)
    if _any_in(t, _YES):
        return True
    if _any_in(t, _NO):
        return False
    return None


def detect_intent(text: str) -> str:
    """
    Возможные значения: appointment | question | transfer | repeat | unknown
    """
    t = _norm(text)
    if _any_in(t, _TRANSFER):
        return "transfer"
    if _any_in(t, _APPOINTMENT):
        return "appointment"
    if _any_in(t, _QUESTION):
        return "question"
    if _any_in(t, _REPEAT):
        return "repeat"
    return "unknown"


def detect_specialization(text: str) -> Optional[str]:
    """Вернуть ключ специальности или None."""
    t = _norm(text)
    for key, keywords in _SPECS.items():
        for kw in keywords:
            if kw in t:
                return key
    return None


def detect_date(text: str, languages: list[str] | None = None) -> Optional[str]:
    """
    Распознать дату из текста. Возвращает строку 'YYYY-MM-DD' или None.
    Использует dateparser с поддержкой русского языка.
    """
    langs = languages or ["ru"]
    parsed = dateparser.parse(
        text,
        languages=langs,
        settings={
            "PREFER_DATES_FROM": "future",
            "RETURN_AS_TIMEZONE_AWARE": False,
            "DATE_ORDER": "DMY",
        },
    )
    if parsed:
        return parsed.strftime("%Y-%m-%d")
    return None


def detect_time(text: str) -> Optional[str]:
    """
    Распознать время из текста. Возвращает строку 'HH:MM' или None.
    Поддерживает форматы: «10:30», «десять тридцать», «в 14», «14 часов».
    """
    t = _norm(text)

    # Числовой формат «10:30» или «14.00»
    m = re.search(r'\b(\d{1,2})[:\.](\d{2})\b', t)
    if m:
        h, minute = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= minute <= 59:
            return f"{h:02d}:{minute:02d}"

    # Только часы «в 14», «14 часов»
    m = re.search(r'\b(\d{1,2})\s*(?:час|ч\b)', t)
    if m:
        h = int(m.group(1))
        if 0 <= h <= 23:
            return f"{h:02d}:00"

    # Словесное время (ограниченный набор)
    word_map = {
        "девять": 9, "десять": 10, "одиннадцать": 11, "двенадцать": 12,
        "тринадцать": 13, "четырнадцать": 14, "пятнадцать": 15,
        "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18,
        # kazakh
        "тоғыз": 9, "он": 10, "он бір": 11, "он екі": 12,
    }
    for word, h in word_map.items():
        if word in t:
            # Проверяем наличие минут «тридцать»
            if "тридцать" in t or "отыз" in t:
                return f"{h:02d}:30"
            return f"{h:02d}:00"

    return None


# ── Вспомогательные ───────────────────────────────────────────────────────────

def _norm(text: str) -> str:
    return text.lower().strip()


def _any_in(text: str, words: set) -> bool:
    return any(w in text for w in words)
