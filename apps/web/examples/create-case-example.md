# Пример создания дела клиентом

## API Endpoint

**POST** `/api/client/cases`

Создаёт новое дело со статусом `WAITING_TRIAGE` (ожидает триажа).

## Аутентификация

Требуется JWT токен с ролью `CLIENT`.

## 1. Логин клиента

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "client@legasvex.ru",
    "password": "client123"
  }'
```

**Ответ:**
```json
{
  "id": "clx1234567890",
  "email": "client@legasvex.ru",
  "name": "Иван Иванов",
  "role": "CLIENT",
  "access_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

## 2. Создание дела

```bash
curl -X POST http://localhost:8000/api/client/cases \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -d '{
    "title": "Консультация по трудовому договору",
    "description": "Нужна помощь в проверке условий трудового договора перед подписанием. Работодатель предлагает нестандартные условия оплаты и график работы.",
    "budget_expectation_rub": 150000,
    "region": "Москва",
    "attachments": ["https://example.com/contract.pdf"]
  }'
```

**Успешный ответ (201):**
```json
{
  "case_id": "clx1234567890",
  "status": "WAITING_TRIAGE",
  "message": "Дело успешно создано и отправлено на рассмотрение"
}
```

## Параметры запроса

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `title` | string | Да | Название дела (5-200 символов) |
| `description` | string | Да | Описание проблемы (20-5000 символов) |
| `budget_expectation_rub` | number | Да | Ожидаемый бюджет в рублях (> 0) |
| `region` | string | Да | Регион (2-100 символов) |
| `attachments` | string[] | Нет | Список URL вложений |

## Ошибки

### 401 Unauthorized
```json
{
  "detail": "Could not validate credentials"
}
```

### 403 Forbidden
```json
{
  "detail": "Insufficient permissions"
}
```

### 422 Validation Error
```json
{
  "detail": "Validation error",
  "errors": [
    {
      "field": "body.title",
      "message": "String should have at least 5 characters",
      "type": "string_too_short"
    }
  ]
}
```

## 3. Получение списка своих дел

```bash
curl -X GET http://localhost:8000/api/client/cases \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

**Ответ:**
```json
{
  "cases": [
    {
      "id": "clx1234567890",
      "title": "Консультация по трудовому договору",
      "description": "...",
      "status": "WAITING_TRIAGE",
      "region": "Москва",
      "budgetExpectation": 150000,
      "createdAt": "2026-02-26T12:00:00.000Z",
      "updatedAt": "2026-02-26T12:00:00.000Z"
    }
  ],
  "total": 1
}
```

## 4. Получение деталей дела

```bash
curl -X GET http://localhost:8000/api/client/cases/clx1234567890 \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

**Ответ:**
```json
{
  "id": "clx1234567890",
  "title": "Консультация по трудовому договору",
  "description": "...",
  "status": "WAITING_TRIAGE",
  "region": "Москва",
  "budgetExpectation": 150000,
  "budgetMin": 120000,
  "budgetMax": 180000,
  "attachments": ["https://example.com/contract.pdf"],
  "isReviewRequired": true,
  "useEmailDelivery": false,
  "createdAt": "2026-02-26T12:00:00.000Z",
  "updatedAt": "2026-02-26T12:00:00.000Z",
  "assignments": [],
  "documents": []
}
```

## Жизненный цикл дела

1. **WAITING_TRIAGE** - Дело создано клиентом, ожидает триажа
2. **NEW** - Дело прошло триаж, готово к назначению консультанта
3. **WAITING_CONSULTANT** - Дело предложено консультанту
4. **IN_PROGRESS** - Консультант работает над делом
5. **REVIEW** - Документы на проверке у администратора
6. **DONE** - Дело завершено
7. **CANCELLED** - Дело отменено
8. **ESCALATED** - Дело эскалировано
