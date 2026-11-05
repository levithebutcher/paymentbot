import html
import uuid
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from config import config
from database import (
    upsert_user,
    get_services,
    get_user_orders,
    get_user_last_bot_msg,
    set_user_last_bot_msg,
    save_support_message
)
from states.order_states import SupportFlow
from keyboards.user_keyboards import (
    get_main_menu_keyboard,
    get_services_keyboard,
    get_back_to_catalog_keyboard,
    get_support_start_keyboard,
    get_cancel_support_keyboard
)
from keyboards.admin_keyboards import get_support_ticket_keyboard

start_router = Router()

@start_router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    if user:
        await upsert_user(user.id, user.username, user.full_name)
        # Delete any previous bot menu/prompt to keep chat spotless
        prev_msg_id = await get_user_last_bot_msg(user.id)
        if prev_msg_id:
            try:
                await message.bot.delete_message(chat_id=user.id, message_id=prev_msg_id)
            except Exception:
                pass

    first_name = html.escape(user.first_name if user else "Member")
    services = await get_services()
    welcome_text = (
        "<blockquote>\n"
        "<b>✦ DIGITAL SERVICES STORE ✦</b>\n"
        f"Welcome, <b>{first_name}</b>!\n\n"
        "Browse our catalog, checkout securely via <b>UPI QR Code</b>, and receive your verified delivery directly in this chat.\n\n"
        "⚡ <i>Instant UPI Activation</i>\n"
        "🔒 <i>Direct Verified Delivery by Admin</i>\n"
        "</blockquote>"
    )

    # 1. Activate the persistent bottom reply keyboard immediately!
    await message.answer(welcome_text, reply_markup=get_main_menu_keyboard(), parse_mode="HTML")

    # 2. Show the interactive services catalog inline keyboard!
    services = await get_services()
    if services:
        catalog_text = (
            "<blockquote>\n"
            "<b>💎 SERVICES CATALOG</b>\n"
            "Select an item below to view full details & pricing:\n"
            "</blockquote>"
        )
        catalog_msg = await message.answer(
            catalog_text,
            reply_markup=get_services_keyboard(services),
            parse_mode="HTML"
        )
        if user:
            await set_user_last_bot_msg(user.id, catalog_msg.message_id)

@start_router.message(Command("help"))
@start_router.message(F.text.in_({"💬 Help & Support", "ℹ️ Help & Support"}))
async def handle_help(message: Message):
    help_text = (
        "<blockquote>\n"
        "<b>💬 HOW TO ORDER & PAY</b>\n"
        "Follow these 4 simple steps:\n"
        "</blockquote>\n\n"
        "1. <b>Choose Service:</b> Tap a service from the catalog.\n"
        "2. <b>Make Payment:</b> Scan the UPI QR Code or copy our UPI ID.\n"
        "3. <b>Send Screenshot:</b> Upload your payment receipt screenshot here.\n"
        "4. <b>Receive Delivery:</b> Our admin verifies payment and delivers directly here!\n\n"
        "💡 <i>Have a question or need personal assistance? Tap 'Send Message to Support' below:</i>"
    )
    await message.answer(help_text, reply_markup=get_support_start_keyboard(), parse_mode="HTML")

@start_router.message(Command("support"))
@start_router.callback_query(F.data == "user_start_support")
async def handle_user_start_support(event: Message | CallbackQuery, state: FSMContext):
    await state.set_state(SupportFlow.waiting_for_query)
    text = (
        "<blockquote>\n"
        "<b>💬 CUSTOMER SUPPORT</b>\n"
        "Need help with an order, payment, or service?\n"
        "</blockquote>\n\n"
        "👉 <b>Type and send your message below:</b>\n"
        "<i>You can send text, a screenshot, or a file. Our support team will review and reply directly to you here!</i>"
    )
    kb = get_cancel_support_keyboard()
    if isinstance(event, CallbackQuery):
        await event.answer()
        sent = await event.message.answer(text, reply_markup=kb, parse_mode="HTML")
        await state.update_data(prompt_msg_id=sent.message_id)
    else:
        sent = await event.answer(text, reply_markup=kb, parse_mode="HTML")
        await state.update_data(prompt_msg_id=sent.message_id)

@start_router.callback_query(F.data == "cancel_user_support")
async def handle_cancel_user_support(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await query.answer("Support request cancelled.")
    try:
        await query.message.delete()
    except Exception:
        pass

@start_router.message(SupportFlow.waiting_for_query)
async def handle_user_submit_support(message: Message, state: FSMContext, bot: Bot):
    user = message.from_user
    data = await state.get_data()
    prompt_msg_id = data.get("prompt_msg_id")
    await state.clear()

    if prompt_msg_id:
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=prompt_msg_id)
        except Exception:
            pass

    ticket_id = f"SUP-{uuid.uuid4().hex[:6].upper()}"

    # Warm confirmation to customer
    user_confirm = (
        "<blockquote>\n"
        f"<b>✅ TICKET SUBMITTED: #{ticket_id}</b>\n"
        "Your message has been forwarded to our support team.\n"
        "</blockquote>\n\n"
        "⏳ <i>Please wait while an admin reviews your query. Their reply will appear directly in this chat!</i>"
    )
    await message.reply(user_confirm, reply_markup=get_main_menu_keyboard(), parse_mode="HTML")

    # Forward ticket card + user content to Admin Group and Admins
    destinations = set()
    if config.ADMIN_GROUP_ID and config.ADMIN_GROUP_ID != 0:
        destinations.add(config.ADMIN_GROUP_ID)
    for aid in config.ADMIN_IDS:
        destinations.add(aid)

    user_str = f"@{user.username}" if user.username else "No username"
    safe_name = html.escape(user.full_name or "Customer")
    safe_user = html.escape(user_str)

    admin_card = (
        "<blockquote>\n"
        "<b>🙋‍♂️ NEW SUPPORT TICKET</b>\n"
        f"<b>Ticket ID:</b> <code>#{ticket_id}</code>\n"
        f"<b>Customer:</b> {safe_name} ({safe_user})\n"
        f"<b>Customer ID:</b> <code>{user.id}</code>\n"
        "</blockquote>\n\n"
        "👉 <i>Swipe-to-reply to this message with your response, or tap below:</i>"
    )
    admin_kb = get_support_ticket_keyboard(ticket_id)

    for dest_id in destinations:
        try:
            card_msg = await bot.send_message(
                chat_id=dest_id,
                text=admin_card,
                reply_markup=admin_kb,
                parse_mode="HTML"
            )
            # Copy customer's message (text/photo/document/video) right below card
            copied_msg = await message.copy_to(chat_id=dest_id)

            # Map BOTH so swipe-to-reply works on either!
            await save_support_message(card_msg.message_id, dest_id, user.id, ticket_id)
            await save_support_message(copied_msg.message_id, dest_id, user.id, ticket_id)
        except Exception as e:
            print(f"Error forwarding support query to {dest_id}: {e}")

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

@start_router.message(Command("orders"))
@start_router.message(F.text == "📦 My Orders")
@start_router.callback_query(F.data == "view_my_orders")
async def handle_my_orders(event: Message | CallbackQuery):
    user_id = event.from_user.id
    orders = await get_user_orders(user_id)

    if not orders:
        text = (
            "<blockquote>\n"
            "<b>📦 YOUR ORDERS</b>\n"
            "No orders found yet.\n"
            "</blockquote>\n\n"
            "Browse our catalog to make your first purchase!"
        )
    else:
        text = (
            "<blockquote>\n"
            "<b>📦 YOUR RECENT ORDERS</b>\n"
            "</blockquote>\n\n"
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
