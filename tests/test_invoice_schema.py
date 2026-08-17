from decimal import Decimal

from schemas.invoice import ExtractedInvoice, LineItem


def test_clean_invoice_has_no_issues():
    invoice = ExtractedInvoice(
        vendor_name="Northline Supplies",
        invoice_number="INV-1042",
        line_items=[
            LineItem(description="Wrap", quantity=10, unit_price="12.00", line_total="120.00"),
            LineItem(description="Labels", quantity=4, unit_price="18.50", line_total="74.00"),
        ],
        subtotal="194.00",
        tax="15.52",
        total="209.52",
    )
    assert invoice.needs_review is False
    assert invoice.issues == []


def test_math_mismatch_goes_to_review():
    invoice = ExtractedInvoice(
        vendor_name="Harbor",
        invoice_number="HF-1",
        line_items=[LineItem(description="Boxes", quantity=20, unit_price="2.40", line_total="48.00")],
        subtotal="48.00",
        tax="5.00",
        total="99.99",
    )
    assert invoice.needs_review is True
    assert any(issue.field == "total" for issue in invoice.issues)
    assert invoice.issues[0].expected == str(Decimal("53.00"))
