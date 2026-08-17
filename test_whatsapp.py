from app_backend import TenantPortalBackend

print("Initializing backend...")
backend = TenantPortalBackend("Tenants_Details.xlsx", "KCB_Bank_Statement.xlsx")

print("Sending test WhatsApp message...")
success, message = backend.send_whatsapp_message("254723562286", "Hello from GlobalStarPortal!")

print(f"Status: {success}")
print(f"Response: {message}")