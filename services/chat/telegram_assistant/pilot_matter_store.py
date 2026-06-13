from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .archive import sanitize_filename, sha256_file


DRAFT_NOTICE = (
    "Внутренний AI-черновик для адвоката. Требует профессиональной проверки. "
    "Не является консультацией доверителю и не подлежит внешней отправке без human approval."
)

TOOL_REGISTRY = {
    "case_analysis": ("АНАЛИЗ ДЕЛА", "case-analysis"),
    "questions_for_principal": ("ВОПРОСЫ К ДОВЕРИТЕЛЮ", "questions-for-principal"),
    "document_check": ("ПРОВЕРКА ДОКУМЕНТОВ", "document-check"),
    "legal_position": ("ПРАВОВАЯ ПОЗИЦИЯ", "legal-position"),
    "risk_review": ("РИСКИ", "risks"),
    "judge_review": ("ПРОВЕРКА СУДЬЁЙ", "judge-review"),
    "source_check": ("ПРОВЕРКА ИСТОЧНИКОВ", "source-check"),
    "final_summary": ("ФИНАЛЬНАЯ СВОДКА ДЛЯ АДВОКАТА", "final-summary"),
    "save_to_matter": ("СОХРАНИТЬ В ДЕЛО", "save-to-matter"),
    "cancel": ("ОТМЕНА", "cancel"),
}


# ─────────────────────────── rule-based legal analysis ───────────────────────


_DISPUTE_KEYWORDS: list[tuple[str, str]] = [
    ("кредит|долг|займ|заём|задолженност|взыскан|неосновательн", "debt"),
    ("трудов|увольнен|работодател|зарплат|оклад|сокращен|дискриминац", "labor"),
    ("алимент|развод|семейн|супруг|брак|дети|ребёнок|ребенок|опека", "family"),
    ("квартир|аренд|найм|жильё|жилье|недвижимост|собственност|ипотек", "property"),
    ("уголовн|обвинен|следствен|преступлен|подозрева|арест|задержан", "criminal"),
    ("налог|фнс|штраф.*налог|декларац|ндс|ндфл|недоимк", "tax"),
    ("административ|коап|постановлен.*штраф|нарушен.*дтп|дтп", "administrative"),
    ("договор|контракт|соглашен|поставк|подряд|услуг|нарушен.*обязательств", "contract"),
    ("банкротств|несостоятельност|кредитор.*реестр|конкурсн", "bankruptcy"),
    ("корпоратив|устав|акционер|ооо|ао.*спор|доля.*участник", "corporate"),
    ("интеллектуальн|авторск|товарн.*знак|патент", "ip"),
]

_DISPUTE_META: dict[str, dict] = {
    "debt": {
        "label": "взыскание задолженности",
        "law": "ст. 807–819 ГК РФ (займ/кредит), ст. 395 ГК РФ (проценты)",
        "proc": "ГПК РФ (при сумме > 500 тыс. руб. — иск; до 500 тыс. — судебный приказ ст. 122 ГПК)",
        "limitation": "3 года со дня просрочки (ст. 196 ГК РФ)",
        "court": "Мировой судья до 100 тыс. / районный суд свыше 100 тыс.",
        "pretrial": "Претензия рекомендуется; для банков — обязательна (ч. 5 ст. 4 АПК при арбитраже)",
    },
    "labor": {
        "label": "трудовой спор",
        "law": "ТК РФ гл. 60–61; ст. 391–396 ТК РФ",
        "proc": "ГПК РФ — районный суд; КТС как досудебный этап",
        "limitation": "1 мес. по увольнению (ст. 392 ТК РФ); 3 мес. по нарушению прав; 1 год по зарплате",
        "court": "Районный суд по месту работодателя или жительства работника",
        "pretrial": "КТС (комиссия по трудовым спорам) или сразу суд",
    },
    "family": {
        "label": "семейный спор",
        "law": "СК РФ; гл. 13–17 (алименты); гл. 4 (развод); гл. 12 (права детей)",
        "proc": "ГПК РФ — мировой судья (развод без имущества, алименты); районный (дети, имущество)",
        "limitation": "Алименты: бессрочно в период обязанности; раздел имущества — 3 года с момента раздельного проживания",
        "court": "Мировой / районный суд",
        "pretrial": "Соглашение об алиментах у нотариуса (ст. 100 СК РФ)",
    },
    "property": {
        "label": "жилищный/имущественный спор",
        "law": "ЖК РФ; гл. 35–36 ГК РФ (аренда); ст. 209–233 ГК РФ (собственность)",
        "proc": "ГПК РФ — районный суд; при оспаривании регистрации — КАС РФ",
        "limitation": "3 года; по виндикации — 3 года с момента, когда узнал (ст. 196, 200 ГК)",
        "court": "Районный суд по месту нахождения недвижимости",
        "pretrial": "Для аренды — уведомление о расторжении за 3 мес. (ст. 610 ГК)",
    },
    "criminal": {
        "label": "уголовное дело",
        "law": "УК РФ; УПК РФ",
        "proc": "УПК РФ — стадии: возбуждение, расследование, судебное разбирательство",
        "limitation": "Зависит от категории преступления (ст. 78 УК РФ): лёгкое — 2 года, средн. — 6, тяжкое — 10, особо тяжкое — 15",
        "court": "Мировой / районный / областной суд в зависимости от статьи",
        "pretrial": "Следственные действия; обжалование постановлений — ст. 125 УПК РФ",
    },
    "tax": {
        "label": "налоговый спор",
        "law": "НК РФ; гл. 14 (налоговый контроль); гл. 19 (обжалование)",
        "proc": "Обязательный досудебный порядок — ФНС; затем арбитражный суд (ИП/организации) или районный суд (физ. лица)",
        "limitation": "3 года; по недоимке — с даты уплаты",
        "court": "Арбитражный суд (организации), районный суд (физ. лица)",
        "pretrial": "Обязательная апелляционная жалоба в вышестоящий налоговый орган (п. 2 ст. 138 НК РФ)",
    },
    "administrative": {
        "label": "административное дело",
        "law": "КоАП РФ; КАС РФ",
        "proc": "Обжалование постановления — вышестоящий орган или суд (10 дней — ст. 30.3 КоАП)",
        "limitation": "10 дней на обжалование постановления (ст. 30.3 КоАП)",
        "court": "Мировой судья / районный суд",
        "pretrial": "Жалоба в вышестоящий орган или в суд",
    },
    "contract": {
        "label": "договорный спор",
        "law": "ГК РФ гл. 27–29 (договоры); ст. 450–453 (расторжение); ст. 393–406 (ответственность)",
        "proc": "ГПК РФ (физ. лица) / АПК РФ (организации)",
        "limitation": "3 года с момента нарушения (ст. 196, 200 ГК РФ)",
        "court": "Районный суд / арбитражный суд",
        "pretrial": "Претензия — для ИП/организаций обязательна (ч. 5 ст. 4 АПК)",
    },
    "bankruptcy": {
        "label": "банкротство",
        "law": "ФЗ «О несостоятельности (банкротстве)» № 127-ФЗ",
        "proc": "АПК РФ — арбитражный суд; минимальный долг 500 тыс. руб. (организации), 500 тыс. (граждане)",
        "limitation": "Заявление о включении в реестр — 2 мес. с даты публикации",
        "court": "Арбитражный суд по месту нахождения должника",
        "pretrial": "Направление уведомления об обращении в суд за 15 дней (юридические лица)",
    },
    "corporate": {
        "label": "корпоративный спор",
        "law": "ФЗ «Об ООО» № 14-ФЗ; ФЗ «Об АО» № 208-ФЗ; гл. 4 ГК РФ",
        "proc": "АПК РФ — арбитражный суд (ст. 225.1 АПК РФ)",
        "limitation": "3 года (общий); оспаривание крупных сделок — 1 год",
        "court": "Арбитражный суд по месту регистрации общества",
        "pretrial": "Уведомление участников и общества",
    },
    "ip": {
        "label": "спор об интеллектуальной собственности",
        "law": "ГК РФ часть 4 (ст. 1225–1551); ст. 1301, 1515 (ответственность)",
        "proc": "Суд по интеллектуальным правам (организации); районный суд (физ. лица)",
        "limitation": "3 года",
        "court": "СИП (Суд по интеллектуальным правам) / районный суд",
        "pretrial": "Претензия рекомендуется",
    },
    "general": {
        "label": "гражданский спор",
        "law": "ГК РФ",
        "proc": "ГПК РФ",
        "limitation": "3 года (общий, ст. 196 ГК РФ)",
        "court": "Районный суд по месту жительства ответчика",
        "pretrial": "Претензия рекомендуется",
    },
}


