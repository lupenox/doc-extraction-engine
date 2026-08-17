from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, Field, field_validator, model_validator

TWOPLACES = Decimal("0.01")


def money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


class LineItem(BaseModel):
    description: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal

    @field_validator("quantity", "unit_price", "line_total", mode="before")
    @classmethod
    def _money_fields(cls, value):
        return money(value)

    def expected_total(self) -> Decimal:
        return money(self.quantity * self.unit_price)


class ValidationIssue(BaseModel):
    field: str
    message: str
    expected: str | None = None
    actual: str | None = None


class ExtractedInvoice(BaseModel):
    vendor_name: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    currency: str = "USD"
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    issues: list[ValidationIssue] = Field(default_factory=list)

    @field_validator("subtotal", "tax", "total", mode="before")
    @classmethod
    def _money_totals(cls, value):
        return None if value in (None, "") else money(value)

    @model_validator(mode="after")
    def check_math(self) -> "ExtractedInvoice":
        settings_tol = Decimal("0.01")
        try:
            from config import get_settings

            settings_tol = money(get_settings().amount_tolerance)
        except Exception:
            pass

        issues: list[ValidationIssue] = []
        if not self.vendor_name:
            issues.append(ValidationIssue(field="vendor_name", message="Vendor is required"))
        if not self.invoice_number:
            issues.append(ValidationIssue(field="invoice_number", message="Invoice number is required"))

        for idx, item in enumerate(self.line_items):
            expected = item.expected_total()
            if abs(expected - item.line_total) > settings_tol:
                issues.append(
                    ValidationIssue(
                        field=f"line_items[{idx}].line_total",
                        message="quantity * unit_price does not match line_total",
                        expected=str(expected),
                        actual=str(item.line_total),
                    )
                )

        if self.line_items:
            expected_subtotal = money(sum((item.line_total for item in self.line_items), Decimal("0")))
            if self.subtotal is None:
                self.subtotal = expected_subtotal
            elif abs(expected_subtotal - self.subtotal) > settings_tol:
                issues.append(
                    ValidationIssue(
                        field="subtotal",
                        message="subtotal does not equal sum of line totals",
                        expected=str(expected_subtotal),
                        actual=str(self.subtotal),
                    )
                )

        if self.subtotal is not None and self.tax is not None:
            expected_total = money(self.subtotal + self.tax)
            if self.total is None:
                self.total = expected_total
            elif abs(expected_total - self.total) > settings_tol:
                issues.append(
                    ValidationIssue(
                        field="total",
                        message="subtotal + tax does not equal total",
                        expected=str(expected_total),
                        actual=str(self.total),
                    )
                )

        self.issues = issues
        return self

    @property
    def needs_review(self) -> bool:
        return bool(self.issues)
