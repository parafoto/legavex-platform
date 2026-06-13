def format_help() -> str:
    return (
        "LegasVex AI CRM помощник\n"
        "\n"
        "Можно писать обычным языком:\n"
        "- Какие сейчас риски?\n"
        "- Покажи портфель дел\n"
        "- Что по делу matter-...\n"
        "- Проверь договор: ...\n"
        "- Пришлите файл с подписью: договор по делу matter-...\n"
        "- Покажи демо\n"
        "- Создай обращение: Иван Петров | Жалоба в суд\n"
        "\n"
        "Команды тоже работают: /demo, /dashboard, /portfolio, /matter, /intake, /risk_scan."
    )


def format_demo_script() -> str:
    return (
        "Демо LegasVex для адвоката\n"
        "1. /seed - загрузить демо-данные.\n"
        "2. Какие сейчас риски? - получить ключевые риски по делам.\n"
        "3. Что по срокам? - увидеть просрочки и ближайшие дедлайны.\n"
        "4. Покажи портфель дел - открыть список активных дел.\n"
        "5. Проверь договор: ... - создать Legal QA проверку и HITL-задачу.\n"
        "6. Пришлите файл с подписью: договор по делу matter-... - сохранить документ в archive и поставить задачу адвокату.\n"
        "Пилотный принцип: AI готовит анализ, финальное решение остаётся за адвокатом."
    )


def format_dashboard(snapshot: dict) -> str:
    return (
        "Сводка практики\n"
        f"Активные дела: {snapshot['open_matters']}\n"
        f"Высокий приоритет: {snapshot['high_priority_matters']}\n"
        f"Клиенты: {snapshot['client_count']}\n"
        f"На проверке: {snapshot['review_queue']}\n"
        f"Поручений: {snapshot['active_assignments']}\n"
        f"Просрочено: {snapshot['overdue_deadlines']}\n"
        f"Ближайшие сроки: {snapshot['upcoming_deadlines']}\n"
        f"AI-обзор: {snapshot['ai_brief']}"
    )


def format_risk_answer(snapshot: dict) -> str:
    risks = snapshot.get("key_risks") or []
    if not risks:
        return "Сейчас ключевые риски не выявлены. Проверьте портфель и сроки после обновления данных."
    lines = ["Ключевые риски:"]
    for risk in risks[:5]:
        lines.append(
            f"- {risk['severity']}: {risk['title']} | дело {risk['matter_id']}\n"
            f"  {risk['rationale']}"
        )
    return "\n".join(lines)


def format_deadline_answer(snapshot: dict) -> str:
    return (
        "Сроки и нагрузка:\n"
        f"- просрочено: {snapshot['overdue_deadlines']}\n"
        f"- ближайшие сроки: {snapshot['upcoming_deadlines']}\n"
        f"- активные поручения: {snapshot['active_assignments']}\n"
        f"- дел на проверке: {snapshot['review_queue']}"
    )


def format_portfolio(items: list[dict]) -> str:
    if not items:
        return "Портфель дел пуст."
    lines = ["Портфель дел"]
    for item in items[:8]:
        lines.append(
            f"- {item['matter_id']} | {item['title']} | {item['owner_name']} | "
            f"{item['status']} | риск={item['risk_level']}"
        )
    return "\n".join(lines)


def format_matter(item: dict) -> str:
    return (
        f"Дело {item['matter_id']}\n"
        f"Тема: {item['title']}\n"
        f"Ответственный: {item['owner_name']}\n"
        f"Приоритет: {item['priority']}\n"
        f"Статус: {item['status']}\n"
        f"Описание: {item['summary']}"
    )


def format_intake_result(record: dict) -> str:
    return (
        "Обращение зарегистрировано\n"
        f"Обращение: {record['intake_id']}\n"
        f"Дело: {record['crm_matter_id'] or record['matter_id']}\n"
        f"Клиент: {record['crm_client_id'] or 'ожидается'}\n"
        f"Статус: {record['status']}\n"
        f"Синхронизация: {record['integration_state']}"
    )


def format_contract_risk_scan(record: dict) -> str:
    result = record["result"]
    assignment = record.get("crm_assignment") or {}
    plan = record.get("orchestrator_plan") or {}
    tasks = plan.get("tasks", [])
    first_task = tasks[0] if tasks else {}
    findings = result.get("findings", [])
    lines = [
        "Анализ договора завершён",
        f"Дело: {result.get('matter_id') or 'не задано'}",
        f"Замечания: {len(findings)}",
        f"Требует проверки адвокатом: {result.get('requires_human_approval')}",
        f"Поручение CRM: {assignment.get('assignment_id', 'не создано')}",
        f"Задача оркестратора: {first_task.get('id', 'не создана')} ({first_task.get('status', 'неизвестно')})",
    ]
    for item in findings[:3]:
        lines.append(f"- {item['severity']}: {item['title']}")
    lines.append(
        "\n⚠️ Анализ сформирован автоматически на основе правил. "
        "Это внутренний черновик для адвоката. "
        "Требует профессиональной проверки перед использованием."
    )
    return "\n".join(lines)


def format_document_upload_result(record: dict) -> str:
    metadata = record.get("metadata") or {}
    scan = record.get("review") or {}
    result = scan.get("result") or {}
    assignment = scan.get("crm_assignment") or {}
    plan = scan.get("orchestrator_plan") or {}
    tasks = plan.get("tasks", [])
    first_task = tasks[0] if tasks else {}
    sha256 = metadata.get("sha256", "")
    lines = [
        "Документ принят",
        f"Файл: {metadata.get('original_filename') or 'telegram document'}",
        f"Дело: {record.get('matter_id') or result.get('matter_id') or 'не определено'}",
        f"SHA256: {sha256[:12] if sha256 else 'не вычислен'}",
        f"Извлечено текста: {metadata.get('extracted_text_chars', 0)} символов ({metadata.get('extraction_status', 'неизвестно')})",
        f"Архив: {metadata.get('stored_path', 'не сохранён')}",
        f"Статус: {record.get('status', 'создано')}",
        f"Поручение CRM: {assignment.get('assignment_id', 'не создано')}",
        f"HITL: {first_task.get('status', 'неизвестно')}",
        "\n⚠️ Документ сохранён локально. Результат анализа является черновиком для адвоката "
        "и не передаётся доверителю.",
    ]
    return "\n".join(lines)
