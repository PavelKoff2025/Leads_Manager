from datetime import datetime
from enum import Enum
import re
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class LeadStatus(str, Enum):
    NEW = "new"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    LOST = "lost"


class LeadSearchBy(str, Enum):
    NAME = "name"
    PHONE = "phone"
    SOURCE = "source"


class LeadCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    contact: Optional[str] = Field(None, max_length=50)
    comment: Optional[str] = Field(None, max_length=500)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=50)
    source: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = Field(None, max_length=2000)

    def resolved_contact(self) -> str:
        return self.contact or self.phone or (str(self.email) if self.email else "")

    def resolved_comment(self) -> str:
        if self.comment is not None:
            return self.comment
        return self.notes or ""


class LeadWebhook(BaseModel):
    """Формат webhook из задания MVP: name, contact, source, comment."""

    name: str = Field(..., min_length=1, max_length=100)
    contact: str = Field(..., min_length=1, max_length=50)
    source: str = Field(..., min_length=1, max_length=50)
    comment: str = Field(default="", max_length=500)

    @field_validator("contact")
    @classmethod
    def validate_contact(cls, value: str) -> str:
        if "@" in value or re.search(r"\d", value):
            return value
        raise ValueError("Контакт должен быть телефоном или email")

    def to_lead_create(self) -> LeadCreate:
        email = None
        phone = None
        if "@" in self.contact:
            email = self.contact
        else:
            phone = self.contact
        return LeadCreate(
            name=self.name,
            contact=self.contact,
            comment=self.comment,
            email=email,
            phone=phone,
            source=self.source,
            notes=self.comment or None,
        )


class LeadUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=50)
    source: Optional[str] = Field(None, max_length=100)
    status: Optional[LeadStatus] = None
    notes: Optional[str] = Field(None, max_length=2000)


class Lead(BaseModel):
    id: int
    name: str
    contact: str
    source: Optional[str] = None
    comment: str = ""
    email: Optional[str] = None
    phone: Optional[str] = None
    status: LeadStatus = LeadStatus.NEW
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    message: str


class ImportResult(BaseModel):
    created: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


class DashboardItem(BaseModel):
    label: str
    count: int


class DashboardStats(BaseModel):
    total: int
    by_date: list[DashboardItem]
    by_source: list[DashboardItem]
    by_status: list[DashboardItem]
