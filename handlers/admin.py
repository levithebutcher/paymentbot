import asyncio
import os
import re
from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter
from PIL import Image, ImageOps
from config import config
from database import (
    approve_order,
    reject_order,
    get_order,
    get_services,
    get_service,
    add_service,
    update_service_price,
    update_service_delivery,
    update_service_title,
    toggle_service_status,
    delete_service,
    get_all_users,
    get_connection,
    get_setting,
    set_setting,
    get_order_by_message
)
from states.order_states import AddServiceFlow, EditServiceFlow, BroadcastFlow, EditPaymentFlow
from keyboards.admin_keyboards import (
    get_admin_verification_keyboard,
    get_admin_rejection_reasons_keyboard,
    get_admin_dashboard_keyboard,
    get_payment_settings_keyboard,
    get_services_management_keyboard,
    get_service_actions_keyboard,
    get_broadcast_confirm_keyboard,
    get_cancel_admin_flow_keyboard,
    REJECTION_REASONS
)
from keyboards.user_keyboards import get_retry_keyboard

admin_router = Router()

def is_admin_authorized(user_id: int) -> bool:
    """Check if user is authorized as an admin."""
    if not config.ADMIN_IDS:
        return True
    return user_id in config.ADMIN_IDS

# ==========================================
# 1. PAYMENT VERIFICATION HANDLERS (ADMIN GROUP)
# ==========================================