def _parse_context(text: str) -> dict:
    """Extract legal context from free-form text."""
    t = text.lower()

    dispute_type = "general"
    for pattern, dtype in _DISPUTE_KEYWORDS:
        if re.search(pattern, t):
            dispute_type = dtype
            break

    amounts = re.findall(
        r"\d[\d\s]*(?:руб(?:лей?|\.)?|тыс(?:яч)?\.?|млн\.?|миллион(?:ов?)?)",
        text, re.IGNORECASE,
    )

    dates = re.findall(
        r"\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}"
        r"|\d{4}\s*год[а-я]*"
        r"|(?:январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр)[а-я]*\s+\d{4}",
        text, re.IGNORECASE,
    )

    has_contract = bool(re.search(r"договор|контракт|соглашен|расписк", t))
    has_payment_docs = bool(re.search(r"платёжн|платежн|квитанц|чек|перевод|выписк", t))
    has_correspondence = bool(re.search(r"претензи|письм|уведомлен|обращал|отвечал|требовал", t))
    has_court_docs = bool(re.search(r"решен[ие].*суд|постановлен|приговор|определен", t))
    has_witnesses = bool(re.search(r"свидетел|показан", t))

    parties = re.findall(r"(?:ООО|АО|ИП|ПАО|НКО)\s+[«\"]?[\w\s]+[»\"]?", text)

    return {
        "dispute_type": dispute_type,
        "meta": _DISPUTE_META.get(dispute_type, _DISPUTE_META["general"]),
        "amounts": amounts[:4],
        "dates": dates[:4],
        "has_contract": has_contract,
        "has_payment_docs": has_payment_docs,
        "has_correspondence": has_correspondence,
        "has_court_docs": has_court_docs,
        "has_witnesses": has_witnesses,
        "parties": parties[:3],
        "word_count": len(text.split()),
    }


def _fmt_list(items: list[str], fallback: str = "не выявлено") -> str:
    return "\n".join(f"• {i}" for i in items) if items else f"• {fallback}"


