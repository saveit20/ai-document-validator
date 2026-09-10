"""Ready-to-run examples for the OpenAPI page (/docs). tests/test_api.py checks that the documented
response is what the service actually returns for the documented request."""

SAMPLE_INVOICE = """ACME Industrial Supplies Ltd
12 Harbour Road, Bristol BS1 4QA, United Kingdom
VAT Reg. No: GB123456789

INVOICE

Invoice No: INV-2026-0142
Invoice date: 2026-06-15

Bill to:
Northwind Construction S.L.
Calle Mayor 5, 28013 Madrid, Spain
VAT: ESB12345678

Description                         Qty     Unit price     Amount
Steel anchors M12                    200          2.50     500.00
Safety harness, class A                5        100.00     500.00

Subtotal                                                  1,000.00
VAT 20%                                                     200.00
Total due (EUR)                                           1,200.00
"""

EXAMPLE_CONFIG = {
    "document_type": "SUPPLIER_INVOICE",
    "max_age_days": 90,
    "allowed_currencies": ["EUR", "GBP"],
    "required_fields": ["supplier_name", "invoice_number", "invoice_date", "total_amount"],
}

# The sample invoice is dated 2026-06-15; measured against today it would (correctly) fail the age rule.
EXAMPLE_REFERENCE_DATE = "2026-06-30"

EXAMPLE_VALIDATE_REQUEST = {
    "document": {"text": SAMPLE_INVOICE},
    "config": EXAMPLE_CONFIG,
    "reference_date": EXAMPLE_REFERENCE_DATE,
}

EXAMPLE_EXTRACT_REQUEST = {"document": {"text": SAMPLE_INVOICE}}


def _field(value: object, evidence: str) -> dict[str, object]:
    return {"value": value, "confidence": 1.0, "evidence": evidence, "page": 1}


def _rule(rule_id: str, message: str) -> dict[str, object]:
    return {"id": rule_id, "passed": True, "status": "PASS", "message": message}


# What the service returns for EXAMPLE_VALIDATE_REQUEST in the default (heuristic) mode.
EXAMPLE_VALIDATE_RESPONSE = {
    "request_id": "example-0001",
    "status": "PASS",
    "document_type": "SUPPLIER_INVOICE",
    "extractor_used": "heuristic",
    "reference_date": EXAMPLE_REFERENCE_DATE,
    "warnings": [],
    "llm": None,
    "rules": [
        _rule("invoice_date_max_age", "invoice_date is 15 days old (max 90)"),
        _rule("total_amount_positive", "total_amount 1200.00 is greater than 0"),
        _rule("supplier_name_present", "supplier_name is 'ACME Industrial Supplies Ltd'"),
        _rule("currency_allowed", "currency EUR is allowed"),
        _rule("required_fields_present", "all required fields present"),
        _rule("amounts_consistent", "subtotal 1000.00 + tax 200.00 = total 1200.00"),
    ],
    "extraction": {
        "supplier_name": _field("ACME Industrial Supplies Ltd", "ACME Industrial Supplies Ltd"),
        "invoice_number": _field("INV-2026-0142", "Invoice No: INV-2026-0142"),
        "invoice_date": _field("2026-06-15", "Invoice date: 2026-06-15"),
        "total_amount": _field(1200.0, "Total due (EUR)" + " " * 43 + "1,200.00"),
        "currency": _field("EUR", "Total due (EUR)" + " " * 43 + "1,200.00"),
        "tax_id": _field("GB123456789", "VAT Reg. No: GB123456789"),
        "subtotal_amount": _field(1000.0, "Subtotal" + " " * 50 + "1,000.00"),
        "tax_amount": _field(200.0, "VAT 20%" + " " * 53 + "200.00"),
        "customer_name": _field("Northwind Construction S.L.", "Northwind Construction S.L."),
        "customer_tax_id": _field("ESB12345678", "VAT: ESB12345678"),
    },
}
