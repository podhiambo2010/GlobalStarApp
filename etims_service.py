"""Safe, fail-closed KRA eTIMS placeholder for Excel-only V1.

This branch does not perform tax-device activation or invoice submission.
Official KRA submission requires a separate verified and approved integration.
"""
class KRAeTIMSClient:
    def __init__(self, kra_pin=None, environment="Disabled"):
        self.kra_pin = kra_pin
        self.environment = environment

    def initialize_device(self):
        return False, None, "KRA eTIMS integration disabled: no verified connection."

    def transmit_rent_invoice(self, *args, **kwargs):
        return {
            "status": "ERROR",
            "reason": "KRA eTIMS submission disabled: no verified integration.",
            "receipt_signature": None,
            "cu_invoice_no": None,
            "qr_code_url": None,
        }