def _analyse_judge(text: str, ctx: dict) -> str:
    meta = ctx["meta"]
    dtype = ctx["dispute_type"]
    amounts_str = ", ".join(ctx["amounts"]) if ctx["amounts"] else "не указаны"
    dates_str = ", ".join(ctx["dates"]) if ctx["dates"] else "не указаны"

    # Strong points based on available evidence
    strong = []
    if ctx["has_contract"]:
        strong.append("Наличие письменного договора/расписки — суд примет за основу")
    if ctx["has_payment_docs"]:
        strong.append("Платёжные документы — подтверждают факт передачи средств или нарушения")
    if ctx["has_correspondence"]:
        strong.append("Письменное обращение к другой стороне — досудебный порядок соблюдён или частично соблюдён")
    if ctx["has_court_docs"]:
        strong.append("Судебный акт — преюдиция (ст. 61 ГПК РФ / ст. 69 АПК РФ) упрощает доказывание")
    if ctx["amounts"]:
        strong.append(f"Суммы зафиксированы: {amounts_str} — позволяет рассчитать исковые требования")
    if ctx["dates"]:
        strong.append(f"Даты установлены: {dates_str} — сроки исковой давности поддаются проверке")
    if not strong:
        strong.append("Фактические обстоятельства описаны — требуют документального подтверждения")

    # Weak points
    weak = []
    if not ctx["has_contract"] and dtype in ("debt", "contract"):
        weak.append("Нет письменного договора или расписки — суд применит правила доказывания ст. 162 ГК РФ (нельзя ссылаться на свидетелей)")
    if not ctx["has_payment_docs"] and dtype in ("debt", "contract"):
        weak.append("Отсутствуют платёжные документы — факт передачи денег или исполнения не подтверждён")
    if not ctx["has_correspondence"]:
        weak.append("Досудебная претензия не упомянута — суд может оставить иск без рассмотрения (обязательный досудебный порядок для коммерческих споров)")
    if not ctx["dates"]:
        weak.append("Даты событий не указаны — проверка срока исковой давности невозможна")
    if ctx["word_count"] < 50:
        weak.append("Описание ситуации неполное — суд потребует чёткое изложение фактических обстоятельств")
    if not weak:
        weak.append("Явных слабых мест в изложенной позиции не выявлено — требуется документальная проверка")

    # Missing evidence
    missing = []
    if not ctx["has_contract"]:
        missing.append("Письменный договор, расписка или иное основание обязательства")
    if not ctx["has_payment_docs"]:
        missing.append("Платёжные поручения, чеки, банковские выписки, акты приёма-передачи")
    if not ctx["has_correspondence"]:
        missing.append("Претензия с подтверждением вручения (почтовое уведомление, отметка на копии)")
    if dtype == "labor":
        missing.append("Трудовой договор, приказы, расчётный лист, выписка из СНИЛС")
    if dtype == "family":
        missing.append("Свидетельство о браке/разводе, документы на детей, справки о доходах")
    if dtype == "property":
        missing.append("Выписка из ЕГРН, договор купли-продажи/аренды, акт приёма-передачи")
    if not missing:
        missing.append("На основе изложенного перечень документов определить затруднительно — нужно уточнение")

    # Likely court questions
    court_questions = [
        f"Какое основание возникновения обязательства? (договор, закон, деликт)",
        f"Соблюдён ли обязательный досудебный порядок? (претензия, срок ответа)",
        f"Какие конкретно нормы нарушены и каков размер требований?",
        f"Не истёк ли срок исковой давности? (общий — 3 года, ст. 196 ГК РФ)",
    ]
    if dtype == "debt":
        court_questions.append("Подтверждена ли передача денег допустимыми доказательствами (не только свидетелями)?")
    if dtype == "labor":
        court_questions.append("Когда истец узнал о нарушении и не пропущен ли месячный срок (ст. 392 ТК РФ)?")

    # Procedural risks
    proc_risks = [
        f"Исковая давность: {meta['limitation']} — проверить точную дату нарушения",
        f"Подсудность: {meta['court']} — неправильная подсудность → возврат иска",
        f"Досудебный порядок: {meta['pretrial']}",
    ]
    if not ctx["has_correspondence"] and dtype in ("contract", "debt", "tax"):
        proc_risks.append("Риск оставления иска без рассмотрения из-за несоблюдения претензионного порядка")

    # What to strengthen
    strengthen = [
        "Собрать полный пакет документов согласно перечню «Недостающие доказательства»",
        "Направить претензию с уведомлением о вручении (если ещё не направлялась)",
        f"Проверить срок исковой давности: {meta['limitation']}",
        "Рассчитать точную сумму требований, включая неустойку и проценты",
    ]
    if dtype in ("debt", "contract"):
        strengthen.append("Запросить банковскую выписку или нотариальный протокол переписки как дополнительное доказательство")

    lines = [
        "### 🏛️ ПРОВЕРКА СУДЬЁЙ",
        "",
        f"**Предполагаемая категория спора:** {meta['label']}",
        f"**Применимое право:** {meta['law']}",
        f"**Процессуальный закон:** {meta['proc']}",
        f"**Суммы в материалах:** {amounts_str}",
        f"**Даты в материалах:** {dates_str}",
        "",
        "---",
        "",
        "**1. КАК СУД ВИДИТ СПОР**",
        f"Спор квалифицируется как «{meta['label']}». Применимый кодекс: {meta['proc']}.",
        f"Подсудность: {meta['court']}.",
        "",
        "**2. СИЛЬНЫЕ СТОРОНЫ ПОЗИЦИИ**",
        _fmt_list(strong),
        "",
        "**3. СЛАБЫЕ СТОРОНЫ ПОЗИЦИИ**",
        _fmt_list(weak),
        "",
        "**4. НЕДОСТАЮЩИЕ ДОКАЗАТЕЛЬСТВА**",
        _fmt_list(missing),
        "",
        "**5. ВЕРОЯТНЫЕ ВОПРОСЫ СУДА**",
        _fmt_list(court_questions),
        "",
        "**6. ПРОЦЕССУАЛЬНЫЕ РИСКИ**",
        _fmt_list(proc_risks),
        "",
        "**7. ЧТО АДВОКАТУ НУЖНО УСИЛИТЬ**",
        _fmt_list(strengthen),
        "",
        "**8. ПРЕДВАРИТЕЛЬНЫЙ ВЫВОД**",
        (
            "Ситуация требует документального подтверждения изложенных фактов. "
            "До подачи иска — собрать доказательную базу, проверить давность и соблюсти досудебный порядок."
        ),
        "",
        "⚠️ Это аналитический черновик, не судебный акт и не мнение реального судьи.",
    ]
    return "\n".join(lines)


def _calculate_success_probability(ctx: dict) -> tuple[int, int]:
    """
    Returns (base_probability, with_docs_probability) as percentages.
    Simple heuristic: each evidence type adds weight.
    """
    base = 30  # minimum with no evidence
    bonus_with_docs = 0

    if ctx.get("has_contract"):
        base += 20
        bonus_with_docs += 5
    if ctx.get("has_payment_docs"):
        base += 15
        bonus_with_docs += 5
    if ctx.get("has_correspondence"):
        base += 10
        bonus_with_docs += 5
    if ctx.get("has_court_docs"):
        base += 10
        bonus_with_docs += 5
    if ctx.get("dates"):
        base += 5
        bonus_with_docs += 5
    if ctx.get("amounts"):
        base += 5

    # Dispute type modifiers
    dtype = ctx.get("dispute_type", "other")
    if dtype in ("debt", "contract") and ctx.get("has_contract") and ctx.get("has_payment_docs"):
        base += 5
    if dtype == "labor":
        base -= 5  # typically harder without specific docs
    if ctx.get("word_count", 0) < 50:
        base -= 10  # description too short

    base = max(10, min(90, base))
    with_docs = min(95, base + bonus_with_docs + 10)
    return base, with_docs


def _probability_bar(pct: int, total: int = 10) -> str:
    """Render a simple block-character progress bar."""
    filled = round(pct / 100 * total)
    empty = total - filled
    return "█" * filled + "░" * empty + f"  ~{pct}%"


