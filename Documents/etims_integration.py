import requests
import json

class KRAeTIMSClient:
    def __init__(self, kra_pin: str, branch_id: str = "00", environment: str = "sandbox"):
        self.kra_pin = kra_pin
        self.branch_id = branch_id
        if environment == "production":
            self.base_url = "https://etims-api.kra.go.ke/etims-api"
        else:
            self.base_url = "https://etims-api-sbx.kra.go.ke/etims-api"
        self.cmc_key = None

    def initialize_device(self):
        """Initializes branch device and retrieves cmcKey."""
        url = f"{self.base_url}/selectInitOsdcInfo"
        payload = {
            "tin": self.kra_pin,
            "bhfId": self.branch_id
        }
        res = requests.post(url, json=payload, headers={"Content-Type": "application/json"})
        if res.status_code == 200:
            data = res.json()
            if data.get("resultCd") == "000":
                self.cmc_key = data.get("data", {}).get("cmcKey")
                return True, self.cmc_key, "Device successfully initialized with KRA!"
            return False, None, data.get("resultMsg", "Initialization failed.")
        return False, None, f"HTTP Error {res.status_code}"

    def register_rent_service_item(self, item_code: str = "RENT-COMM-01", item_name: str = "Commercial Property Rent"):
        """Registers Commercial Rent service item on KRA eTIMS catalog."""
        url = f"{self.base_url}/saveItem"
        payload = {
            "tin": self.kra_pin,
            "bhfId": self.branch_id,
            "cmcKey": self.cmc_key,
            "itemCd": item_code,
            "itemClsCd": "80131500",  # Commercial Real Estate Lease
            "itemName": item_name,
            "pkgUnitCd": "NT",         # Not Applicable
            "qtyUnitCd": "NT",
            "vatTyCd": "A",            # A = 16% VAT, B = Exempt, C = Zero Rated
            "dftPrc": 0.0
        }
        res = requests.post(url, json=payload, headers={"Content-Type": "application/json"})
        return res.json()

    def transmit_rent_invoice(self, tenant_name: str, tenant_pin: str, shop_no: int, base_rent: float, is_vat_applicable: bool = False):
        """Transmits rent transaction directly to KRA OSCU for digital signing."""
        url = f"{self.base_url}/saveTrnsSalesOsdc"
        
        vat_type = "A" if is_vat_applicable else "B"
        vat_amount = base_rent * 0.16 if is_vat_applicable else 0.0
        total_gross = base_rent + vat_amount

        payload = {
            "tin": self.kra_pin,
            "bhfId": self.branch_id,
            "cmcKey": self.cmc_key,
            "trnsNo": 1,
            "custTin": tenant_pin if tenant_pin and len(tenant_pin) == 11 else "",
            "custNm": tenant_name,
            "prchAcptAproNo": "",
            "rcptTyCd": "N",         # N = Normal, C = Copy, T = Training
            "pmtTyCd": "01",         # 01 = Cash/Bank Transfer
            "salesSttsCd": "02",     # 02 = Approved/Completed
            "cfmDt": "",
            "salesDt": "",
            "stockRlsDt": "",
            "cnclReqDt": "",
            "cnclDt": "",
            "rctPrtCnt": 1,
            "totItemCnt": 1,
            "taxblAmtA": base_rent if is_vat_applicable else 0.0,
            "taxblAmtB": base_rent if not is_vat_applicable else 0.0,
            "taxAmtA": vat_amount,
            "totAmt": total_gross,
            "itemList": [
                {
                    "itemSeq": 1,
                    "itemCd": "RENT-COMM-01",
                    "itemClsCd": "80131500",
                    "itemName": f"Commercial Rent - Shop #{shop_no}",
                    "pkgUnitCd": "NT",
                    "qtyUnitCd": "NT",
                    "qty": 1.0,
                    "prc": base_rent,
                    "totAmt": total_gross,
                    "vatTyCd": vat_type,
                    "vatAmt": vat_amount
                }
            ]
        }

        res = requests.post(url, json=payload, headers={"Content-Type": "application/json"})
        if res.status_code == 200:
            data = res.json()
            if data.get("resultCd") == "000":
                result_data = data.get("data", {})
                return {
                    "status": "SUCCESS",
                    "etims_invoice_no": result_data.get("curInvcNo"),
                    "scu_id": result_data.get("sdcId"),
                    "receipt_signature": result_data.get("rcptSign"),
                    "qr_code_url": f"https://etims.kra.go.ke/common/link/etims/receipt/index?checkGdm={result_data.get('rcptSign')}"
                }
            return {"status": "FAILED", "error": data.get("resultMsg", "eTIMS submission rejected.")}
        return {"status": "FAILED", "error": f"HTTP {res.status_code}"}