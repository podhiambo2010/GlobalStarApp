# Global Star Investments: Project Constitution & Governance

## 1. The Constitution (Core Values & Creed)
* **Data Integrity & Immutability:** Financial records, tax compliance (KRA eTIMS), and ledger transactions are sacred. Every computation must be deterministic, auditable, and mathematically exact.
* **Compliance First:** Adherence to statutory requirements (KRA tax regulations, data privacy, and financial reporting standards) is non-negotiable and baked directly into the system architecture.
* **Resilience Over Speed:** System stability and zero data loss take precedence over rapid feature deployment. Every upgrade must protect existing financial history.

## 2. Governance (Security, Access, and Control)
* **Strict Separation of Secrets:** Hardcoded keys, tokens, and credentials are strictly prohibited. All sensitive variables (KRA OSCU tokens, WhatsApp Meta API secrets, database connection strings) must be managed via environment variables (`.env`) and secure secret stores.
* **Role-Based Access Control (RBAC):** Access is permission-based. Property owners, managers, and tenants operate within isolated, secure boundaries.
* **Auditable Operations:** Every state change, invoice generation, and automated communication dispatch must leave a clear trace.

## 3. Architecture Principles
* **State Persistence:** Relational database storage (PostgreSQL via Supabase) guarantees ACID compliance and multi-user concurrency, replacing ephemeral local files.
* **Modular Separation:** Clean boundaries must be maintained between the data layer, business logic services, and the Streamlit frontend.
* **Asynchronous Automation:** Communication dispatch (WhatsApp, SMS, Email) and scheduled tasks run via background execution to keep the UI responsive.