def _analyse_judge_premium(text: str, ctx: dict) -> str:
    """Premium version of _analyse_judge with probability section and cleaner formatting."""
    base_result = _analyse_judge(text, ctx)
    base_pct, with_docs_pct = _calculate_success_probability(ctx)
    meta = ctx["meta"]

    prob_section = "\n".join([
        "",
        "─" * 24,
        "ВЕРОЯТНОСТЬ УСПЕХА",
        "",
        f"Сейчас:        {_probability_bar(base_pct)}",
        f"С документами: {_probability_bar(with_docs_pct)}",
        "",
        f"Оценка: {meta.get('label', 'спор не классифицирован')}",
        "Для уточнения загрузите договор, платёжные документы и переписку.",
    ])

    # Append probability to the end of the base result (before disclaimer)
    disclaimer = "⚠️ Это аналитический черновик, не судебный акт и не мнение реального судьи."
    if disclaimer in base_result:
        base_result = base_result.replace(
            disclaimer,
            prob_section + "\n\n" + disclaimer,
        )
    else:
        base_result += prob_section

    # Premium header replacement
    base_result = base_result.replace(
        "### 🏛️ ПРОВЕРКА СУДЬЁЙ",
        "⚖️ Оценка судьи",
    )
    return base_result


def _analyse_case(text: str, ctx: dict) -> str:
    meta = ctx["meta"]
    amounts_str = ", ".join(ctx["amounts"]) if ctx["amounts"] else "не указаны"
    dates_str = ", ".join(ctx["dates"]) if ctx["dates"] else "не указаны"
    parties_str = ", ".join(ctx["parties"]) if ctx["parties"] else "из текста не извлечены"

    evidence_list = []
    if ctx["has_contract"]:
        evidence_list.append("Договор/расписка — упомянут(а)")
    if ctx["has_payment_docs"]:
        evidence_list.append("Платёжные документы — упомянуты")
    if ctx["has_correspondence"]:
        evidence_list.append("Переписка/претензия — упомянута")
    if ctx["has_court_docs"]:
        evidence_list.append("Судебный акт — упомянут")
    if not evidence_list:
        evidence_list.append("Документы не упомянуты — необходимо уточнение")

    lines = [
        "### 📋 АНАЛИЗ ДЕЛА",
        "",
        f"**Категория:** {meta['label']}",
        f"**Применимое право:** {meta['law']}",
        "",
        "**Стороны (из текста):**",
        f"• {parties_str}",
        "",
        f"**Суммы:** {amounts_str}",
        f"**Даты:** {dates_str}",
        "",
        "**Упомянутые документы:**",
        _fmt_list(evidence_list),
        "",
        "**Правовая квалификация (предварительная):**",
        f"• Спор относится к категории: {meta['label']}",
        f"• Процессуальный закон: {meta['proc']}",
        f"• Срок исковой давности: {meta['limitation']}",
        "",
        "**Что необходимо для полного анализа:**",
        "• Хронология событий с точными датами",
        "• Полный перечень имеющихся документов",
        "• Позиция второй стороны (если известна)",
        "• Желаемый результат (взыскание, расторжение, признание права и т. д.)",
        "",
        "⚠️ Предварительный анализ на основе описания. Требует проверки адвоката.",
    ]
    return "\n".join(lines)


def _analyse_questions(text: str, ctx: dict) -> str:
    dtype = ctx["dispute_type"]

    base_questions = [
        "В какой стране и регионе возник спор? (от этого зависит подсудность)",
        "Когда именно было нарушено право? (для проверки срока исковой давности)",
        "Кто конкретно является сторонами: физические лица, ИП или организации?",
        "Направлялась ли письменная претензия другой стороне? Есть ли подтверждение вручения?",
        "Какой результат вы хотите получить: взыскать деньги, расторгнуть договор, признать право?",
        "Есть ли уже судебные решения по этому делу или смежным спорам?",
    ]

    type_questions: dict[str, list[str]] = {
        "debt": [
            "Есть ли письменный договор займа/кредита или расписка?",
            "Каков точный размер долга, период просрочки и начисленные проценты?",
            "Была ли частичная оплата? Если да — есть ли её документальное подтверждение?",
            "Требовал ли кредитор возврата до этого? Есть ли переписка?",
        ],
        "labor": [
            "Когда именно уволен/нарушены права работника? (срок 1 мес. по ст. 392 ТК РФ)",
            "Есть ли трудовой договор, приказ о приёме/увольнении, расчётный лист?",
            "Обращался ли работник в трудовую инспекцию или прокуратуру?",
            "Есть ли свидетели нарушений? Готовы ли давать показания?",
        ],
        "family": [
            "Есть ли несовершеннолетние дети? Где они проживают?",
            "Требуется ли раздел имущества? Какое имущество нажито в браке?",
            "Есть ли нотариальное соглашение об алиментах?",
            "Каков официальный доход каждой из сторон?",
        ],
        "property": [
            "Зарегистрировано ли право собственности в ЕГРН? Есть ли выписка?",
            "Есть ли договор аренды/купли-продажи с актом приёма-передачи?",
            "Кто и на каком основании занимает спорный объект сейчас?",
            "Есть ли задолженность по коммунальным платежам?",
        ],
        "criminal": [
            "Статус: подозреваемый, обвиняемый или потерпевший?",
            "На какой стадии находится дело (доследственная проверка, следствие, суд)?",
            "Есть ли уже процессуальные документы (постановление о возбуждении, обвинительное заключение)?",
            "Был ли задержан? Применена ли мера пресечения?",
        ],
        "contract": [
            "Что конкретно нарушил контрагент: не заплатил, не поставил, некачественно выполнил?",
            "Предусмотрена ли договором неустойка и в каком размере?",
            "Есть ли акты сдачи-приёмки или накладные?",
            "Обращались ли с претензией? Каков был ответ?",
        ],
    }

    specific = type_questions.get(dtype, [])
    all_questions = base_questions + specific

    lines = ["### ❓ ВОПРОСЫ К ДОВЕРИТЕЛЮ", "", "Для подготовки позиции адвокату необходимо уточнить:", ""]
    for i, q in enumerate(all_questions, 1):
        lines.append(f"{i}. {q}")
    lines += [
        "",
        "**После получения ответов:**",
        "• Запросите оригиналы или заверенные копии всех упомянутых документов",
        "• Составьте хронологию событий с датами",
        "• Определите желаемый результат и реалистичность его достижения",
        "",
        "⚠️ Черновик. Адвокат вправе расширить или сократить перечень вопросов.",
    ]
    return "\n".join(lines)


