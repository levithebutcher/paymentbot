import html
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from database import upsert_user, get_services, get_user_orders
from keyboards.user_keyboards import (
    get_main_menu_keyboard,
    get_services_keyboard,
    get_back_to_catalog_keyboard
)

start_router = Router()

@start_router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    if user:
        await upsert_user(user.id, user.username, user.full_name)

    first_name = html.escape(user.first_name if user else "Member")
    welcome_text = (
        "╭──────────────────────────────╮\n"
        "│     ✦ DIGITAL SERVICES STORE ✦    │\n"
        "╰──────────────────────────────╯\n"
        f"Welcome, <b>{first_name}</b>!\n\n"
        "Browse our catalog, checkout securely via <b>UPI QR Code</b>, and receive your verified delivery directly in this chat.\n\n"
        "⚡ <i>Instant UPI Activation</i>\n"
        "🔒 <i>Direct Verified Delivery by Admin</i>"
    )

    await message.answer(welcome_text, reply_markup=get_main_menu_keyboard(), parse_mode="HTML")

    services = await get_services()
    if services:
        await message.answer(
            "╭── 💎 AVAILABLE SERVICES ─────╮\n"
            "│ Select an item to view info: │\n"
            "╰──────────────────────────────╯",
            reply_markup=get_services_keyboard(services),
            parse_mode="HTML"
        )

@start_router.message(Command("help"))
@start_router.message(F.text.in_({"💬 Help & Support", "ℹ️ Help & Support"}))
async def handle_help(message: Message):
    help_text = (
        "╭── 💬 HOW TO ORDER & PAY ─────╮\n"
        "│ Follow these 4 simple steps: │\n"
        "╰──────────────────────────────╯\n\n"
        "1. <b>Choose Service:</b> Tap <i>💎 View Services</i> and pick your desired item.\n"
        "2. <b>Make Payment:</b> Scan the UPI QR Code or copy our UPI ID.\n"
        "3. <b>Send Screenshot:</b> Upload your payment receipt screenshot here.\n"
        "4. <b>Receive Delivery:</b> Our admin verifies the payment and delivers your file or access directly in this chat!\n\n"
        "💡 <i>Type /cancel anytime to abort an active order.</i>"
    )
    await message.answer(help_text, reply_markup=get_main_menu_keyboard(), parse_mode="HTML")

@start_router.message(Command("cancel"))
async def handle_cancel(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("ℹ️ No active order in progress.", reply_markup=get_main_menu_keyboard())
        return

    data = await state.get_data()
    qr_msg_id = data.get("qr_msg_id")
    if qr_msg_id:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=qr_msg_id)
        except Exception:
            pass

    try:
        await message.delete()
    except Exception:
        pass

    await state.clear()
    await message.answer(
        "✕ <b>Order cancelled.</b> You can start fresh anytime from the menu.",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML"
    )

@start_router.message(F.text == "📦 My Orders")
@start_router.callback_query(F.data == "view_my_orders")
async def handle_my_orders(event: Message | CallbackQuery):
    user_id = event.from_user.id
    orders = await get_user_orders(user_id)

    if not orders:
        text = (
            "╭── 📦 YOUR ORDERS ────────────╮\n"
            "│ No orders found yet.         │\n"
            "╰──────────────────────────────╯\n"
            "Browse our catalog to make your first purchase!"
        )
    else:
        text = (
            "╭── 📦 RECENT ORDERS ──────────╮\n"
            "╰──────────────────────────────╯\n\n"
        )
        for o in orders:
            status = o['status']
            if status == "COMPLETED":
                badge = "✅ COMPLETED"
            elif status == "PENDING_VERIFICATION":
                badge = "⏳ REVIEWING"
            elif status == "REJECTED":
                reason = o.get('rejection_reason') or 'Unverified'
                badge = f"❌ REJECTED ({html.escape(reason)})"
            else:
                badge = "🟡 PENDING PAYMENT"

            text += (
                f"• <b>Order:</b> <code>#{o['order_id']}</code>\n"
                f"  <b>Service:</b> {html.escape(o['service_title'])}\n"
                f"  <b>Amount:</b> ₹{o['amount']:.0f}\n"
                f"  <b>Status:</b> {badge}\n"
                f"  <b>Date:</b> <i>{o['created_at']}</i>\n\n"
            )

    kb = get_back_to_catalog_keyboard()
    if isinstance(event, CallbackQuery):
        await event.answer()
        try:
            await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await event.message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await event.answer(text, reply_markup=kb, parse_mode="HTML")
