from datetime import datetime
from pathlib import Path

from app.logger import setup_logger
from app.models import Lead

logger = setup_logger("notifications")

NOTIFICATIONS_FILE = Path(__file__).resolve().parent.parent / "logs" / "events.log"
BANNER_WIDTH = 50


def _format_optional(value: str | None) -> str:
    return value if value else "—"


def log_event(message: str) -> None:
    """Запись события в лог (вариант A из задания MVP)."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(message)
    NOTIFICATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(NOTIFICATIONS_FILE, "a", encoding="utf-8") as f:
        f.write(f"{timestamp} | {message}\n")


def _print_banner(title: str, lines: list[str]) -> None:
    """Красивый вывод уведомления в консоль."""
    print("\n" + "=" * BANNER_WIDTH)
    print(title)
    for line in lines:
        print(f"  {line}")
    print("=" * BANNER_WIDTH + "\n")


def notify(event: str, details: str = "") -> None:
    """Записывает уведомление о событии в лог-файл."""
    message = f"[NOTIFICATION] {event}"
    if details:
        message = f"{message} | {details}"
    log_event(message)


def notify_new_lead(lead: Lead) -> None:
    """Уведомление о новой заявке: event log + вывод в консоль."""
    log_event(f"New lead saved: {lead.id}")
    _print_banner(
        f"📋 НОВАЯ ЗАЯВКА #{lead.id}",
        [
            f"Имя: {lead.name}",
            f"Контакт: {_format_optional(lead.contact)}",
            f"Источник: {_format_optional(lead.source)}",
            f"Комментарий: {_format_optional(lead.comment)}",
        ],
    )


def notify_lead_updated(lead: Lead) -> None:
    """Уведомление об обновлении заявки."""
    log_event(f"Lead updated: {lead.id}")
    _print_banner(
        f"✏️  ЗАЯВКА ОБНОВЛЕНА #{lead.id}",
        [
            f"Имя: {lead.name}",
            f"Контакт: {_format_optional(lead.contact)}",
            f"Статус: {lead.status.value}",
            f"Источник: {_format_optional(lead.source)}",
        ],
    )


def notify_lead_deleted(lead: Lead) -> None:
    """Уведомление об удалении заявки."""
    log_event(f"Lead deleted: {lead.id}")
    _print_banner(
        f"🗑️  ЗАЯВКА УДАЛЕНА #{lead.id}",
        [
            f"Имя: {lead.name}",
            f"Контакт: {_format_optional(lead.contact)}",
        ],
    )