def _analyse_documents(text: str, ctx: dict) -> str:
    dtype = ctx["dispute_type"]

    # Documents present
    present = []
    if ctx["has_contract"]:
        present.append("Договор/расписка — упомянут(а) в описании ситуации ✓")
    if ctx["has_payment_docs"]:
        present.append("Платёжные документы — упомянуты ✓")
    if ctx["has_correspondence"]:
        present.append("Переписка/претензия — упомянута ✓")
    if ctx["has_court_docs"]:
        present.append("Судебный акт — упомянут ✓")

    # Documents needed by type
    needed_by_type: dict[str, list[str]] = {
        "debt": [
            "Договор займа/кредита или расписка (оригинал)",
            "Банковские выписки о переводе средств",
            "Переписка с должником о возврате долга",
            "Претензия с уведомлением о вручении",
            "Расчёт суммы долга, процентов (ст. 395 ГК), неустойки",
        ],
        "labor": [
            "Трудовой договор со всеми приложениями и доп. соглашениями",
            "Приказ о приёме на работу",
            "Приказ об увольнении (копия для работника)",
            "Расчётный листок / справка о заработке (2-НДФЛ)",
            "Трудовая книжка или сведения СТД-Р",
            "Должностная инструкция (если нарушены обязанности работодателя)",
        ],
        "family": [
            "Свидетельство о браке / расторжении брака",
            "Свидетельства о рождении детей",
            "Справки о доходах обеих сторон",
            "Документы на совместно нажитое имущество",
            "Соглашение об алиментах (если есть)",
        ],
        "property": [
            "Выписка из ЕГРН (актуальная, не старше 30 дней)",
            "Договор купли-продажи или аренды",
            "Акт приёма-передачи недвижимости",
            "Квитанции об оплате ЖКУ",
            "Технический паспорт / кадастровый план",
        ],
        "criminal": [
            "Постановление о возбуждении уголовного дела (копия)",
            "Постановление о привлечении в качестве обвиняемого (если есть)",
            "Протокол задержания / допроса (при наличии)",
            "Документы, опровергающие обвинение (алиби, переписка и т. д.)",
        ],
        "contract": [
            "Договор со всеми приложениями, спецификациями, доп. соглашениями",
            "Акты выполненных работ / сдачи-приёмки (подписанные и неподписанные)",
            "Накладные, счета-фактуры, УПД",
            "Переписка о нарушении и требованиях",
            "Претензия с ответом или без",
            "Расчёт убытков и неустойки",
        ],
    }

    needed = needed_by_type.get(dtype, [
        "Документальное основание возникновения правоотношения",
        "Доказательства нарушения права",
        "Переписка/претензия и ответ другой стороны",
        "Расчёт требований",
    ])

    lines = [
        "### 📄 ПРОВЕРКА ДОКУМЕНТОВ",
        "",
        "**Упомянуты в описании:**",
        _fmt_list(present, fallback="Документы не упомянуты"),
        "",
        f"**Необходимы для дела категории «{ctx['meta']['label']}»:**",
        _fmt_list(needed),
        "",
        "**Общие требования к документам:**",
        "• Оригиналы или нотариально заверенные копии для суда",
        "• Переписка: нотариальный протокол или распечатка с заверением",
        "• Иностранные документы — апостиль + нотариальный перевод",
        "",
        "⚠️ Окончательный перечень документов определяет адвокат после изучения материалов.",
    ]
    return "\n".join(lines)


def _analyse_legal_position(text: str, ctx: dict) -> str:
    meta = ctx["meta"]
    dtype = ctx["dispute_type"]

    basis_by_type: dict[str, list[str]] = {
        "debt": [
            "Основание требования: ст. 807 ГК РФ (договор займа) или ст. 819 ГК РФ (кредит)",
            "Ответственность за просрочку: ст. 395 ГК РФ (проценты за пользование чужими деньгами)",
            "Взыскание неустойки: договорная или законная (ст. 395 ГК РФ)",
            "При отсутствии договора: ст. 1102 ГК РФ (неосновательное обогащение)",
        ],
        "labor": [
            "Основание восстановления/выплат: ст. 394 ТК РФ",
            "Компенсация за вынужденный прогул: ст. 394 ТК РФ",
            "Компенсация морального вреда: ст. 237 ТК РФ",
            "При задержке зарплаты: ст. 236 ТК РФ (проценты 1/150 ключевой ставки в день)",
        ],
        "family": [
            "Алименты на детей: ст. 81 СК РФ (¼ – 1 ребёнок, ⅓ – двое, ½ – трое и более)",
            "Раздел совместного имущества: ст. 38–39 СК РФ (равные доли по умолчанию)",
            "Определение места жительства детей: ст. 65 СК РФ",
        ],
        "property": [
            "Истребование имущества из незаконного владения: ст. 301 ГК РФ (виндикация)",
            "Устранение нарушений права собственности: ст. 304 ГК РФ (негаторный иск)",
            "Расторжение договора аренды: ст. 619 ГК РФ",
        ],
        "contract": [
            "Взыскание убытков: ст. 393 ГК РФ",
            "Взыскание неустойки: ст. 330 ГК РФ (договорная) или ст. 395 ГК РФ (законная)",
            "Расторжение договора: ст. 450–453 ГК РФ",
            "Принуждение к исполнению: ст. 398 ГК РФ",
        ],
    }

    basis = basis_by_type.get(dtype, [
        f"Основания требований определяются по {meta['law']}",
        "Необходима правовая квалификация адвокатом после изучения документов",
    ])

    lines = [
        "### ⚖️ ПРАВОВАЯ ПОЗИЦИЯ (черновик)",
        "",
        f"**Категория спора:** {meta['label']}",
        f"**Применимое право:** {meta['law']}",
        "",
        "**Нормативное основание требований:**",
        _fmt_list(basis),
        "",
        "**Структура позиции (предварительно):**",
        "1. Изложение фактических обстоятельств в хронологическом порядке",
        "2. Правовая квалификация нарушения (норма права + факт нарушения)",
        "3. Расчёт требований (основной долг, проценты, неустойка, судебные расходы)",
        "4. Доказательная база по каждому требованию",
        "5. Опровержение вероятных возражений другой стороны",
        "",
        "**Что требует уточнения адвокатом:**",
        "• Проверка фактических обстоятельств по документам",
        "• Правовая квалификация в соответствии с актуальной судебной практикой",
        "• Расчёт точной суммы требований",
        f"• Проверка срока исковой давности ({meta['limitation']})",
        "",
        "⚠️ Черновик правовой позиции. Не подлежит использованию без проверки адвоката.",
    ]
    return "\n".join(lines)


