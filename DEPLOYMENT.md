# Deployment & Production Operations Guide

This document outlines the standard operating procedures for deploying and maintaining the Global Star Investments application in production environments (e.g., Streamlit Cloud).

## 1. Environment Secrets Management
Production secrets must never be committed to version control. They are injected securely at runtime via the platform's secret manager.

### Required Production Secrets (`st.secrets`):
* `KRA_OSCU_API_KEY` — Authentication token for KRA eTIMS integration.
* `WHATSAPP_ACCESS_TOKEN` — Meta Cloud API token for automated WhatsApp dispatches.
* `WHATSAPP_PHONE_NUMBER_ID` — Business phone number identifier for WhatsApp messaging.
* `SMTP_PASSWORD` — Secure mail transport password for automated email invoicing.
* `DATABASE_URL` — Connection string for the persistent relational database (PostgreSQL/Supabase).

## 2. Pre-Deployment Verification Checklist
Before pushing code changes to the `main` branch for production release, verify that:
1. **No Hardcoded Secrets:** All API keys and credentials reference `os.getenv()` or `st.secrets`.
2. **Local Test Run:** The application runs cleanly locally without missing dependencies in `requirements.txt`.
3. **Data Protection:** No sensitive local files (`KCB_Bank_Statement.xlsx`, private tenant logs) are tracked by git.

## 3. Production Deployment Steps
1. Commit all verified changes to a feature branch, then merge into `main`:
   ```bash
   git checkout main
   git merge feature/your-feature-name
   git push origin main