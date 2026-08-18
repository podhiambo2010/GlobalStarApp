# Security Policy & Secrets Management

## 1. Reporting Security Vulnerabilities
If you discover a security vulnerability or potential credential leak within the Global Star Investments repository, please report it immediately through private channels rather than public issues.

## 2. Zero-Secrets Policy
* **No Hardcoded Credentials:** Hardcoding API tokens, private keys, database passwords, or connection strings in source code files (`app_backend.py`, `app_frontend.py`, `etims_service.py`, etc.) is strictly prohibited.
* **Environment Variables:** All sensitive keys must be injected at runtime using environment variables (`.env` locally, and Streamlit Cloud Secrets Manager in production).
* **Ignored Files:** Private operational files—such as local bank statements (`KCB_Bank_Statement.xlsx`), tenant ledgers, and local `.env` files—must remain untracked and safely listed in `.gitignore`.

## 3. Data Privacy & Compliance
* Tenant financial data, tax invoices, and transaction ledgers must be handled securely with strict access control.
* Compliance with statutory data protection standards must be maintained across all data ingestion and export workflows.