def _analyse_risks(text: str, ctx: dict) -> str:
    meta = ctx["meta"]

    risks = []

    # Limitation risk
    risks.append(("🔴 ВЫСОКИЙ", "Срок исковой давности",
                  f"{meta['limitation']} — необходима проверка точной даты нарушения"))

    # Evidence risks
    if not ctx["has_contract"] and ctx["dispute_type"] in ("debt", "contract"):
        risks.append(("🔴 ВЫСОКИЙ", "Отсутствие письменного договора",
                      "Ст. 162 ГК РФ — нельзя ссылаться на свидетелей; суд может отказать в иске"))
    if not ctx["has_payment_docs"]:
        risks.append(("🟠 СРЕДНИЙ", "Отсутствие платёжных документов",
                      "Факт передачи денег или исполнения не подтверждён допустимыми доказательствами"))

    # Pretrial procedure risk
    if not ctx["has_correspondence"]:
        risks.append(("🟠 СРЕДНИЙ", "Несоблюдение досудебного порядка",
                      f"Суд оставит иск без рассмотрения — {meta['pretrial']}"))

    # Jurisdiction risk
    risks.append(("🟡 НИЗКИЙ", "Подсудность",
                  f"Подать в ненадлежащий суд → возврат иска. Правильный суд: {meta['court']}"))

    # Counterparty risk
    risks.append(("🟡 НИЗКИЙ", "Позиция другой стороны",
                  "Контраргументы и доказательства оппонента не известны — возможны сюрпризы в процессе"))

    if ctx["dispute_type"] == "labor":
        risks.append(("🔴 ВЫСОКИЙ", "Истечение месячного срока по увольнению",
                      "Ст. 392 ТК РФ — срок 1 месяц с даты вручения копии приказа. При пропуске — отказ"))

    if ctx["dispute_type"] == "criminal":
        risks.append(("🔴 КРИТИЧЕСКИЙ", "Процессуальные сроки защиты",
                      "УПК РФ — строгие сроки на обжалование следственных действий. Пропуск → утрата права"))

    lines = ["### ⚠️ ОЦЕНКА РИСКОВ", ""]
    for severity, name, desc in risks:
        lines.append(f"**{severity} — {name}**")
        lines.append(f"  {desc}")
        lines.append("")

    lines += [
        "**Рекомендации по снижению рисков:**",
        "• Немедленно зафиксировать точные даты всех нарушений",
        "• Направить претензию (если не направлялась) — с уведомлением о вручении",
        "• Собрать и систематизировать доказательную базу по каждому требованию",
        "• Проверить, не истёк ли срок исковой давности",
        "",
        "⚠️ Оценка рисков предварительная. Требует проверки адвокатом.",
    ]
    return "\n".join(lines)


def _analyse_sources(text: str, ctx: dict) -> str:
    meta = ctx["meta"]

    # Check for cited norms
    norms_cited = re.findall(
        r"(?:ст(?:атья?|\.)|п(?:ункт|\.)|ч(?:асть|\.))[\s.]*\d+[\s.]*(?:ГК|ТК|СК|УК|КоАП|ЖК|НК|АПК|ГПК|УПК|КАС)[^,;\n]{0,40}",
        text, re.IGNORECASE,
    )
    laws_cited = re.findall(r"(?:федеральн\w+ закон|фз)[^,;\n]{0,60}", text, re.IGNORECASE)

    lines = [
        "### 🔍 ПРОВЕРКА ИСТОЧНИКОВ",
        "",
        "**Нормативные ссылки, найденные в материалах:**",
        _fmt_list(norms_cited if norms_cited else [], fallback="Ссылки на нормы в описании не обнаружены"),
        "",
        "**Законы, упомянутые в материалах:**",
        _fmt_list(laws_cited if laws_cited else [], fallback="Федеральные законы явно не упомянуты"),
        "",
        f"**Рекомендуемые источники для категории «{meta['label']}»:**",
        f"• {meta['law']}",
        f"• {meta['proc']}",
        "• КонсультантПлюс / Гарант — проверка актуальной редакции норм",
        "• Судебная практика: ВС РФ, ВАС РФ (картотека kad.arbitr.ru, sudact.ru)",
        "",
        "**Что проверить адвокату:**",
        "• Актуальность редакции всех применяемых норм на дату спора",
        "• Наличие обзоров судебной практики ВС РФ по данной категории",
        "• Аналогичные дела в регионе (региональная практика может отличаться)",
        "",
        "⚠️ Анализ источников выполнен по описанию. Требует проверки адвокатом.",
    ]
    return "\n".join(lines)


