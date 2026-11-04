# 🤖 Telegram Payment Verification & Service Delivery Bot

A production-ready Telegram bot built with **Python 3.10+**, **Aiogram 3.x**, and **SQLite (aiosqlite)** that handles pre-payment for services via static UPI QR Code, prevents fake/duplicate payment screenshots through unique UTR tracking, routes verification requests to a private Telegram Admin Group for 1-click approvals/rejections, and allows dynamic service management and user broadcasts directly from Telegram.

---

## 🌟 Key Features

- **🛍️ Dynamic Services Catalog**: Manage, add, or edit services and pricing directly from Telegram without touching code or restarting the bot.
- **📱 Static UPI QR Code Display**: Displays your static merchant QR code image and copyable UPI ID with full payment instructions.
- **🛡️ Anti-Fraud Duplicate Protection**: Requires users to input the 12-digit UTR/Reference number from their receipt and validates uniqueness in SQLite. Reused or duplicated receipts are rejected instantly.
- **👥 Private Admin Group Verification**: Forwards payment screenshots, customer profiles, order IDs, and UTR details directly to an admin group with interactive inline buttons (`[✅ Approve]` and `[❌ Reject]`).
- **❌ Reason-Based Rejections**: Admins can select standard rejection reasons (*Payment not in bank*, *Fake/Invalid UTR*, *Wrong Amount*, *Blurry Screenshot*), and the bot notifies the user with clear instructions and a retry button.
- **⚡ Instant Automated Delivery**: When an admin taps `Approve`, the user immediately receives their invite link, digital file, or access credentials.
- **🛠️ In-Bot Service Editor (`/admin`)**: Edit service prices, titles, descriptions, and delivery links interactively via buttons without exposing anything to regular users.
- **📢 Safe Mass Broadcast (`/admin`)**: Send announcements (text or photo with caption) to all registered users with live preview, rate-limiting, and error handling for blocked users.
- **📊 Admin Dashboard**: Built-in `/admin` command provides real-time statistics on total registered users, completed orders, approved revenue, and pending verifications.

---

## 📁 Project Structure

```
payment/
├── .env.example              # Configuration template
├── .gitignore                # Git ignore rules
├── requirements.txt          # Python dependencies
├── config.py                 # Bot settings & default services
├── database.py               # Async SQLite database layer with CRUD & anti-fraud
├── main.py                   # Bot entrypoint & polling runner (UTF-8 Windows safe)
├── assets/
│   └── qr_code.png           # Your static UPI QR code image
├── states/
│   └── order_states.py       # FSM states (order flow, service editing, broadcast)
├── keyboards/
│   ├── user_keyboards.py     # User menus, catalog, and retry buttons
│   └── admin_keyboards.py    # Admin dashboard, service actions, and reasons
├── handlers/
│   ├── start.py              # /start, /help, /cancel, and order history
│   ├── services.py           # Services catalog & details
│   ├── payment.py            # Screenshot & UTR submission flow
│   └── admin.py              # Admin verification, service management & broadcast
└── tests/
    └── test_db.py            # Automated test suite (CRUD, anti-fraud, broadcast)
```

---

## 🚀 Setup & Installation Guide

### 1. Clone or Open the Project
Open a terminal in the `payment` folder:
```bash
cd c:\Users\Lenovo\Desktop\payment
```

### 2. Activate Virtual Environment & Install Dependencies
A virtual environment has already been created for you. Activate it:

**On Windows PowerShell:**
```powershell
.\venv\Scripts\Activate.ps1
```
*(If you see an execution policy error on PowerShell, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first).*

**On Windows Command Prompt (CMD):**
```cmd
venv\Scripts\activate.bat
```

Install requirements (already installed in `venv`):
```bash
pip install -r requirements.txt
```

---

## ⚙️ Configuration (.env)

Create a `.env` file by copying `.env.example`:
```powershell
Copy-Item .env.example .env
```

Open `.env` in any text editor and fill in your details:

```env
# 1. Bot Token from @BotFather
BOT_TOKEN=123456789:ABCDefGhIJklMNopQRstUVwxyz_123456

# 2. Telegram Group ID for Admin Review
# Create a private group, add your bot as Admin, and get the group ID
ADMIN_GROUP_ID=-1001234567890

# 3. Your Telegram User ID for /admin dashboard
ADMIN_IDS=123456789

# 4. Your UPI details
UPI_ID=yourmerchant@upi
UPI_NAME=My Store

# 5. Path to your static QR code
QR_IMAGE_PATH=assets/qr_code.png
```

### How to get your `ADMIN_GROUP_ID`:
1. Create a Telegram Group (e.g. `My Bot Payment Alerts`).
2. Add your bot into the group.
3. Promote your bot to **Administrator** with permission to send messages and photos.
4. Add [@RawDataBot](https://t.me/RawDataBot) or forward a message from the group to [@userinfobot](https://t.me/userinfobot) to get the chat ID. Supergroup IDs typically start with `-100...` (e.g., `-1002345678901`).

---

## 🛠️ Managing Services Directly from Telegram

You can manage your catalog anytime by typing `/admin` in private chat with the bot:

1. **View & Edit Services**:
   - Tap **`[📋 Manage Services]`**.
   - Select any service from the list (🟢 = Active, 🔴 = Hidden).
   - Tap **`[💰 Edit Price]`** to change the price in INR.
   - Tap **`[🎁 Edit Delivery]`** to change the channel invite link or message.
   - Tap **`[📝 Edit Title]`** to rename the service.
   - Tap **`[🔴 Deactivate / Hide]`** to temporarily hide it from customers without deleting.
   - Tap **`[🗑️ Delete Service]`** to remove it.
2. **Add a New Service**:
   - Tap **`[➕ Add Service]`**.
   - The bot guides you through 5 quick steps:
     1. Unique ID (e.g. `vip_pro`)
     2. Title (e.g. `💎 VIP Masterclass Channel`)
     3. Description
     4. Price in INR (e.g. `299`)
     5. Delivery Content / Invite link
   - Once completed, the service immediately appears in the customer `/start` and `🛍️ View Services` catalog!

> [!NOTE]
> All editing steps are 100% private to the admin. Regular users will never see intermediate edits or prompts.

---

## 📢 Broadcasting Announcements to All Users

Want to announce a new discount, channel link update, or new service?

1. Type `/admin` and tap **`[📢 Broadcast Message]`**.
2. Send the message you want to broadcast:
   - Plain text formatted in Markdown/bold/italic.
   - Or a photo with a caption.
3. The bot displays a **live preview** showing the exact message and total targeted registered users.
4. Tap **`[🚀 Send Broadcast Now]`**.
5. The bot sends the broadcast safely:
   - Includes **rate-limiting delays** so Telegram never throttles the bot.
   - Automatically catches and skips users who blocked the bot.
   - Posts a final completion report:
     ```
     🎉 BROADCAST COMPLETED!
     ✅ Delivered: 148 users
     🚫 Blocked / Failed: 2 users
     👥 Total Audience: 150 users
     ```

---

## 🖼️ Adding your UPI QR Code Image

A default placeholder QR code is located at `assets/qr_code.png`.
To replace it with your real PhonePe, Google Pay, or Paytm merchant QR code:
1. Download or take a screenshot of your personal/business UPI QR code.
2. Save it as `qr_code.png` inside the `assets/` directory (replacing the placeholder).

---

## ▶️ Running the Bot

Run the bot with:
```powershell
python main.py
```

You should see log output confirming that the bot has started:
```
2026-11-04 11:35:00 [INFO] payment_bot: Initializing database...
2026-11-04 11:35:00 [INFO] payment_bot: Database initialized successfully.
2026-11-04 11:35:01 [INFO] payment_bot: Bot @YourBotUsername (ID: 123456) started successfully.
```

---

## 🧪 Running Automated Tests

Run the test suite to verify database operations, service management CRUD, broadcast tracking, and anti-fraud duplicate checks:
```powershell
.\venv\Scripts\python -m unittest tests/test_db.py
```

Expected output:
```
.......
Ran 7 tests in 2.2s
OK
```
