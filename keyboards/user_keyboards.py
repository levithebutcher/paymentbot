from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from typing import List, Dict, Any

def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="💎 View Services"), KeyboardButton(text="📦 My Orders")],
        [KeyboardButton(text="💬 Help & Support")]
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        is_persistent=True
    )

def get_services_keyboard(services: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    buttons = []
    for s in services:
        text = f"✦ {s['title']} • ₹{s['price_inr']:.0f}"
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"select_service:{s['service_id']}")])
    
    buttons.append([InlineKeyboardButton(text="📦 My Orders History", callback_data="view_my_orders")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_service_detail_keyboard(service_id: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="⚡ Proceed to Payment", callback_data=f"buy_service:{service_id}")],
        [InlineKeyboardButton(text="← Back to Catalog", callback_data="back_to_services")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_cancel_order_keyboard(order_id: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="✕ Cancel Order", callback_data=f"cancel_order:{order_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_retry_keyboard(service_id: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="🔄 Try Again", callback_data=f"buy_service:{service_id}")],
        [InlineKeyboardButton(text="💎 Back to Catalog", callback_data="back_to_services")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_back_to_catalog_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="← Back to Catalog", callback_data="back_to_services")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_support_start_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="💬 Send Message to Support", callback_data="user_start_support")],
        [InlineKeyboardButton(text="💎 Browse Catalog", callback_data="back_to_services")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_cancel_support_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="✕ Cancel Support Message", callback_data="cancel_user_support")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