@admin_router.callback_query(F.data.startswith("admin_approve:"))
async def handle_admin_approve(query: CallbackQuery, bot: Bot):
    admin = query.from_user
    order_id = query.data.split(":")[1]

    order = await get_order(order_id)
    if not order:
        await query.answer("⚠️ Order not found in database.", show_alert=True)
        return

    if order["status"] == "COMPLETED":
        await query.answer("ℹ️ This order is already approved.", show_alert=True)
        return

    updated_order = await approve_order(order_id, admin.id)
    if not updated_order:
        await query.answer("⚠️ Could not update order (status changed or not pending).", show_alert=True)
        return

    await query.answer("✅ Order approved successfully!")

    admin_name = f"@{admin.username}" if admin.username else admin.full_name
    approved_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    current_caption = query.message.caption or ""
    new_caption = (
        current_caption
        + f"\n\n━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ **STATUS: APPROVED**\n"
        f"👮 **Verified by:** {admin_name} (`{admin.id}`)\n"
        f"🕒 **Time:** {approved_time}"
    )

    try:
        await query.message.edit_caption(
            caption=new_caption,
            reply_markup=None,
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Could not edit admin message caption: {e}")

    # Deliver service to the user
    user_id = order["user_id"]
    delivery_msg = (
        "🎉 **PAYMENT VERIFIED & APPROVED!**\n\n"
        f"🧾 **Order ID:** `#{order_id}`\n"
        f"📌 **Service:** {order['service_title']}\n"
        f"💰 **Amount Paid:** ₹{order['amount']:.0f}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🎁 **Your Service / Access Details:**\n\n"
        f"{order['delivery_content']}\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🙏 Thank you for your purchase! If you have any questions, feel free to reach out to our support team."
    )

    try:
        await bot.send_message(
            chat_id=user_id,
            text=delivery_msg,
            parse_mode="Markdown",
            disable_web_page_preview=False
        )
    except Exception as e:
        print(f"Could not deliver service to user {user_id}: {e}")

@admin_router.callback_query(F.data.startswith("admin_reject_menu:"))
async def handle_admin_reject_menu(query: CallbackQuery):
    order_id = query.data.split(":")[1]
    order = await get_order(order_id)
    if not order:
        await query.answer("⚠️ Order not found.", show_alert=True)
        return

    if order["status"] != "PENDING_VERIFICATION":
        await query.answer(f"ℹ️ Order is already {order['status']}.", show_alert=True)
        return

    await query.answer()
    reasons_kb = get_admin_rejection_reasons_keyboard(order_id)
    await query.message.edit_reply_markup(reply_markup=reasons_kb)

@admin_router.callback_query(F.data.startswith("admin_back_to_verify:"))
async def handle_admin_back_to_verify(query: CallbackQuery):
    order_id = query.data.split(":")[1]
    await query.answer()
    verify_kb = get_admin_verification_keyboard(order_id)
    await query.message.edit_reply_markup(reply_markup=verify_kb)

@admin_router.callback_query(F.data.startswith("admin_reject_reason:"))
async def handle_admin_reject_reason(query: CallbackQuery, bot: Bot):
    _, order_id, reason_code = query.data.split(":")
    admin = query.from_user

    order = await get_order(order_id)
    if not order:
        await query.answer("⚠️ Order not found.", show_alert=True)
        return

    if order["status"] != "PENDING_VERIFICATION":
        await query.answer(f"ℹ️ Order is already {order['status']}.", show_alert=True)
        return

    reason_text = REJECTION_REASONS.get(reason_code, "Payment proof could not be verified")
    await reject_order(order_id, admin.id, reason_text)

    await query.answer("❌ Order marked as Rejected.")

    admin_name = f"@{admin.username}" if admin.username else admin.full_name
    rejected_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    current_caption = query.message.caption or ""
    new_caption = (
        current_caption
        + f"\n\n━━━━━━━━━━━━━━━━━━━━\n"
        f"❌ **STATUS: REJECTED**\n"
        f"👮 **Reviewed by:** {admin_name}\n"
        f"⚠️ **Reason:** {reason_text}\n"
        f"🕒 **Time:** {rejected_time}"
    )

    try:
        await query.message.edit_caption(
            caption=new_caption,
            reply_markup=None,
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Could not edit admin message caption: {e}")

    user_id = order["user_id"]
    user_rejection_text = (
        "❌ **PAYMENT VERIFICATION FAILED**\n\n"
        f"🧾 **Order ID:** `#{order_id}`\n"
        f"📌 **Service:** {order['service_title']}\n\n"
        f"⚠️ **Reason for rejection:**\n_{reason_text}_\n\n"
        "💡 *What to do next?*\n"
        "• Please verify in your bank/UPI app that the money was actually debited.\n"
        "• Ensure you uploaded a clear, uncropped screenshot with visible UTR.\n"
        "• You can try ordering again or contact support for help."
    )

    retry_kb = get_retry_keyboard(order["service_id"])
    try:
        await bot.send_message(
            chat_id=user_id,
            text=user_rejection_text,
            reply_markup=retry_kb,
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Could not send rejection message to user {user_id}: {e}")

@admin_router.message(F.reply_to_message)
async def handle_admin_reply_delivery(message: Message, bot: Bot):
    """
    Allows Admin to reply to any order verification card with a file, document, photo,
    or message, and the bot automatically delivers it directly to the buyer's Telegram chat!
    """
    if not is_admin_authorized(message.from_user.id):
        return

    replied_msg_id = message.reply_to_message.message_id
    chat_id = message.chat.id
    order = await get_order_by_message(replied_msg_id, chat_id)
    if not order:
        return  # The replied message is not an active order card

    if order["status"] == "COMPLETED":
        await message.reply("ℹ️ This order is already marked as COMPLETED.")
        return

    user_id = order["user_id"]
    order_id = order["order_id"]

    intro = (
        "🎉 **PAYMENT VERIFIED & ORDER DELIVERED!**\n\n"
        f"🧾 **Order ID:** `#{order_id}`\n"
        f"📌 **Service:** {order['service_title']}\n"
        f"💰 **Amount Paid:** ₹{order['amount']:.0f}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🎁 **Here is your delivery file / access content from our admin:**\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

    try:
        await bot.send_message(chat_id=user_id, text=intro, parse_mode="Markdown")
        # Copy the exact admin message (Document, Photo, Audio, Video, or Text) directly to the buyer!
        await message.copy_to(chat_id=user_id)
    except Exception as e:
        await message.reply(f"⚠️ Could not deliver message to user {user_id}: {e}")
        return

    # Mark order as completed
    await approve_order(order_id, message.from_user.id)

    admin_name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name
    await message.reply(
        f"✅ **Delivered successfully to customer!**\n\n"
        f"👤 Customer: {order['full_name']} (@{order['username']})\n"
        f"🆔 Customer ID: `{user_id}`\n"
        f"🧾 Order ID: `#{order_id}`\n"
        f"👮 Verified by: {admin_name}\n\n"
        "Order status updated to **COMPLETED**.",
        parse_mode="Markdown"
    )

# ==========================================
# 2. INTERACTIVE ADMIN DASHBOARD & NAVIGATION
# ==========================================

@admin_router.message(Command("setgroup"), F.chat.type.in_({"group", "supergroup"}))
async def handle_set_group(message: Message):
    user_id = message.from_user.id
    if not is_admin_authorized(user_id):
        await message.reply("⛔ Only authorized admins can register this group.")
        return

    group_id = message.chat.id
    config.ADMIN_GROUP_ID = group_id
    
    # Also update .env file if it exists so it persists across restarts
    try:
        if os.path.exists(".env"):
            with open(".env", "r", encoding="utf-8") as f:
                content = f.read()
            if "ADMIN_GROUP_ID=" in content:
                content = re.sub(r"ADMIN_GROUP_ID=.*", f"ADMIN_GROUP_ID={group_id}", content)
            else:
                content += f"\nADMIN_GROUP_ID={group_id}\n"
            with open(".env", "w", encoding="utf-8") as f:
                f.write(content)
    except Exception as e:
        print(f"Could not persist ADMIN_GROUP_ID to .env: {e}")

    await message.reply(
        "✅ **Admin Verification Group Registered!**\n\n"
        f"🏷️ **Group Title:** {message.chat.title}\n"
        f"🆔 **Group ID:** `{group_id}`\n\n"
        "All customer payment verification requests will now appear in this group with [Approve] and [Reject] buttons.",
        parse_mode="Markdown"
    )

@admin_router.message(Command("admin"))
async def handle_admin_panel(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    if not is_admin_authorized(user_id):
        await message.reply("⛔ You are not authorized to access the admin panel.")
        return

    upi_id = await get_setting("upi_id", config.UPI_ID)
    text = (
        "🛠️ **ADMIN CONTROL DASHBOARD**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📲 **Current Active UPI:** `{upi_id}`\n\n"
        "👇 **Select an option to manage:**\n"
        "1️⃣ **Payment Method & QR Code** — Change UPI ID or QR image\n"
        "2️⃣ **Services Catalog** — Add/edit services, pricing & delivery links"
    )
    await message.reply(text, reply_markup=get_admin_dashboard_keyboard(), parse_mode="Markdown")

@admin_router.callback_query(F.data == "admin_nav:dashboard")
async def nav_dashboard(query: CallbackQuery, state: FSMContext):
    await state.clear()
    if not is_admin_authorized(query.from_user.id):
        await query.answer("⛔ Unauthorized", show_alert=True)
        return

    await query.answer()
    upi_id = await get_setting("upi_id", config.UPI_ID)
    text = (
        "🛠️ **ADMIN CONTROL DASHBOARD**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📲 **Current Active UPI:** `{upi_id}`\n\n"
        "👇 **Select an option to manage:**\n"
        "1️⃣ **Payment Method & QR Code** — Change UPI ID or QR image\n"
        "2️⃣ **Services Catalog** — Add/edit services, pricing & delivery links"
    )
    await query.message.edit_text(text, reply_markup=get_admin_dashboard_keyboard(), parse_mode="Markdown")

# ==========================================
# PAYMENT SETTINGS MANAGEMENT (UPI & QR)
# ==========================================

@admin_router.callback_query(F.data == "admin_nav:payment_settings")
async def nav_payment_settings(query: CallbackQuery, state: FSMContext):
    await state.clear()
    if not is_admin_authorized(query.from_user.id):
        await query.answer("⛔ Unauthorized", show_alert=True)
        return

    await query.answer()
    upi_id = await get_setting("upi_id", config.UPI_ID)
    upi_name = await get_setting("upi_name", config.UPI_NAME)
    qr_path = await get_setting("qr_image_path", config.QR_IMAGE_PATH)
    qr_exists = "✅ File Active" if os.path.exists(qr_path) else "⚠️ File Missing"

    text = (
        "💳 **PAYMENT METHODS & QR SETTINGS**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📲 **UPI ID:** `{upi_id}`\n"
        f"👤 **Payee Name:** {upi_name}\n"
        f"🖼️ **QR Image:** {qr_exists} (`{qr_path}`)\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Select what you want to update:"
    )
    await query.message.edit_text(text, reply_markup=get_payment_settings_keyboard(), parse_mode="Markdown")

@admin_router.callback_query(F.data == "admin_pay:change_upi")
async def start_change_upi(query: CallbackQuery, state: FSMContext):
    if not is_admin_authorized(query.from_user.id):
        await query.answer("⛔ Unauthorized", show_alert=True)
        return

    await state.set_state(EditPaymentFlow.waiting_for_upi_id)
    await query.answer()
    text = (
        "🔄 **CHANGE UPI ID**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Please send the new UPI ID (e.g. `yourname@okhdfcbank` or `9876543210@upi`):"
    )
    await query.message.edit_text(text, reply_markup=get_cancel_admin_flow_keyboard(), parse_mode="Markdown")

@admin_router.message(EditPaymentFlow.waiting_for_upi_id, F.text)
async def finish_change_upi(message: Message, state: FSMContext):
    new_upi = message.text.strip()
    if "@" not in new_upi or len(new_upi) < 5:
        await message.reply("⚠️ Invalid UPI ID format. It should look like `username@bank` or `number@upi`. Please try again:")
        return

    await set_setting("upi_id", new_upi)
    config.UPI_ID = new_upi

    # Persist to .env if present
    try:
        if os.path.exists(".env"):
            with open(".env", "r", encoding="utf-8") as f:
                env_text = f.read()
            if "UPI_ID=" in env_text:
                env_text = re.sub(r"UPI_ID=.*", f"UPI_ID={new_upi}", env_text)
            else:
                env_text += f"\nUPI_ID={new_upi}\n"
            with open(".env", "w", encoding="utf-8") as f:
                f.write(env_text)
    except Exception as e:
        print(f"Could not update .env with new UPI_ID: {e}")

    await state.clear()
    await message.reply(
        f"✅ **UPI ID updated successfully!**\nNew UPI ID: `{new_upi}`\n\nAll future customer orders will now display this UPI ID.",
        reply_markup=get_admin_dashboard_keyboard(),
        parse_mode="Markdown"
    )

@admin_router.callback_query(F.data == "admin_pay:change_name")
async def start_change_name(query: CallbackQuery, state: FSMContext):
    if not is_admin_authorized(query.from_user.id):
        await query.answer("⛔ Unauthorized", show_alert=True)
        return

    await state.set_state(EditPaymentFlow.waiting_for_payee_name)
    await query.answer()
    text = (
        "👤 **CHANGE PAYEE / MERCHANT NAME**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Please send the new Payee Name (e.g. `My Store` or `John Doe`):"
    )
    await query.message.edit_text(text, reply_markup=get_cancel_admin_flow_keyboard(), parse_mode="Markdown")

@admin_router.message(EditPaymentFlow.waiting_for_payee_name, F.text)
async def finish_change_name(message: Message, state: FSMContext):
    new_name = message.text.strip()
    await set_setting("upi_name", new_name)
    config.UPI_NAME = new_name
    await state.clear()
    await message.reply(
        f"✅ **Payee Name updated successfully!**\nNew Name: **{new_name}**",
        reply_markup=get_admin_dashboard_keyboard(),
        parse_mode="Markdown"
    )

@admin_router.callback_query(F.data == "admin_pay:change_qr")
async def start_change_qr(query: CallbackQuery, state: FSMContext):
    if not is_admin_authorized(query.from_user.id):
        await query.answer("⛔ Unauthorized", show_alert=True)
        return

    await state.set_state(EditPaymentFlow.waiting_for_qr_photo)
    await query.answer()
    text = (
        "🖼️ **UPLOAD NEW QR CODE IMAGE**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Please send the new QR code image as a **photo** in this chat.\n\n"
        "✨ *Note: The bot will automatically add clean white edge padding so no corners or edges get cut off on mobile screens.*"
    )
    await query.message.edit_text(text, reply_markup=get_cancel_admin_flow_keyboard(), parse_mode="Markdown")

@admin_router.message(EditPaymentFlow.waiting_for_qr_photo, F.photo)
async def finish_change_qr(message: Message, state: FSMContext, bot: Bot):
    photo = message.photo[-1]
    temp_path = "assets/qr_temp_download.png"
    final_path = "assets/qr_code.png"

    os.makedirs("assets", exist_ok=True)
    await bot.download(photo, destination=temp_path)

    try:
        # Open and apply 60px edge padding to prevent Telegram corner cut-off
        img = Image.open(temp_path).convert("RGB")
        padded = ImageOps.expand(img, border=60, fill="white")
        padded.save(final_path)
        if os.path.exists(temp_path):
            os.remove(temp_path)

        await set_setting("qr_image_path", final_path)
        await state.clear()

        await message.reply(
            "✅ **QR Code image updated successfully!**\n\n"
            "Clean edge padding has been applied to ensure clear scannability on all devices. "
            "All new customer payment orders will now display this QR code image.",
            reply_markup=get_admin_dashboard_keyboard(),
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.reply(f"⚠️ Failed to process image: {e}. Please try uploading again:")

@admin_router.callback_query(F.data == "admin_nav:close")
async def nav_close(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await query.answer("Closed")
    await query.message.delete()

@admin_router.callback_query(F.data == "admin_nav:stats")
async def nav_stats(query: CallbackQuery):
    if not is_admin_authorized(query.from_user.id):
        await query.answer("⛔ Unauthorized", show_alert=True)
        return

    await query.answer()
    async with get_connection() as conn:
        async with conn.execute("SELECT COUNT(*) as total_users FROM users") as cur:
            users_count = (await cur.fetchone())["total_users"]

        async with conn.execute(
            "SELECT COUNT(*) as total, SUM(amount) as revenue FROM orders WHERE status = 'COMPLETED'"
        ) as cur:
            comp = await cur.fetchone()
            completed_count = comp["total"] or 0
            revenue = comp["revenue"] or 0.0

        async with conn.execute(
            "SELECT COUNT(*) as pending FROM orders WHERE status = 'PENDING_VERIFICATION'"
        ) as cur:
            pending_count = (await cur.fetchone())["pending"] or 0

        async with conn.execute(
            "SELECT COUNT(*) as rejected FROM orders WHERE status = 'REJECTED'"
        ) as cur:
            rejected_count = (await cur.fetchone())["rejected"] or 0

    stats_text = (
        "📊 **BOT LIVE ANALYTICS**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 **Total Registered Users:** {users_count}\n"
        f"⏳ **Pending Verifications:** {pending_count}\n"
        f"✅ **Completed Orders:** {completed_count}\n"
        f"❌ **Rejected Orders:** {rejected_count}\n"
        f"💰 **Total Approved Revenue:** ₹{revenue:,.2f}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ **Admin Group ID:** `{config.ADMIN_GROUP_ID}`\n"
        f"📲 **Configured UPI ID:** `{config.UPI_ID}`\n"
    )
    kb = get_admin_dashboard_keyboard()
    await query.message.edit_text(stats_text, reply_markup=kb, parse_mode="Markdown")

# ==========================================
# 3. SERVICE CATALOG MANAGEMENT
# ==========================================

@admin_router.callback_query(F.data == "admin_nav:services")
async def nav_manage_services(query: CallbackQuery, state: FSMContext):
    await state.clear()
    if not is_admin_authorized(query.from_user.id):
        await query.answer("⛔ Unauthorized", show_alert=True)
        return

    await query.answer()
    services = await get_services(active_only=False)
    text = (
        "📋 **SERVICES CATALOG MANAGER**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🟢 = Active (Visible to buyers)\n"
        "🔴 = Inactive / Hidden\n\n"
        "Click on any service below to edit its **Price, Delivery Content, Title**, or toggle visibility:"
    )
    await query.message.edit_text(text, reply_markup=get_services_management_keyboard(services), parse_mode="Markdown")

@admin_router.callback_query(F.data.startswith("admin_svc:"))
async def handle_service_details(query: CallbackQuery, state: FSMContext):
    await state.clear()
    service_id = query.data.split(":")[1]
    service = await get_service(service_id)

    if not service:
        await query.answer("⚠️ Service not found.", show_alert=True)
        return

    await query.answer()
    status_str = "🟢 Active (Visible)" if service["is_active"] == 1 else "🔴 Inactive (Hidden)"
    text = (
        f"🏷️ **SERVICE DETAILS: {service['title']}**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 **ID:** `{service['service_id']}`\n"
        f"💰 **Price:** ₹{service['price_inr']:.0f}\n"
        f"📶 **Status:** {status_str}\n\n"
        f"📝 **Description:**\n{service['description']}\n\n"
        f"🎁 **Delivery Content / Link:**\n`{service['delivery_content']}`\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Choose an action to modify this service:"
    )
    kb = get_service_actions_keyboard(service_id, service["is_active"])
    await query.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

@admin_router.callback_query(F.data.startswith("svc_action:toggle:"))
async def handle_toggle_service(query: CallbackQuery):
    service_id = query.data.split(":")[2]
    new_status = await toggle_service_status(service_id)
    if new_status is None:
        await query.answer("⚠️ Service not found.", show_alert=True)
        return

    status_word = "Activated (Visible)" if new_status == 1 else "Deactivated (Hidden)"
    await query.answer(f"Service {status_word}!")

    # Refresh details view
    service = await get_service(service_id)
    status_str = "🟢 Active (Visible)" if service["is_active"] == 1 else "🔴 Inactive (Hidden)"
    text = (
        f"🏷️ **SERVICE DETAILS: {service['title']}**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 **ID:** `{service['service_id']}`\n"
        f"💰 **Price:** ₹{service['price_inr']:.0f}\n"
        f"📶 **Status:** {status_str}\n\n"
        f"📝 **Description:**\n{service['description']}\n\n"
        f"🎁 **Delivery Content / Link:**\n`{service['delivery_content']}`\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Choose an action to modify this service:"
    )
    kb = get_service_actions_keyboard(service_id, service["is_active"])
    await query.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

@admin_router.callback_query(F.data.startswith("svc_action:delete:"))
async def handle_delete_service(query: CallbackQuery):
    service_id = query.data.split(":")[2]
    success = await delete_service(service_id)
    if success:
        await query.answer("🗑️ Service removed/deactivated.")
    else:
        await query.answer("⚠️ Could not delete service.", show_alert=True)

    services = await get_services(active_only=False)
    text = (
        "📋 **SERVICES CATALOG MANAGER**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Service was updated/removed.\n\n"
        "Select a service to manage:"
    )
    await query.message.edit_text(text, reply_markup=get_services_management_keyboard(services), parse_mode="Markdown")

# --- EDIT PRICE FLOW ---
@admin_router.callback_query(F.data.startswith("svc_action:price:"))
async def edit_price_start(query: CallbackQuery, state: FSMContext):
    service_id = query.data.split(":")[2]
    await state.set_state(EditServiceFlow.waiting_for_new_price)
    await state.update_data(service_id=service_id)
    await query.answer()
    text = (
        f"💰 **Edit Price for Service:** `{service_id}`\n\n"
        "Please type and send the **new price in INR** (e.g. `249` or `499`):"
    )
    await query.message.edit_text(text, reply_markup=get_cancel_admin_flow_keyboard(), parse_mode="Markdown")

@admin_router.message(EditServiceFlow.waiting_for_new_price, F.text)
async def edit_price_finish(message: Message, state: FSMContext):
    raw = message.text.strip().replace("₹", "").replace(",", "")
    try:
        new_price = float(raw)
        if new_price <= 0:
            raise ValueError
    except ValueError:
        await message.reply("⚠️ Invalid amount. Please enter a valid positive number (e.g. `299`):")
        return

    data = await state.get_data()
    service_id = data.get("service_id")
    await update_service_price(service_id, new_price)
    await state.clear()

    await message.reply(
        f"✅ **Price updated successfully!**\nService `{service_id}` is now priced at **₹{new_price:.0f}**.",
        reply_markup=get_admin_dashboard_keyboard(),
        parse_mode="Markdown"
    )

# --- EDIT DELIVERY CONTENT FLOW ---
@admin_router.callback_query(F.data.startswith("svc_action:delivery:"))
async def edit_delivery_start(query: CallbackQuery, state: FSMContext):
    service_id = query.data.split(":")[2]
    await state.set_state(EditServiceFlow.waiting_for_new_delivery)
    await state.update_data(service_id=service_id)
    await query.answer()
    text = (
        f"🎁 **Edit Delivery Content for Service:** `{service_id}`\n\n"
        "Please send the new invite link, file URL, or instructions that will be delivered to the buyer upon payment approval:"
    )
    await query.message.edit_text(text, reply_markup=get_cancel_admin_flow_keyboard(), parse_mode="Markdown")

@admin_router.message(EditServiceFlow.waiting_for_new_delivery, F.text)
async def edit_delivery_finish(message: Message, state: FSMContext):
    new_delivery = message.text.strip()
    data = await state.get_data()
    service_id = data.get("service_id")
    await update_service_delivery(service_id, new_delivery)
    await state.clear()

    await message.reply(
        f"✅ **Delivery content updated successfully!**\nNew content for `{service_id}`:\n\n{new_delivery}",
        reply_markup=get_admin_dashboard_keyboard(),
        parse_mode="Markdown"
    )

# --- EDIT TITLE FLOW ---
@admin_router.callback_query(F.data.startswith("svc_action:title:"))
async def edit_title_start(query: CallbackQuery, state: FSMContext):
    service_id = query.data.split(":")[2]
    await state.set_state(EditServiceFlow.waiting_for_new_title)
    await state.update_data(service_id=service_id)
    await query.answer()
    text = (
        f"📝 **Edit Title for Service:** `{service_id}`\n\n"
        "Please send the new display title for this service (e.g. `💎 VIP Signals (Lifetime)`):"
    )
    await query.message.edit_text(text, reply_markup=get_cancel_admin_flow_keyboard(), parse_mode="Markdown")

@admin_router.message(EditServiceFlow.waiting_for_new_title, F.text)
async def edit_title_finish(message: Message, state: FSMContext):
    new_title = message.text.strip()
    data = await state.get_data()
    service_id = data.get("service_id")
    await update_service_title(service_id, new_title)
    await state.clear()

    await message.reply(
        f"✅ **Title updated successfully!**\nNew Title: **{new_title}**",
        reply_markup=get_admin_dashboard_keyboard(),
        parse_mode="Markdown"
    )

# ==========================================
# 4. ADD NEW SERVICE WIZARD
# ==========================================

@admin_router.callback_query(F.data == "admin_nav:add_service")
async def add_service_step1(query: CallbackQuery, state: FSMContext):
    if not is_admin_authorized(query.from_user.id):
        await query.answer("⛔ Unauthorized", show_alert=True)
        return

    await state.set_state(AddServiceFlow.waiting_for_id)
    await query.answer()
    text = (
        "➕ **ADD NEW SERVICE WIZARD (Step 1/5)**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Please enter a **short, unique ID** for this service (letters, numbers, underscore only; e.g. `vip_pro`, `course_2026`):"
    )
    await query.message.edit_text(text, reply_markup=get_cancel_admin_flow_keyboard(), parse_mode="Markdown")

@admin_router.message(AddServiceFlow.waiting_for_id, F.text)
async def add_service_step2(message: Message, state: FSMContext):
    raw_id = message.text.strip().lower()
    if not re.match(r"^[a-z0-9_]{3,30}$", raw_id):
        await message.reply("⚠️ Invalid ID format. Use 3-30 lowercase characters with numbers/underscores (e.g. `crypto_vip`):")
        return

    existing = await get_service(raw_id)
    if existing:
        await message.reply(f"⚠️ A service with ID `{raw_id}` already exists. Please pick a different ID:")
        return

    await state.update_data(new_svc_id=raw_id)
    await state.set_state(AddServiceFlow.waiting_for_title)
    await message.reply("📝 **Step 2/5:** Send the **Title** of the service (e.g. `💎 VIP Master Channel`):")

@admin_router.message(AddServiceFlow.waiting_for_title, F.text)
async def add_service_step3(message: Message, state: FSMContext):
    title = message.text.strip()
    await state.update_data(new_svc_title=title)
    await state.set_state(AddServiceFlow.waiting_for_description)
    await message.reply("📄 **Step 3/5:** Send a **Description** explaining what the buyer receives:")

@admin_router.message(AddServiceFlow.waiting_for_description, F.text)
async def add_service_step4(message: Message, state: FSMContext):
    desc = message.text.strip()
    await state.update_data(new_svc_desc=desc)
    await state.set_state(AddServiceFlow.waiting_for_price)
    await message.reply("💰 **Step 4/5:** Send the **Price in INR** (e.g. `199`):")

@admin_router.message(AddServiceFlow.waiting_for_price, F.text)
async def add_service_step5(message: Message, state: FSMContext):
    raw = message.text.strip().replace("₹", "").replace(",", "")
    try:
        price = float(raw)
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.reply("⚠️ Please enter a valid numeric price (e.g. `199`):")
        return

    await state.update_data(new_svc_price=price)
    await state.set_state(AddServiceFlow.waiting_for_delivery)
    await message.reply(
        "🎁 **Step 5/5:** Send the **Delivery Content**\n"
        "(This will be sent to the user immediately after payment is approved; e.g. Private channel invite link, Google Drive link, or instructions):"
    )

@admin_router.message(AddServiceFlow.waiting_for_delivery, F.text)
async def add_service_finish(message: Message, state: FSMContext):
    delivery = message.text.strip()
    data = await state.get_data()
    svc_id = data["new_svc_id"]
    title = data["new_svc_title"]
    desc = data["new_svc_desc"]
    price = data["new_svc_price"]

    success = await add_service(svc_id, title, desc, price, delivery)
    await state.clear()

    if success:
        text = (
            "🎉 **NEW SERVICE CREATED & ACTIVATED!**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 **ID:** `{svc_id}`\n"
            f"🏷️ **Title:** {title}\n"
            f"💰 **Price:** ₹{price:.0f}\n\n"
            "It is now live in the `/start` and `🛍️ View Services` catalog for all customers!"
        )
    else:
        text = "⚠️ An error occurred while creating the service in the database."

    await message.reply(text, reply_markup=get_admin_dashboard_keyboard(), parse_mode="Markdown")

# ==========================================
# 5. BROADCAST SYSTEM (ALL REGISTERED USERS)
# ==========================================

@admin_router.callback_query(F.data == "admin_nav:broadcast")
async def broadcast_start(query: CallbackQuery, state: FSMContext):
    if not is_admin_authorized(query.from_user.id):
        await query.answer("⛔ Unauthorized", show_alert=True)
        return

    await state.set_state(BroadcastFlow.waiting_for_content)
    await query.answer()
    text = (
        "📢 **BROADCAST ANNOUNCEMENT TO ALL USERS**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Send the message you want to broadcast.\n\n"
        "• You can send **plain text**.\n"
        "• Or send a **photo with a caption**.\n\n"
        "Before sending, bot will show you a preview and ask for confirmation."
    )
    await query.message.edit_text(text, reply_markup=get_cancel_admin_flow_keyboard(), parse_mode="Markdown")

@admin_router.message(BroadcastFlow.waiting_for_content, F.photo)
async def broadcast_receive_photo(message: Message, state: FSMContext):
    photo_file_id = message.photo[-1].file_id
    caption = message.caption or ""
    all_users = await get_all_users()

    await state.update_data(
        content_type="photo",
        photo_file_id=photo_file_id,
        caption=caption,
        total_targets=len(all_users)
    )
    await state.set_state(BroadcastFlow.waiting_for_confirmation)

    preview_text = (
        f"📢 **BROADCAST PREVIEW (Photo Message):**\n\n"
        f"📝 **Caption:**\n{caption if caption else '*(No caption)*'}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 **Audience:** `{len(all_users)}` registered users.\n\n"
        "Ready to send to all users?"
    )
    await message.reply_photo(
        photo=photo_file_id,
        caption=preview_text,
        reply_markup=get_broadcast_confirm_keyboard(),
        parse_mode="Markdown"
    )

@admin_router.message(BroadcastFlow.waiting_for_content, F.text)
async def broadcast_receive_text(message: Message, state: FSMContext):
    text_content = message.text
    all_users = await get_all_users()

    await state.update_data(
        content_type="text",
        text_content=text_content,
        total_targets=len(all_users)
    )
    await state.set_state(BroadcastFlow.waiting_for_confirmation)

    preview_text = (
        "📢 **BROADCAST PREVIEW:**\n\n"
        f"{text_content}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 **Audience:** `{len(all_users)}` registered users.\n\n"
        "Ready to send to all users?"
    )
    await message.reply(preview_text, reply_markup=get_broadcast_confirm_keyboard(), parse_mode="Markdown")

@admin_router.callback_query(F.data == "broadcast_action:confirm")
async def broadcast_execute(query: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    content_type = data.get("content_type")

    if not content_type:
        await query.answer("⚠️ Broadcast session expired.", show_alert=True)
        await state.clear()
        return

    all_users = await get_all_users()
    total = len(all_users)

    if total == 0:
        await query.answer("ℹ️ No registered users to broadcast to.", show_alert=True)
        await state.clear()
        return

    await query.answer("🚀 Starting broadcast...")
    status_msg = await query.message.answer(f"⏳ **Broadcasting in progress...** (0/{total})")
    await state.clear()

    sent_count = 0
    blocked_count = 0

    for idx, uid in enumerate(all_users, 1):
        try:
            if content_type == "photo":
                await bot.send_photo(
                    chat_id=uid,
                    photo=data["photo_file_id"],
                    caption=data.get("caption", ""),
                    parse_mode="Markdown"
                )
            else:
                await bot.send_message(
                    chat_id=uid,
                    text=data["text_content"],
                    parse_mode="Markdown"
                )
            sent_count += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            blocked_count += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                if content_type == "photo":
                    await bot.send_photo(chat_id=uid, photo=data["photo_file_id"], caption=data.get("caption", ""))
                else:
                    await bot.send_message(chat_id=uid, text=data["text_content"])
                sent_count += 1
            except Exception:
                blocked_count += 1
        except Exception:
            blocked_count += 1

        # Safe rate-limiting delay between sends to prevent Telegram flood penalties
        await asyncio.sleep(0.04)

        # Update progress every 25 users
        if idx % 25 == 0 or idx == total:
            try:
                await status_msg.edit_text(f"⏳ **Broadcasting in progress...** ({idx}/{total})")
            except Exception:
                pass

    report = (
        "🎉 **BROADCAST COMPLETED!**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ **Delivered:** {sent_count} users\n"
        f"🚫 **Blocked / Failed:** {blocked_count} users\n"
        f"👥 **Total Audience:** {total} users\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )
    await status_msg.edit_text(report, reply_markup=get_admin_dashboard_keyboard(), parse_mode="Markdown")

@admin_router.callback_query(F.data == "broadcast_action:cancel")
async def broadcast_cancel(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await query.answer("Broadcast cancelled.")
    await query.message.edit_text(
        "❌ **Broadcast cancelled.**",
        reply_markup=get_admin_dashboard_keyboard(),
        parse_mode="Markdown"
    )
