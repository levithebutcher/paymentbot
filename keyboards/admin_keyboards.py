from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Dict, Any

def get_admin_verification_keyboard(order_id: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="✅ Approve", callback_data=f"admin_approve:{order_id}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"admin_reject_menu:{order_id}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

REJECTION_REASONS = {
    "not_in_bank": "Payment not received/credited in our bank account",
    "fake_utr": "Invalid or unverified UTR/Transaction reference",
    "wrong_amount": "Transferred amount does not match the order total",
    "blurry_proof": "Screenshot is blurry, cropped, or unreadable",
}

def get_admin_rejection_reasons_keyboard(order_id: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="🏦 Not in Bank Account", callback_data=f"admin_reject_reason:{order_id}:not_in_bank")],
        [InlineKeyboardButton(text="⚠️ Fake / Invalid UTR", callback_data=f"admin_reject_reason:{order_id}:fake_utr")],
        [InlineKeyboardButton(text="📉 Incorrect Amount", callback_data=f"admin_reject_reason:{order_id}:wrong_amount")],
        [InlineKeyboardButton(text="📷 Blurry / Incomplete Screenshot", callback_data=f"admin_reject_reason:{order_id}:blurry_proof")],
        [InlineKeyboardButton(text="◀️ Back", callback_data=f"admin_back_to_verify:{order_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_dashboard_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="💳 1. Change Payment Method / QR", callback_data="admin_nav:payment_settings")
        ],
        [
            InlineKeyboardButton(text="📋 2. Manage Services Catalog", callback_data="admin_nav:services")
        ],
        [
            InlineKeyboardButton(text="📢 Broadcast", callback_data="admin_nav:broadcast"),
            InlineKeyboardButton(text="📊 Stats", callback_data="admin_nav:stats")
        ],
        [
            InlineKeyboardButton(text="❌ Close Menu", callback_data="admin_nav:close")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_payment_settings_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="🔄 Change UPI ID", callback_data="admin_pay:change_upi")],
        [InlineKeyboardButton(text="🖼️ Upload New QR Code Image", callback_data="admin_pay:change_qr")],
        [InlineKeyboardButton(text="👤 Change Payee Name", callback_data="admin_pay:change_name")],
        [InlineKeyboardButton(text="◀️ Back to Admin Menu", callback_data="admin_nav:dashboard")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_services_management_keyboard(services: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    buttons = []
    for s in services:
        status_icon = "🟢" if s.get("is_active", 1) == 1 else "🔴"
        title = s.get("title", "Untitled")[:25]
        price = s.get("price_inr", 0)
        btn_text = f"{status_icon} {title} (₹{price:.0f})"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"admin_svc:{s['service_id']}")])

    buttons.append([InlineKeyboardButton(text="➕ Add New Service", callback_data="admin_nav:add_service")])
    buttons.append([InlineKeyboardButton(text="◀️ Back to Admin Menu", callback_data="admin_nav:dashboard")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_service_actions_keyboard(service_id: str, is_active: int) -> InlineKeyboardMarkup:
    toggle_text = "🔴 Deactivate / Hide" if is_active == 1 else "🟢 Activate / Show"
    buttons = [
        [
            InlineKeyboardButton(text="💰 Edit Price", callback_data=f"svc_action:price:{service_id}"),
            InlineKeyboardButton(text="🎁 Edit Delivery", callback_data=f"svc_action:delivery:{service_id}")
        ],
        [
            InlineKeyboardButton(text="📝 Edit Title", callback_data=f"svc_action:title:{service_id}"),
            InlineKeyboardButton(text=toggle_text, callback_data=f"svc_action:toggle:{service_id}")
        ],
        [
            InlineKeyboardButton(text="🗑️ Delete Service", callback_data=f"svc_action:delete:{service_id}"),
            InlineKeyboardButton(text="◀️ Back to Services", callback_data="admin_nav:services")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="🚀 Send Broadcast Now", callback_data="broadcast_action:confirm"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="broadcast_action:cancel")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_cancel_admin_flow_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="❌ Cancel Operation", callback_data="admin_nav:dashboard")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