def _analyse_summary(text: str, ctx: dict) -> str:
    meta = ctx["meta"]
    amounts_str = ", ".join(ctx["amounts"]) if ctx["amounts"] else "не определены"
    dates_str = ", ".join(ctx["dates"]) if ctx["dates"] else "не установлены"

    readiness_items = []
    if ctx["has_contract"]:
        readiness_items.append("✓ Договор/расписка упомянут(а)")
    else:
        readiness_items.append("✗ Договор/расписка — ОТСУТСТВУЕТ или не упомянут(а)")
    if ctx["has_payment_docs"]:
        readiness_items.append("✓ Платёжные документы упомянуты")
    else:
        readiness_items.append("✗ Платёжные документы — ОТСУТСТВУЮТ или не упомянуты")
    if ctx["has_correspondence"]:
        readiness_items.append("✓ Претензия/переписка упомянута")
    else:
        readiness_items.append("✗ Претензия — НЕ НАПРАВЛЕНА или не упомянута")
    if ctx["dates"]:
        readiness_items.append(f"✓ Даты установлены: {dates_str}")
    else:
        readiness_items.append("✗ Даты событий — НЕ УКАЗАНЫ (риск давности)")
    if ctx["amounts"]:
        readiness_items.append(f"✓ Суммы: {amounts_str}")
    else:
        readiness_items.append("✗ Суммы требований — НЕ УКАЗАНЫ")

    ready_count = sum(1 for item in readiness_items if item.startswith("✓"))
    total_count = len(readiness_items)
    readiness_pct = int(ready_count / total_count * 100)

    next_steps = [
        "Собрать полный пакет документов (инструмент «ПРОВЕРКА ДОКУМЕНТОВ»)",
        "Направить претензию с уведомлением о вручении (если не направлена)",
        "Рассчитать точную сумму требований с процентами и неустойкой",
        f"Проверить срок исковой давности: {meta['limitation']}",
        "Провести адвокатскую проверку всей позиции до подачи иска",
    ]

    lines = [
        "### 🧾 ФИНАЛЬНАЯ СВОДКА ДЛЯ АДВОКАТА",
        "",
        f"**Категория спора:** {meta['label']}",
        f"**Применимое право:** {meta['law']}",
        f"**Суд:** {meta['court']}",
        f"**Срок давности:** {meta['limitation']}",
        "",
        f"**Готовность к подаче иска: {readiness_pct}%**",
        _fmt_list(readiness_items),
        "",
        "**Следующие шаги:**",
        _fmt_list(next_steps),
        "",
        "**ИТОГ:** " + (
            "Позиция требует существенной доработки — собрать доказательную базу и соблюсти досудебный порядок."
            if readiness_pct < 60 else
            "Базовая документальная основа имеется — уточнить расчёт требований и провести адвокатскую проверку."
            if readiness_pct < 80 else
            "Позиция близка к готовности — финальная проверка адвокатом и подготовка искового заявления."
        ),
        "",
        "⚠️ Черновик. Финальное решение о подаче принимает адвокат.",
    ]
    return "\n".join(lines)


def _analyse_matter(tool_id: str, text: str) -> str:
    """Route to the correct analysis function."""
    ctx = _parse_context(text)
    handlers = {
        "judge_review": _analyse_judge_premium if os.getenv("LEGASVEX_PREMIUM_UI", "true").strip().lower() in {"1", "true", "yes"} else _analyse_judge,
        "case_analysis": _analyse_case,
        "questions_for_principal": _analyse_questions,
        "document_check": _analyse_documents,
        "legal_position": _analyse_legal_position,
        "risk_review": _analyse_risks,
        "source_check": _analyse_sources,
        "final_summary": _analyse_summary,
    }
    handler = handlers.get(tool_id)
    if handler:
        return handler(text, ctx)
    return (
        f"Инструмент «{tool_id}» выполнен: маршрут и контекст дела проверены.\n\n"
        f"Материалов: {len(text.split())} слов. Для содержательного анализа опишите ситуацию подробнее."
    )


# ─────────────────────────── PilotMatterStore ────────────────────────────────


@dataclass(frozen=True)
class StoredMaterial:
    matter_id: str
    document_id: str
    stored_path: str
    audit_event_id: str
    status: str = "saved_locally"


@dataclass(frozen=True)
class StoredAnalysis:
    matter_id: str
    analysis_id: str
    stored_path: str
    audit_event_id: str
    content: str


