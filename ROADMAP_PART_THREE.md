# Roadmap: Global Star Investments Enterprise-Grade Scaling (Part Three)

This document outlines the strategic roadmap for transitioning the Global Star Investments property management system into a fully scalable, enterprise-grade SaaS product.

## 1. Database & Multi-Tenant Architecture
- **Objective:** Replace local Excel files (.xlsx) with a secure, relational database.
- **Tasks:**
    - Set up a PostgreSQL instance (e.g., Supabase).
    - Design normalized schema for properties, units, tenants, leases, and transactions.
    - Implement multi-tenant portfolio isolation to support multiple enterprise users.
    - Develop data migration scripts to import legacy .xlsx data into the database.

## 2. Security & Environment Management
- **Objective:** Eliminate hardcoded secrets and implement secure credential handling.
- **Tasks:**
    - Audit codebase for any remaining hardcoded tokens (KRA, WhatsApp, SMTP).
    - Implement `python-dotenv` for secure local secret management.
    - Configure production-grade secret management for Streamlit Cloud and future deployment environments.

## 3. Role-Based Access Control (RBAC)
- **Objective:** Secure access based on user roles.
- **Tasks:**
    - Implement user authentication (e.g., Streamlit Authenticator or OAuth).
    - Define roles: Admin, Property Manager, Landlord, Tenant.
    - Create permission-gated views to ensure data privacy across user types.

## 4. Robust Error Handling & Logging
- **Objective:** Increase system stability and visibility.
- **Tasks:**
    - Implement centralized structured logging for tracking transactions and API calls.
    - Build automated fallback states for API integrations (e.g., if KRA eTIMS is temporarily unavailable).
    - Develop custom exception handling to provide user-friendly feedback during runtime errors.

## 5. Automated Background Task Scheduling
- **Objective:** Automate routine business operations.
- **Tasks:**
    - Integrate task queues (e.g., Celery/Redis or APScheduler) for background execution.
    - Automate monthly rent invoice generation and dispatch.
    - Schedule periodic payment reminder WhatsApp/SMS/Email dispatches.
    - Automate periodic penalty and interest recalculations.

## 6. Production-Grade CI/CD & Testing
- **Objective:** Ensure code quality and streamlined deployments.
- **Tasks:**
    - Develop Pytest test suite for core financial calculation modules.
    - Configure CI/CD pipelines for automated testing on push.
    - Maintain strict environment variable management.

## 7. UI/UX Refinement
- **Objective:** Enhance the user interface for enterprise-grade usability.
- **Tasks:**
    - Replace standard Streamlit data tables with interactive grids (e.g., `ag-grid`).
    - Enable inline editing for ledger entries.
    - Implement advanced search and multi-dimensional reporting filters.
    - Create comprehensive financial reporting dashboards.