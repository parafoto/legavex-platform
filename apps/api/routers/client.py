"""Client routes for case management."""

import json
import logging
from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, status

from ..models import get_prisma_client
from ..middleware import get_current_user, require_role, TokenData
from ..schemas.case import CaseCreateRequest, CaseCreateResponse
from ..dependencies import get_audit_service
from ..services import AuditService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/client", tags=["Client"])


@router.post("/cases", response_model=CaseCreateResponse)
async def create_case(
    case_data: CaseCreateRequest,
    current_user: Annotated[TokenData, Depends(require_role("CLIENT"))]
):
    """
    Создать новое дело (доступно только клиентам).
    
    - **title**: Название дела (5-200 символов)
    - **description**: Описание проблемы (20-5000 символов)
    - **budget_expectation_rub**: Ожидаемый бюджет в рублях (> 0)
    - **region**: Регион (2-100 символов)
    - **attachments**: Список URL вложений (опционально)
    
    Возвращает ID созданного дела и статус WAITING_TRIAGE
    """
    db = await get_prisma_client()
    
    # Преобразовать attachments в JSON строку
    attachments_json = None
    if case_data.attachments:
        attachments_json = json.dumps(case_data.attachments)
    
    # Рассчитать budgetMin и budgetMax на основе budget_expectation
    budget_expectation = case_data.budget_expectation_rub
    budget_min = budget_expectation * 0.8
    budget_max = budget_expectation * 1.2
    
    try:
        # Создать дело
        case = await db.case.create(
            data={
                "clientId": current_user.user_id,
                "title": case_data.title,
                "description": case_data.description,
                "budgetExpectation": budget_expectation,
                "budgetMin": budget_min,
                "budgetMax": budget_max,
                "region": case_data.region,
                "attachments": attachments_json,
                "status": "WAITING_TRIAGE",
                "isReviewRequired": True,
                "useEmailDelivery": False,
            }
        )
        
        logger.info(f"Case created: {case.id} by user {current_user.user_id}")
        
        # Логировать создание дела
        audit_service = await get_audit_service(db)
        await audit_service.log(
            action="create_case",
            entity_type=AuditService.ENTITY_CASE,
            entity_id=case.id,
            user_id=current_user.user_id,
            new_value=json.dumps({
                "title": case.title,
                "status": case.status,
                "region": case.region,
                "budgetExpectation": case.budgetExpectation,
            }),
        )
        
        return CaseCreateResponse(
            case_id=case.id,
            status=case.status
        )
        
    except Exception as e:
        logger.error(f"Error creating case: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка при создании дела"
        )


@router.get("/cases")
async def get_my_cases(
    current_user: Annotated[TokenData, Depends(require_role("CLIENT"))]
):
    """
    Получить список дел текущего клиента.
    
    Возвращает все дела, созданные текущим пользователем,
    отсортированные по дате создания (новые первыми).
    """
    db = await get_prisma_client()
    
    cases = await db.case.find_many(
        where={"clientId": current_user.user_id},
        order={"createdAt": "desc"}
    )
    
    return {
        "cases": [
            {
                "id": case.id,
                "title": case.title,
                "description": case.description,
                "status": case.status,
                "region": case.region,
                "budgetExpectation": case.budgetExpectation,
                "createdAt": case.createdAt.isoformat(),
                "updatedAt": case.updatedAt.isoformat(),
            }
            for case in cases
        ],
        "total": len(cases)
    }


@router.get("/cases/{case_id}")
async def get_case_details(
    case_id: str,
    current_user: Annotated[TokenData, Depends(require_role("CLIENT"))]
):
    """
    Получить детали дела (только своего).
    
    - **case_id**: ID дела
    
    Возвращает полную информацию о деле, если оно принадлежит текущему пользователю.
    """
    db = await get_prisma_client()
    
    case = await db.case.find_unique(
        where={"id": case_id},
        include={
            "assignments": {
                "include": {
                    "consultant": {
                        "select": {
                            "name": True,
                            "email": True,
                        }
                    }
                }
            },
            "documents": True,
        }
    )
    
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Дело не найдено"
        )
    
    if case.clientId != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ запрещён"
        )
    
    # Парсить attachments из JSON
    attachments = None
    if case.attachments:
        try:
            attachments = json.loads(case.attachments)
        except json.JSONDecodeError:
            attachments = None
    
    return {
        "id": case.id,
        "title": case.title,
        "description": case.description,
        "status": case.status,
        "region": case.region,
        "budgetExpectation": case.budgetExpectation,
        "budgetMin": case.budgetMin,
        "budgetMax": case.budgetMax,
        "attachments": attachments,
        "isReviewRequired": case.isReviewRequired,
        "useEmailDelivery": case.useEmailDelivery,
        "createdAt": case.createdAt.isoformat(),
        "updatedAt": case.updatedAt.isoformat(),
        "assignments": [
            {
                "id": a.id,
                "status": a.status,
                "assignedAt": a.assignedAt.isoformat(),
                "consultant": {
                    "name": a.consultant.name,
                    "email": a.consultant.email,
                } if a.consultant else None
            }
            for a in (case.assignments or [])
        ],
        "documents": [
            {
                "id": d.id,
                "fileName": d.fileName,
                "type": d.type,
                "status": d.status,
                "uploadedAt": d.uploadedAt.isoformat(),
            }
            for d in (case.documents or [])
        ]
    }
