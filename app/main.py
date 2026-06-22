from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import sqlite3
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.database import (
    check_db_connection,
    create_lead,
    delete_lead,
    get_all_leads,
    get_dashboard_data,
    get_lead,
    init_db,
    update_lead,
)
from app.importer import build_template_xlsx, parse_xlsx_rows
from app.logger import setup_logger
from app.models import (
    DashboardStats,
    ImportResult,
    Lead,
    LeadCreate,
    LeadSearchBy,
    LeadStatus,
    LeadUpdate,
    LeadWebhook,
    MessageResponse,
)
from app.notifications import notify, notify_lead_deleted, notify_lead_updated, notify_new_lead

logger = setup_logger()

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("База данных инициализирована")
    notify("app_started", f"Lead Manager v{__version__}")
    yield
    logger.info("Приложение остановлено")


app = FastAPI(
    title="Lead Manager",
    description="Сервис управления лидами",
    version=__version__,
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    logger.warning("HTTP ошибка: %s - %s", exc.status_code, exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = exc.errors()
    if any(error.get("loc", ())[-1:] == ("contact",) for error in errors):
        detail = "Отсутствует или невалидное поле contact"
    elif any(error.get("type") == "json_invalid" for error in errors):
        detail = "Невалидный JSON"
    else:
        messages = []
        for error in errors:
            field = ".".join(str(part) for part in error.get("loc", []) if part != "body")
            messages.append(f"{field}: {error.get('msg', 'ошибка валидации')}")
        detail = "; ".join(messages) or "Невалидные данные запроса"

    logger.warning("Ошибка валидации: %s", detail)
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"error": detail})


@app.get("/")
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/info")
def api_info() -> dict:
    return {
        "service": "Lead Manager API",
        "version": __version__,
        "endpoints": {
            "GET /": "Веб-интерфейс",
            "GET /api/info": "Информация о сервисе",
            "GET /health": "Проверка работоспособности",
            "POST /lead": "Webhook: принять заявку (name, contact, source, comment)",
            "POST /leads": "Создать лид",
            "POST /leads/import": "Импорт из .xlsx",
            "GET /leads/import/template": "Шаблон .xlsx",
            "GET /leads": "Список лидов (поиск: ?q=...&search_by=name|phone|source)",
            "GET /api/dashboard": "Дашборд по дате, источнику и квалификации",
            "GET /leads/{id}": "Получить лид",
            "PATCH /leads/{id}": "Обновить лид",
            "DELETE /leads/{id}": "Удалить лид",
        },
    }


@app.get("/health")
def health_check() -> dict:
    try:
        check_db_connection()
    except Exception as exc:
        logger.error("Health check failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service unavailable",
        ) from exc

    return {
        "status": "healthy",
        "version": __version__,
        "database": "connected",
    }


@app.get("/api/dashboard", response_model=DashboardStats)
def dashboard() -> DashboardStats:
    return DashboardStats(**get_dashboard_data())


def _save_lead(data: LeadCreate) -> Lead:
    try:
        lead = create_lead(data)
    except sqlite3.Error as exc:
        logger.exception("Ошибка БД при создании лида: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error",
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Лид с таким email уже существует",
            ) from exc
        logger.exception("Ошибка при создании лида")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось создать лид",
        ) from exc

    logger.info("Создан лид id=%s contact=%s", lead.id, lead.contact or "—")
    notify_new_lead(lead)
    return lead


@app.post("/lead", response_model=Lead, status_code=status.HTTP_201_CREATED)
def webhook_lead(data: LeadWebhook) -> Lead:
    """Webhook endpoint по формату MVP-задания."""
    return _save_lead(data.to_lead_create())


@app.post("/leads", response_model=Lead, status_code=status.HTTP_201_CREATED)
def add_lead(data: LeadCreate) -> Lead:
    return _save_lead(data)


@app.get("/leads/import/template")
def download_import_template() -> Response:
    content = build_template_xlsx()
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="leads_template.xlsx"'},
    )


@app.post("/leads/import", response_model=ImportResult)
async def import_leads(file: UploadFile = File(...)) -> ImportResult:
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Поддерживается только формат .xlsx",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Файл пустой",
        )

    try:
        leads, parse_errors = parse_xlsx_rows(file_bytes)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    created = 0
    skipped = 0
    errors = list(parse_errors)

    for index, lead_data in enumerate(leads, start=1):
        try:
            lead = create_lead(lead_data)
            created += 1
            logger.info("Импортирован лид id=%s email=%s", lead.id, lead.email or "—")
        except Exception as exc:
            skipped += 1
            if "UNIQUE constraint failed" in str(exc):
                errors.append(
                    f"Строка с email {lead_data.email}: лид уже существует"
                )
            else:
                errors.append(f"Строка {index}: не удалось сохранить лид")

    if not created and not leads and not errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="В файле нет данных для импорта",
        )

    if not created and not leads and errors:
        preview = "; ".join(errors[:5])
        if len(errors) > 5:
            preview += f" ... и ещё {len(errors) - 5}"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Не удалось импортировать: {preview}",
        )

    notify("leads_imported", f"created={created}, skipped={skipped}")
    return ImportResult(created=created, skipped=skipped, errors=errors)


@app.get("/leads", response_model=list[Lead])
def list_leads(
    status_filter: Optional[LeadStatus] = Query(None, alias="status"),
    q: Optional[str] = Query(None, min_length=1, max_length=200),
    search_by: LeadSearchBy = Query(LeadSearchBy.NAME, alias="search_by"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[Lead]:
    search = q.strip() if q else None
    return get_all_leads(
        status=status_filter,
        search=search,
        search_by=search_by.value,
        limit=limit,
        offset=offset,
    )


@app.get("/leads/{lead_id}", response_model=Lead)
def read_lead(lead_id: int) -> Lead:
    lead = get_lead(lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Лид не найден",
        )
    return lead


@app.patch("/leads/{lead_id}", response_model=Lead)
def patch_lead(lead_id: int, data: LeadUpdate) -> Lead:
    try:
        lead = update_lead(lead_id, data)
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Лид с таким email уже существует",
            ) from exc
        logger.exception("Ошибка при обновлении лида id=%s", lead_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось обновить лид",
        ) from exc

    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Лид не найден",
        )

    logger.info("Обновлён лид id=%s", lead.id)
    notify_lead_updated(lead)
    return lead


@app.delete("/leads/{lead_id}", response_model=MessageResponse)
def remove_lead(lead_id: int) -> MessageResponse:
    lead = get_lead(lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Лид не найден",
        )

    delete_lead(lead_id)
    logger.info("Удалён лид id=%s", lead_id)
    notify_lead_deleted(lead)
    return MessageResponse(message=f"Лид {lead_id} удалён")
