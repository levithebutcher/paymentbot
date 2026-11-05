from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Dict, Any

def get_admin_verification_keyboard(order_id: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="📤 Send Delivery", callback_data=f"admin_deliver_flow:{order_id}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"admin_reject:{order_id}")
        ],
        [
            InlineKeyboardButton(text="💬 Message Buyer", callback_data=f"admin_msg_buyer:{order_id}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_support_ticket_keyboard(ticket_id: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="💬 Reply to Customer", callback_data=f"admin_reply_ticket:{ticket_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_cancel_support_reply_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="✕ Cancel Reply", callback_data="admin_cancel_support_reply")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_cancel_delivery_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="✕ Cancel Delivery", callback_data="admin_cancel_delivery")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

REJECTION_REASONS = {
    "not_in_bank": "Payment not credited to bank account",
    "wrong_amount": "Amount transferred does not match order price",
    "blurry_proof": "Screenshot is blurry, cropped, or unreadable",
    "invalid_proof": "Receipt could not be verified by admin",
}

def get_admin_rejection_reasons_keyboard(order_id: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="🏦 Not in Bank Account", callback_data=f"admin_reject_reason:{order_id}:not_in_bank")],
        [InlineKeyboardButton(text="📉 Incorrect Amount", callback_data=f"admin_reject_reason:{order_id}:wrong_amount")],
        [InlineKeyboardButton(text="📷 Blurry / Incomplete Image", callback_data=f"admin_reject_reason:{order_id}:blurry_proof")],
        [InlineKeyboardButton(text="◀️ Back", callback_data=f"admin_back_to_verify:{order_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_dashboard_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="💳 Payment & QR Settings", callback_data="admin_nav:payment_settings")
        ],
        [
            InlineKeyboardButton(text="📋 Manage Services Catalog", callback_data="admin_nav:services")
        ],
        [
            InlineKeyboardButton(text="📦 Recent Orders", callback_data="admin_nav:orders"),
            InlineKeyboardButton(text="📊 Live Stats", callback_data="admin_nav:stats")
        ],
        [
            InlineKeyboardButton(text="📢 Broadcast Announcement", callback_data="admin_nav:broadcast")
        ],
        [
            InlineKeyboardButton(text="✕ Close Panel", callback_data="admin_nav:close")
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
            InlineKeyboardButton(text="📝 Edit Title", callback_data=f"svc_action:title:{service_id}")
        ],
        [
            InlineKeyboardButton(text="📄 Edit Description", callback_data=f"svc_action:desc:{service_id}"),
            InlineKeyboardButton(text=toggle_text, callback_data=f"svc_action:toggle:{service_id}")
        ],
        [
            InlineKeyboardButton(text="🗑️ Delete Service", callback_data=f"svc_action:delete:{service_id}"),
            InlineKeyboardButton(text="◀️ Back to Services", callback_data="admin_nav:services")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_service_created_keyboard(service_id: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="➕ Add Another Service", callback_data="admin_nav:add_service"),
            InlineKeyboardButton(text="📋 Manage Services", callback_data="admin_nav:services")
        ],
        [
            InlineKeyboardButton(text="◀️ Back to Dashboard", callback_data="admin_nav:dashboard")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_recent_orders_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="🔄 Refresh Orders", callback_data="admin_nav:orders")],
        [InlineKeyboardButton(text="◀️ Back to Dashboard", callback_data="admin_nav:dashboard")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="🚀 Send Broadcast Now", callback_data="broadcast_action:confirm"),
            InlineKeyboardButton(text="✕ Cancel", callback_data="broadcast_action:cancel")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_cancel_admin_flow_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="✕ Cancel", callback_data="admin_nav:dashboard")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