class PilotMatterStore:
    def __init__(self, root: Path, max_upload_mb: int = 20) -> None:
        self.root = root.resolve()
        self.matters_root = self.root / "matters"
        self.index_path = self.root / "index.json"
        self.max_upload_bytes = max(1, max_upload_mb) * 1024 * 1024
        self.matters_root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls, project_root: Path) -> "PilotMatterStore":
        configured = os.getenv("LEGASVEX_LOCAL_DATA_DIR", "./local_data")
        path = Path(configured)
        if not path.is_absolute():
            path = project_root / path
        try:
            max_mb = int(os.getenv("LEGASVEX_TELEGRAM_MAX_UPLOAD_MB", "20"))
        except ValueError:
            max_mb = 20
        return cls(path, max_upload_mb=max_mb)

    def current_matter(self, chat_id: str) -> str | None:
        return self._read_json(self.index_path, {}).get("current_by_chat", {}).get(str(chat_id))

    def get_or_create_matter(self, chat_id: str, actor_id: str) -> str:
        current = self.current_matter(chat_id)
        if current and self._matter_dir(current).is_dir():
            return current
        now = self._now()
        actor_token = hashlib.sha256(str(actor_id).encode("utf-8")).hexdigest()[:8]
        matter_id = f"MAT-{now.strftime('%Y%m%d-%H%M%S')}-TG{actor_token}-{uuid.uuid4().hex[:4]}"
        matter_dir = self._matter_dir(matter_id)
        for relative in ("intake/messages", "uploads/original", "analysis", "audit"):
            (matter_dir / relative).mkdir(parents=True, exist_ok=True)
        self._write_json(
            matter_dir / "state.json",
            {
                "matter_id": matter_id,
                "status": "active",
                "document_sequence": 0,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            },
        )
        index = self._read_json(self.index_path, {"current_by_chat": {}})
        index.setdefault("current_by_chat", {})[str(chat_id)] = matter_id
        self._write_json(self.index_path, index)
        self._audit(matter_id, "matter.created", actor_id, {"matter_id": matter_id})
        return matter_id

    def save_text(self, chat_id: str, actor_id: str, text: str, message_id: str = "") -> StoredMaterial:
        matter_id = self.get_or_create_matter(chat_id, actor_id)
        document_id = self._next_document_id(matter_id)
        target = self._safe_target(self._matter_dir(matter_id) / "intake" / "messages", f"{document_id}.txt")
        target.write_text(text, encoding="utf-8")
        if not target.exists():
            raise RuntimeError("Text material was not saved locally.")
        metadata = {
            "matter_id": matter_id,
            "document_id": document_id,
            "kind": "text_message",
            "message_id": str(message_id),
            "stored_path": str(target),
            "sha256": sha256_file(target),
            "saved_at": self._now().isoformat(),
        }
        self._append_metadata(target.parent / "metadata.json", metadata)
        event_id = self._audit(matter_id, "document.saved", actor_id, metadata)
        return StoredMaterial(matter_id, document_id, str(target), event_id)

    def save_upload(
        self,
        chat_id: str,
        actor_id: str,
        source_path: Path,
        original_name: str,
        mime_type: str = "",
        message_id: str = "",
    ) -> StoredMaterial:
        source = source_path.resolve()
        if not source.is_file():
            raise RuntimeError("Incoming file was not saved locally.")
        size = source.stat().st_size
        if size > self.max_upload_bytes:
            raise ValueError("Incoming file exceeds configured size limit.")
        matter_id = self.get_or_create_matter(chat_id, actor_id)
        document_id = self._next_document_id(matter_id)
        suffix = Path(sanitize_filename(original_name)).suffix.lower()
        target = self._safe_target(self._matter_dir(matter_id) / "uploads" / "original", f"{document_id}{suffix}")
        shutil.copyfile(source, target)
        if not target.is_file() or target.stat().st_size != size:
            raise RuntimeError("Incoming file was not saved locally.")
        metadata = {
            "matter_id": matter_id,
            "document_id": document_id,
            "kind": "telegram_attachment",
            "original_filename": Path(original_name).name,
            "mime_type": mime_type,
            "message_id": str(message_id),
            "stored_path": str(target),
            "size_bytes": size,
            "sha256": sha256_file(target),
            "saved_at": self._now().isoformat(),
        }
        self._append_metadata(target.parent / "metadata.json", metadata)
        event_id = self._audit(matter_id, "document.saved", actor_id, metadata)
        return StoredMaterial(matter_id, document_id, str(target), event_id)

    def document_ids(self, matter_id: str) -> list[str]:
        ids: list[str] = []
        for metadata_path in (
            self._matter_dir(matter_id) / "intake" / "messages" / "metadata.json",
            self._matter_dir(matter_id) / "uploads" / "original" / "metadata.json",
        ):
            ids.extend(item["document_id"] for item in self._read_json(metadata_path, {"documents": []})["documents"])
        return ids

    def run_tool(self, matter_id: str, tool_id: str, actor_id: str) -> StoredAnalysis:
        if tool_id not in TOOL_REGISTRY:
            raise ValueError(f"Unsupported tool: {tool_id}")
        title, slug = TOOL_REGISTRY[tool_id]
        now = self._now()
        analysis_id = f"ANL-{now.strftime('%Y%m%d-%H%M%S')}-{self._matter_token(matter_id)}-{slug}"
        documents = self.document_ids(matter_id)
        matter_text = self._read_matter_text(matter_id)
        content = self._tool_draft(title, tool_id, matter_id, documents, analysis_id, matter_text)
        target = self._safe_target(self._matter_dir(matter_id) / "analysis", f"{analysis_id}.md")
        target.write_text(content, encoding="utf-8")
        if not target.is_file():
            raise RuntimeError("Analysis result was not saved locally.")
        metadata = {
            "matter_id": matter_id,
            "analysis_id": analysis_id,
            "tool_id": tool_id,
            "input_document_ids": documents,
            "stored_path": str(target),
            "status": "rule_based_draft",
            "requires_human_review": True,
            "allow_external_send": False,
            "saved_at": now.isoformat(),
        }
        self._append_metadata(target.parent / "metadata.json", metadata, key="analyses")
        event_id = self._audit(matter_id, "analysis.saved", actor_id, metadata)
        return StoredAnalysis(matter_id, analysis_id, str(target), event_id, content)

    def record_action(self, matter_id: str, action: str, actor_id: str, payload: dict[str, Any]) -> str:
        return self._audit(matter_id, action, actor_id, payload)

    def _read_matter_text(self, matter_id: str) -> str:
        """Read all stored intake text messages for a matter."""
        messages_dir = self._matter_dir(matter_id) / "intake" / "messages"
        parts: list[str] = []
        if messages_dir.is_dir():
            for txt_file in sorted(messages_dir.glob("*.txt")):
                try:
                    text = txt_file.read_text(encoding="utf-8").strip()
                    if text:
                        parts.append(text)
                except OSError:
                    pass
        return "\n\n".join(parts)

    def _tool_draft(
        self,
        title: str,
        tool_id: str,
        matter_id: str,
        documents: list[str],
        analysis_id: str,
        matter_text: str = "",
    ) -> str:
        checked = "\n".join(f"- {item}" for item in documents) or "- Материалы не загружены"

        if matter_text:
            body = _analyse_matter(tool_id, matter_text)
        else:
            body = (
                "Материалы дела не загружены.\n\n"
                "Для получения анализа сначала опишите юридическую ситуацию в сообщении "
                "или загрузите документы дела."
            )

        return (
            f"# {title}\n\n"
            f"Статус: внутренний AI-черновик для адвоката.\n\n"
            f"Дело: {matter_id}\n\n"
            f"Проверенные материалы:\n{checked}\n\n"
            f"Analysis ID: {analysis_id}\n\n"
            f"{body}\n\n"
            f"{DRAFT_NOTICE}\n"
        )

    def _next_document_id(self, matter_id: str) -> str:
        state_path = self._matter_dir(matter_id) / "state.json"
        state = self._read_json(state_path, {})
        sequence = int(state.get("document_sequence", 0)) + 1
        state["document_sequence"] = sequence
        state["updated_at"] = self._now().isoformat()
        self._write_json(state_path, state)
        return f"DOC-{self._now().strftime('%Y%m%d-%H%M%S')}-{self._matter_token(matter_id)}-{sequence:04d}"

    def _audit(self, matter_id: str, action: str, actor_id: str, payload: dict[str, Any]) -> str:
        event_id = f"AUD-{self._now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
        event = {
            "audit_event_id": event_id,
            "matter_id": matter_id,
            "action": action,
            "actor_hash": hashlib.sha256(str(actor_id).encode("utf-8")).hexdigest()[:16],
            "timestamp": self._now().isoformat(),
            "payload": payload,
        }
        path = self._matter_dir(matter_id) / "audit" / "events.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        return event_id

    def _append_metadata(self, path: Path, item: dict[str, Any], key: str = "documents") -> None:
        payload = self._read_json(path, {key: []})
        payload.setdefault(key, []).append(item)
        self._write_json(path, payload)

    def _safe_target(self, parent: Path, filename: str) -> Path:
        parent.mkdir(parents=True, exist_ok=True)
        target = (parent / filename).resolve()
        if parent.resolve() not in target.parents:
            raise ValueError("Path traversal blocked.")
        return target

    def _matter_dir(self, matter_id: str) -> Path:
        if not re.fullmatch(r"MAT-[A-Za-z0-9-]+", matter_id):
            raise ValueError("Invalid matter_id.")
        return self.matters_root / matter_id

    @staticmethod
    def _matter_token(matter_id: str) -> str:
        return f"MAT-{hashlib.sha256(matter_id.encode('utf-8')).hexdigest()[:4]}"

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(path)
