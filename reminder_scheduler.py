import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Configuration
SENDER_GMAIL = "globalstarinvest@gmail.com"
APP_PASSWORD = "bwng mwof eqrq jpaf"
RECIPIENT_EMAIL = "podhiambo2010@gmail.com"

# Check today's date
today = datetime.now()
day_of_month = today.day
month_str = today.strftime("%B %Y")

# Schedule messages mapped to days
reminders = {
    1: {
        "subject": f"⏰ Property Action Required: Update Bank Statement ({month_str})",
        "body": f"Good morning,\n\nToday is the 1st of {month_str}. Rent is officially due!\n\nActions Required:\n1. Download the latest KCB Bank Statement.\n2. Replace 'KCB_Bank_Statement.xlsx' in your app folder.\n3. Send initial rent statements via the Global Star Tenant Portal.\n\nGlobal Star Investments Limited"
    },
    6: {
        "subject": f"⚠️ Grace Period Ended: Update Bank Statement & Send Soft Reminders ({month_str})",
        "body": f"Good morning,\n\nToday is the 6th of {month_str}. Old lease grace periods ended yesterday.\n\nActions Required:\n1. Export the updated KCB Bank Statement.\n2. Update 'KCB_Bank_Statement.xlsx'.\n3. Review overdue shops and dispatch SMS/Email reminders to tenants with unpaid balances.\n\nGlobal Star Investments Limited"
    },
    11: {
        "subject": f"🚨 Late Penalty Enforcement: Update Statement & Dispatch Legal Notices ({month_str})",
        "body": f"Good morning,\n\nToday is the 11th of {month_str}. Late penalties (KSh 2,000 + 1.5% interest) and access restrictions now apply for unpaid rent.\n\nActions Required:\n1. Update 'KCB_Bank_Statement.xlsx' with the latest KCB statement.\n2. Run batch statement generation to apply penalty fees automatically.\n3. Dispatch Demand Notices to defaulted tenants.\n\nGlobal Star Investments Limited"
    },
    28: {
        "subject": f"📊 End of Month Reconciliation: Final Bank Statement Update ({month_str})",
        "body": f"Good morning,\n\nToday is the 28th of {month_str}. Time for final monthly ledger reconciliation.\n\nActions Required:\n1. Export the month-end KCB Bank Statement.\n2. Update 'KCB_Bank_Statement.xlsx'.\n3. Run final ledger audit and verify zero-balance accounts.\n\nGlobal Star Investments Limited"
    }
}

if day_of_month in reminders:
    msg = MIMEMultipart()
    msg['From'] = f"Global Star System <{SENDER_GMAIL}>"
    msg['To'] = RECIPIENT_EMAIL
    msg['Subject'] = reminders[day_of_month]["subject"]
    msg.attach(MIMEText(reminders[day_of_month]["body"], 'plain'))

    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(SENDER_GMAIL, APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"[{today.strftime('%Y-%m-%d')}] Reminder email successfully sent for Day {day_of_month}.")
    except Exception as e:
        print(f"Error sending email: {e}")
else:
    print(f"[{today.strftime('%Y-%m-%d')}] No reminder scheduled for Day {day_of_month}.")