import asyncio
import os
import re
import html
import uuid
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
    get_order_by_message,
    get_admin_order_messages,
    delete_admin_order_messages
)
from states.order_states import (
    AddServiceFlow,
    EditServiceFlow,
    BroadcastFlow,
    EditPaymentFlow,
    AdminDeliveryFlow
)
from keyboards.admin_keyboards import (
    get_admin_verification_keyboard,
    get_admin_rejection_reasons_keyboard,
    get_admin_dashboard_keyboard,
    get_payment_settings_keyboard,
    get_services_management_keyboard,
    get_service_actions_keyboard,
    get_broadcast_confirm_keyboard,
    get_cancel_admin_flow_keyboard,
    get_cancel_delivery_keyboard,
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
# 1. PAYMENT VERIFICATION & DELIVERY HANDLERS
# ==========================================

@admin_router.callback_query(F.data.startswith("admin_deliver_flow:") | F.data.startswith("admin_approve:"))
async def handle_admin_deliver_flow_start(query: CallbackQuery, state: FSMContext):
    if not is_admin_authorized(query.from_user.id):
        await query.answer("⛔ Unauthorized", show_alert=True)
        return

    order_id = query.data.split(":")[1]
    order = await get_order(order_id)
    if not order:
        await query.answer("⚠️ Order not found in database.", show_alert=True)
        return

    if order["status"] == "COMPLETED":
        await query.answer("ℹ️ This order is already COMPLETED.", show_alert=True)
        return

    await query.answer()
    await state.set_state(AdminDeliveryFlow.waiting_for_delivery_item)
    await state.update_data(
        order_id=order_id,
        buyer_id=order["user_id"],
        service_title=order["service_title"],
        card_msg_id=query.message.message_id,
        card_chat_id=query.message.chat.id
    )

    safe_title = html.escape(order["service_title"])
    prompt_text = (
        "<blockquote>\n"
        "<b>📤 ORDER DELIVERY</b>\n"
        f"<b>Order ID:</b> <code>#{order_id}</code>\n"
        f"<b>Customer ID:</b> <code>{order['user_id']}</code>\n"
        f"<b>Service:</b> {safe_title}\n"
        "</blockquote>\n\n"
        "👉 <b>Send the delivery file or content now:</b>\n"
        "• Send a Document (PDF, ZIP, APK, etc.)\n"
        "• Or send a Photo / Video\n"
        "• Or send a Text message / Access link\n\n"
        "<i>The bot will forward it directly to this customer!</i>"
    )
    prompt_msg = await query.message.reply(prompt_text, reply_markup=get_cancel_delivery_keyboard(), parse_mode="HTML")
    await state.update_data(prompt_msg_id=prompt_msg.message_id)

@admin_router.callback_query(F.data == "admin_cancel_delivery")
async def handle_admin_cancel_delivery(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await query.answer("Delivery cancelled.")
    try:
        await query.message.delete()
    except Exception:
        pass

@admin_router.message(AdminDeliveryFlow.waiting_for_delivery_item)
async def handle_admin_send_delivery(message: Message, state: FSMContext, bot: Bot):
    if not is_admin_authorized(message.from_user.id):
        return

    data = await state.get_data()
    order_id = data.get("order_id")
    buyer_id = data.get("buyer_id")
    service_title = data.get("service_title", "Service")
    prompt_msg_id = data.get("prompt_msg_id")

    if not order_id or not buyer_id:
        await state.clear()
        await message.reply("⚠️ Delivery session expired. Please tap 'Send Delivery' on the order card again.")
        return

    # Delete buyer's temporary "Receipt Received / Under Verification" message
    order = await get_order(order_id)
    if order and order.get("receipt_msg_id"):
        try:
            await bot.delete_message(chat_id=buyer_id, message_id=order["receipt_msg_id"])
        except Exception:
            pass

    safe_title = html.escape(service_title)
    delivery_header = (
        "<blockquote>\n"
        "<b>🎉 ORDER DELIVERED</b>\n"
        f"<b>Order ID:</b> <code>#{order_id}</code>\n"
        f"<b>Service:</b> {safe_title}\n"
        "</blockquote>\n\n"
        "🎁 <b>Here is your purchase delivery:</b>"
    )

    try:
        await bot.send_message(chat_id=buyer_id, text=delivery_header, parse_mode="HTML")
        # Copy the admin's file/document/photo/video/text directly to buyer!
        await message.copy_to(chat_id=buyer_id)
        await bot.send_message(
            chat_id=buyer_id,
            text="🙏 <i>Thank you for your purchase! Feel free to reach out if you have any questions.</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.reply(f"⚠️ Could not deliver to customer ({buyer_id}): {e}")
        return

    # Mark order completed in DB
    await approve_order(order_id, message.from_user.id)
    await state.clear()

    # Delete prompt message asking for file
    if prompt_msg_id:
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=prompt_msg_id)
        except Exception:
            pass

    # DELETE the approval card from BOTH group and admin DM!
    admin_msgs = await get_admin_order_messages(order_id)
    for am in admin_msgs:
        try:
            await bot.delete_message(chat_id=am["chat_id"], message_id=am["message_id"])
        except Exception:
            pass
    await delete_admin_order_messages(order_id)

    await message.reply(
        f"✅ <b>Order #{order_id} delivered & approval cards cleared!</b>",
        parse_mode="HTML"
    )

@admin_router.callback_query(F.data.startswith("admin_reject:"))
async def handle_admin_direct_reject(query: CallbackQuery, bot: Bot):
    order_id = query.data.split(":")[1]
    admin = query.from_user

    order = await get_order(order_id)
    if not order:
        await query.answer("⚠️ Order not found.", show_alert=True)
        return

    if order["status"] == "REJECTED":
        await query.answer("ℹ️ Order is already rejected.", show_alert=True)
        return

    reason_text = "Payment proof could not be verified by Admin"
    await reject_order(order_id, admin.id, reason_text)
    await query.answer("❌ Order rejected.")

    admin_name = f"@{admin.username}" if admin.username else admin.full_name
    safe_admin_name = html.escape(admin_name)
    safe_reason = html.escape(reason_text)
    rejected_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    current_caption = query.message.caption or ""
    status_block = (
        f"\n\n━━━━━━━━━━━━━━━━━━━━\n"
        f"❌ <b>STATUS: REJECTED</b>\n"
        f"👮 <b>Reviewed by:</b> {safe_admin_name}\n"
        f"⚠️ <b>Reason:</b> {safe_reason}\n"
        f"🕒 <b>Time:</b> {rejected_time}"
    )
    max_orig_len = 1020 - len(status_block)
    if len(current_caption) > max_orig_len:
        current_caption = current_caption[:max_orig_len] + "..."
    new_caption = current_caption + status_block

    try:
        await query.message.edit_caption(
            caption=new_caption,
            reply_markup=None,
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Could not edit admin message caption with HTML: {e}. Retrying plain text...")
        try:
            plain_status = (
                f"\n\n━━━━━━━━━━━━━━━━━━━━\n"
                f"❌ STATUS: REJECTED\n"
                f"👮 Reviewed by: {admin_name}\n"
                f"⚠️ Reason: {reason_text}\n"
                f"🕒 Time: {rejected_time}"
            )
            await query.message.edit_caption(
                caption=(query.message.caption or "")[:800] + plain_status,
                reply_markup=None
            )
        except Exception as e2:
            print(f"Fallback caption edit failed: {e2}")

    user_id = order["user_id"]
    if order.get("receipt_msg_id"):
        try:
            await bot.delete_message(chat_id=user_id, message_id=order["receipt_msg_id"])
        except Exception:
            pass

    user_rejection_text = (
        "<blockquote>\n"
        "<b>❌ VERIFICATION FAILED</b>\n"
        f"<b>Order ID:</b> <code>#{order_id}</code>\n"
        f"<b>Service:</b> {html.escape(order['service_title'])}\n"
        f"<b>Reason:</b> {safe_reason}\n"
        "</blockquote>\n\n"
        "• Please verify in your UPI app that the payment went through.\n"
        "• Ensure you uploaded an uncropped, clear transaction receipt.\n"
        "• Tap below to try again or contact support."
    )

    retry_kb = get_retry_keyboard(order["service_id"])
    try:
        await bot.send_message(
            chat_id=user_id,
            text=user_rejection_text,
            reply_markup=retry_kb,
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Could not send rejection message to user {user_id}: {e}")

    # Clear approval cards from group and DM
    admin_msgs = await get_admin_order_messages(order_id)
    for am in admin_msgs:
        try:
            await bot.delete_message(chat_id=am["chat_id"], message_id=am["message_id"])
        except Exception:
            pass
    await delete_admin_order_messages(order_id)

@admin_router.callback_query(F.data.startswith("admin_reject_menu:"))
async def handle_admin_reject_menu(query: CallbackQuery):
    order_id = query.data.split(":")[1]
    order = await get_order(order_id)
    if not order:
        await query.answer("⚠️ Order not found.", show_alert=True)
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

    reason_text = REJECTION_REASONS.get(reason_code, "Payment proof could not be verified")
    await reject_order(order_id, admin.id, reason_text)

    await query.answer("❌ Order marked as Rejected.")

    admin_name = f"@{admin.username}" if admin.username else admin.full_name
    safe_admin_name = html.escape(admin_name)
    safe_reason = html.escape(reason_text)
    rejected_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    current_caption = query.message.caption or ""
    status_block = (
        f"\n\n━━━━━━━━━━━━━━━━━━━━\n"
        f"❌ <b>STATUS: REJECTED</b>\n"
        f"👮 <b>Reviewed by:</b> {safe_admin_name}\n"
        f"⚠️ <b>Reason:</b> {safe_reason}\n"
        f"🕒 <b>Time:</b> {rejected_time}"
    )
    max_orig_len = 1020 - len(status_block)
    if len(current_caption) > max_orig_len:
        current_caption = current_caption[:max_orig_len] + "..."
    new_caption = current_caption + status_block

    try:
        await query.message.edit_caption(
            caption=new_caption,
            reply_markup=None,
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Could not edit admin message caption with HTML: {e}. Retrying plain text...")
        try:
            plain_status = (
                f"\n\n━━━━━━━━━━━━━━━━━━━━\n"
                f"❌ STATUS: REJECTED\n"
                f"👮 Reviewed by: {admin_name}\n"
                f"⚠️ Reason: {reason_text}\n"
                f"🕒 Time: {rejected_time}"
            )
            await query.message.edit_caption(
                caption=(query.message.caption or "")[:800] + plain_status,
                reply_markup=None
            )
        except Exception as e2:
            print(f"Fallback caption edit failed: {e2}")

    user_id = order["user_id"]
    if order.get("receipt_msg_id"):
        try:
            await bot.delete_message(chat_id=user_id, message_id=order["receipt_msg_id"])
        except Exception:
            pass

    user_rejection_text = (
        "<blockquote>\n"
        "<b>❌ VERIFICATION FAILED</b>\n"
        f"<b>Order ID:</b> <code>#{order_id}</code>\n"
        f"<b>Service:</b> {html.escape(order['service_title'])}\n"
        f"<b>Reason:</b> {safe_reason}\n"
        "</blockquote>\n\n"
        "• Please verify in your UPI app that the payment went through.\n"
        "• Ensure you uploaded an uncropped, clear transaction receipt.\n"
        "• Tap below to try again or contact support."
    )

    retry_kb = get_retry_keyboard(order["service_id"])
    try:
        await bot.send_message(
            chat_id=user_id,
            text=user_rejection_text,
            reply_markup=retry_kb,
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Could not send rejection message to user {user_id}: {e}")

    # Clear approval cards from group and DM
    admin_msgs = await get_admin_order_messages(order_id)
    for am in admin_msgs:
        try:
            await bot.delete_message(chat_id=am["chat_id"], message_id=am["message_id"])
        except Exception:
            pass
    await delete_admin_order_messages(order_id)

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

    # Delete buyer's temporary "Receipt Received / Under Verification" message
    if order.get("receipt_msg_id"):
        try:
            await bot.delete_message(chat_id=user_id, message_id=order["receipt_msg_id"])
        except Exception:
            pass

    safe_title = html.escape(order["service_title"])
    delivery_header = (
        "<blockquote>\n"
        "<b>🎉 ORDER DELIVERED</b>\n"
        f"<b>Order ID:</b> <code>#{order_id}</code>\n"
        f"<b>Service:</b> {safe_title}\n"
        "</blockquote>\n\n"
        "🎁 <b>Here is your purchase delivery:</b>"
    )

    try:
        await bot.send_message(chat_id=user_id, text=delivery_header, parse_mode="HTML")
        # Copy the exact admin message (Document, Photo, Audio, Video, or Text) directly to the buyer!
        await message.copy_to(chat_id=user_id)
        await bot.send_message(
            chat_id=user_id,
            text="🙏 <i>Thank you for your purchase! Feel free to reach out if you have any questions.</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.reply(f"⚠️ Could not deliver message to user {user_id}: {e}")
        return

    # Mark order as completed
    await approve_order(order_id, message.from_user.id)

    # DELETE the approval card from BOTH group and admin DM!
    admin_msgs = await get_admin_order_messages(order_id)
    for am in admin_msgs:
        try:
            await bot.delete_message(chat_id=am["chat_id"], message_id=am["message_id"])
        except Exception:
            pass
    await delete_admin_order_messages(order_id)

    await message.reply(
        f"✅ <b>Order #{order_id} delivered & approval cards cleared!</b>",
        parse_mode="HTML"
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

    safe_group_title = html.escape(message.chat.title or "Admin Group")
    await message.reply(
        "<blockquote>\n"
        "<b>✅ ADMIN GROUP REGISTERED</b>\n"
        f"<b>Title:</b> {safe_group_title}\n"
        f"<b>ID:</b> <code>{group_id}</code>\n"
        "</blockquote>\n\n"
        "All customer payment verification requests will now appear in this group with interactive delivery and rejection options.",
        parse_mode="HTML"
    )

@admin_router.message(Command("admin"))
async def handle_admin_panel(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    if not is_admin_authorized(user_id):
        await message.reply("⛔ You are not authorized to access the admin panel.")
        return

    upi_id = await get_setting("upi_id", config.UPI_ID)
    upi_name = await get_setting("upi_name", config.UPI_NAME)
    text = (
        "<blockquote>\n"
        "<b>🛠️ STORE ADMIN CONTROL PANEL</b>\n"
        f"<b>Active UPI:</b> <code>{upi_id}</code>\n"
        f"<b>Payee Name:</b> {html.escape(upi_name)}\n"
        "</blockquote>\n\n"
        "Select a section below to configure your store:"
    )
    await message.reply(text, reply_markup=get_admin_dashboard_keyboard(), parse_mode="HTML")

@admin_router.callback_query(F.data == "admin_nav:dashboard")
async def nav_dashboard(query: CallbackQuery, state: FSMContext):
    await state.clear()
    if not is_admin_authorized(query.from_user.id):
        await query.answer("⛔ Unauthorized", show_alert=True)
        return

    await query.answer()
    upi_id = await get_setting("upi_id", config.UPI_ID)
    upi_name = await get_setting("upi_name", config.UPI_NAME)
    text = (
        "<blockquote>\n"
        "<b>🛠️ STORE ADMIN CONTROL PANEL</b>\n"
        f"<b>Active UPI:</b> <code>{upi_id}</code>\n"
        f"<b>Payee Name:</b> {html.escape(upi_name)}\n"
        "</blockquote>\n\n"
        "Select a section below to configure your store:"
    )
    try:
        await query.message.edit_text(text, reply_markup=get_admin_dashboard_keyboard(), parse_mode="HTML")
    except Exception:
        await query.message.answer(text, reply_markup=get_admin_dashboard_keyboard(), parse_mode="HTML")

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
    qr_exists = "Active" if os.path.exists(qr_path) else "Missing"

    text = (
        "<blockquote>\n"
        "<b>💳 PAYMENT & QR SETTINGS</b>\n"
        f"<b>UPI ID:</b> <code>{upi_id}</code>\n"
        f"<b>Payee Name:</b> {html.escape(upi_name)}\n"
        f"<b>QR Image:</b> {qr_exists}\n"
        "</blockquote>\n\n"
        "Select what you want to update:"
    )
    try:
        await query.message.edit_text(text, reply_markup=get_payment_settings_keyboard(), parse_mode="HTML")
    except Exception:
        await query.message.answer(text, reply_markup=get_payment_settings_keyboard(), parse_mode="HTML")

@admin_router.callback_query(F.data == "admin_pay:change_upi")
async def start_change_upi(query: CallbackQuery, state: FSMContext):
    if not is_admin_authorized(query.from_user.id):
        await query.answer("⛔ Unauthorized", show_alert=True)
        return

    await state.set_state(EditPaymentFlow.waiting_for_upi_id)
    await query.answer()
    text = (
        "<blockquote>\n"
        "<b>🔄 CHANGE UPI ID</b>\n"
        "Please send the new UPI ID below:\n"
        "e.g. <code>yourname@okhdfcbank</code> or <code>9876543210@upi</code>\n"
        "</blockquote>"
    )
    await query.message.edit_text(text, reply_markup=get_cancel_admin_flow_keyboard(), parse_mode="HTML")

@admin_router.message(EditPaymentFlow.waiting_for_upi_id, F.text)
async def finish_change_upi(message: Message, state: FSMContext):
    new_upi = message.text.strip()
    if "@" not in new_upi or len(new_upi) < 5:
        await message.reply("⚠️ Invalid UPI ID format. It should look like <code>username@bank</code> or <code>number@upi</code>. Please try again:", parse_mode="HTML")
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
        "<blockquote>\n"
        "<b>✅ UPI ID UPDATED</b>\n"
        f"<b>New UPI ID:</b> <code>{html.escape(new_upi)}</code>\n"
        "All future customer orders will now display this UPI ID.\n"
        "</blockquote>",
        reply_markup=get_admin_dashboard_keyboard(),
        parse_mode="HTML"
    )

@admin_router.callback_query(F.data == "admin_pay:change_name")
async def start_change_name(query: CallbackQuery, state: FSMContext):
    if not is_admin_authorized(query.from_user.id):
        await query.answer("⛔ Unauthorized", show_alert=True)
        return

    await state.set_state(EditPaymentFlow.waiting_for_payee_name)
    await query.answer()
    text = (
        "<blockquote>\n"
        "<b>👤 CHANGE PAYEE NAME</b>\n"
        "Please send the new Payee / Merchant Name:\n"
        "e.g. <code>My Store</code> or <code>John Doe</code>\n"
        "</blockquote>"
    )
    await query.message.edit_text(text, reply_markup=get_cancel_admin_flow_keyboard(), parse_mode="HTML")

@admin_router.message(EditPaymentFlow.waiting_for_payee_name, F.text)
async def finish_change_name(message: Message, state: FSMContext):
    new_name = message.text.strip()
    await set_setting("upi_name", new_name)
    config.UPI_NAME = new_name
    await state.clear()
    await message.reply(
        "<blockquote>\n"
        "<b>✅ PAYEE NAME UPDATED</b>\n"
        f"<b>New Name:</b> {html.escape(new_name)}\n"
        "</blockquote>",
        reply_markup=get_admin_dashboard_keyboard(),
        parse_mode="HTML"
    )

@admin_router.callback_query(F.data == "admin_pay:change_qr")
async def start_change_qr(query: CallbackQuery, state: FSMContext):
    if not is_admin_authorized(query.from_user.id):
        await query.answer("⛔ Unauthorized", show_alert=True)
        return

    await state.set_state(EditPaymentFlow.waiting_for_qr_photo)
    await query.answer()
    text = (
        "<blockquote>\n"
        "<b>🖼️ UPLOAD NEW QR CODE</b>\n"
        "Please upload the new QR code image as a photo.\n"
        "<i>Clean white edge padding will be automatically added for mobile clarity.</i>\n"
        "</blockquote>"
    )
    await query.message.edit_text(text, reply_markup=get_cancel_admin_flow_keyboard(), parse_mode="HTML")

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
            "<blockquote>\n"
            "<b>✅ QR CODE UPDATED</b>\n"
            "Clean edge padding has been applied for mobile scannability.\n"
            "All new orders will now display this QR code image.\n"
            "</blockquote>",
            reply_markup=get_admin_dashboard_keyboard(),
            parse_mode="HTML"
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
        "<blockquote>\n"
        "<b>📊 BOT LIVE ANALYTICS</b>\n"
        f"<b>Registered Users:</b> {users_count}\n"
        f"<b>Pending Orders:</b> {pending_count}\n"
        f"<b>Completed Orders:</b> {completed_count}\n"
        f"<b>Rejected Orders:</b> {rejected_count}\n"
        f"<b>Total Approved Revenue:</b> ₹{revenue:,.2f}\n"
        "</blockquote>\n\n"
        f"⚙️ <b>Admin Group ID:</b> <code>{config.ADMIN_GROUP_ID}</code>\n"
        f"📲 <b>Configured UPI ID:</b> <code>{config.UPI_ID}</code>"
    )
    kb = get_admin_dashboard_keyboard()
    await query.message.edit_text(stats_text, reply_markup=kb, parse_mode="HTML")

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
        "<blockquote>\n"
        "<b>📋 SERVICES CATALOG MANAGER</b>\n"
        "🟢 = Active (Visible to buyers)\n"
        "🔴 = Inactive / Hidden\n"
        "</blockquote>\n\n"
        "Select a service below to edit its price, title, or toggle visibility:"
    )
    await query.message.edit_text(text, reply_markup=get_services_management_keyboard(services), parse_mode="HTML")

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
    safe_title = html.escape(service['title'])
    safe_desc = html.escape(service['description'] or "")
    text = (
        "<blockquote>\n"
        f"<b>🏷️ SERVICE: {safe_title}</b>\n"
        f"<b>ID:</b> <code>{service['service_id']}</code>\n"
        f"<b>Price:</b> ₹{service['price_inr']:.0f}\n"
        f"<b>Status:</b> {status_str}\n"
        "</blockquote>\n\n"
        f"📝 <b>Description:</b>\n{safe_desc}\n\n"
        "<i>Select an action below to update this service:</i>"
    )
    kb = get_service_actions_keyboard(service_id, service["is_active"])
    await query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

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
    safe_title = html.escape(service['title'])
    safe_desc = html.escape(service['description'] or "")
    text = (
        "<blockquote>\n"
        f"<b>🏷️ SERVICE: {safe_title}</b>\n"
        f"<b>ID:</b> <code>{service['service_id']}</code>\n"
        f"<b>Price:</b> ₹{service['price_inr']:.0f}\n"
        f"<b>Status:</b> {status_str}\n"
        "</blockquote>\n\n"
        f"📝 <b>Description:</b>\n{safe_desc}\n\n"
        "<i>Select an action below to update this service:</i>"
    )
    kb = get_service_actions_keyboard(service_id, service["is_active"])
    await query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

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
        "<blockquote>\n"
        "<b>📋 SERVICES CATALOG MANAGER</b>\n"
        "Service was updated/removed.\n"
        "</blockquote>\n\n"
        "Select a service to manage:"
    )
    await query.message.edit_text(text, reply_markup=get_services_management_keyboard(services), parse_mode="HTML")

# --- EDIT PRICE FLOW ---
@admin_router.callback_query(F.data.startswith("svc_action:price:"))
async def edit_price_start(query: CallbackQuery, state: FSMContext):
    service_id = query.data.split(":")[2]
    await state.set_state(EditServiceFlow.waiting_for_new_price)
    await state.update_data(service_id=service_id)
    await query.answer()
    text = (
        "<blockquote>\n"
        f"<b>💰 EDIT PRICE:</b> <code>{service_id}</code>\n"
        "Please type and send the new price in INR (e.g. <code>249</code> or <code>499</code>):\n"
        "</blockquote>"
    )
    await query.message.edit_text(text, reply_markup=get_cancel_admin_flow_keyboard(), parse_mode="HTML")

@admin_router.message(EditServiceFlow.waiting_for_new_price, F.text)
async def edit_price_finish(message: Message, state: FSMContext):
    raw = message.text.strip().replace("₹", "").replace(",", "")
    try:
        new_price = float(raw)
        if new_price <= 0:
            raise ValueError
    except ValueError:
        await message.reply("⚠️ Invalid amount. Please enter a valid positive number (e.g. <code>299</code>):", parse_mode="HTML")
        return

    data = await state.get_data()
    service_id = data.get("service_id")
    await update_service_price(service_id, new_price)
    await state.clear()

    await message.reply(
        "<blockquote>\n"
        "<b>✅ PRICE UPDATED</b>\n"
        f"Service <code>{service_id}</code> is now priced at <b>₹{new_price:.0f}</b>.\n"
        "</blockquote>",
        reply_markup=get_admin_dashboard_keyboard(),
        parse_mode="HTML"
    )

# --- EDIT DELIVERY CONTENT FLOW ---
@admin_router.callback_query(F.data.startswith("svc_action:delivery:"))
async def edit_delivery_start(query: CallbackQuery, state: FSMContext):
    service_id = query.data.split(":")[2]
    await state.set_state(EditServiceFlow.waiting_for_new_delivery)
    await state.update_data(service_id=service_id)
    await query.answer()
    text = (
        "<blockquote>\n"
        f"<b>🎁 EDIT DELIVERY CONTENT:</b> <code>{service_id}</code>\n"
        "Please send the new delivery link, text, or instructions:\n"
        "</blockquote>"
    )
    await query.message.edit_text(text, reply_markup=get_cancel_admin_flow_keyboard(), parse_mode="HTML")

@admin_router.message(EditServiceFlow.waiting_for_new_delivery, F.text)
async def edit_delivery_finish(message: Message, state: FSMContext):
    new_delivery = message.text.strip()
    data = await state.get_data()
    service_id = data.get("service_id")
    await update_service_delivery(service_id, new_delivery)
    await state.clear()

    await message.reply(
        "<blockquote>\n"
        "<b>✅ DELIVERY CONTENT UPDATED</b>\n"
        f"Service: <code>{service_id}</code>\n"
        "</blockquote>",
        reply_markup=get_admin_dashboard_keyboard(),
        parse_mode="HTML"
    )

# --- EDIT TITLE FLOW ---
@admin_router.callback_query(F.data.startswith("svc_action:title:"))
async def edit_title_start(query: CallbackQuery, state: FSMContext):
    service_id = query.data.split(":")[2]
    await state.set_state(EditServiceFlow.waiting_for_new_title)
    await state.update_data(service_id=service_id)
    await query.answer()
    text = (
        "<blockquote>\n"
        f"<b>📝 EDIT TITLE:</b> <code>{service_id}</code>\n"
        "Please send the new display title for this service:\n"
        "</blockquote>"
    )
    await query.message.edit_text(text, reply_markup=get_cancel_admin_flow_keyboard(), parse_mode="HTML")

@admin_router.message(EditServiceFlow.waiting_for_new_title, F.text)
async def edit_title_finish(message: Message, state: FSMContext):
    new_title = message.text.strip()
    data = await state.get_data()
    service_id = data.get("service_id")
    await update_service_title(service_id, new_title)
    await state.clear()

    await message.reply(
        "<blockquote>\n"
        "<b>✅ TITLE UPDATED</b>\n"
        f"<b>New Title:</b> {html.escape(new_title)}\n"
        "</blockquote>",
        reply_markup=get_admin_dashboard_keyboard(),
        parse_mode="HTML"
    )

# ==========================================
# 4. ADD NEW SERVICE WIZARD (STREAMLINED)
# ==========================================

@admin_router.callback_query(F.data == "admin_nav:add_service")
async def add_service_step1(query: CallbackQuery, state: FSMContext):
    if not is_admin_authorized(query.from_user.id):
        await query.answer("⛔ Unauthorized", show_alert=True)
        return

    await state.set_state(AddServiceFlow.waiting_for_title)
    await query.answer()
    text = (
        "<blockquote>\n"
        "<b>➕ ADD NEW SERVICE (Step 1 of 3)</b>\n"
        "Send the <b>Service Title</b> (e.g. <code>💎 VIP Signals Channel</code>):\n"
        "</blockquote>"
    )
    await query.message.edit_text(text, reply_markup=get_cancel_admin_flow_keyboard(), parse_mode="HTML")

@admin_router.message(AddServiceFlow.waiting_for_title, F.text)
async def add_service_step2(message: Message, state: FSMContext):
    title = message.text.strip()
    await state.update_data(new_svc_title=title)
    await state.set_state(AddServiceFlow.waiting_for_description)
    text = (
        "<blockquote>\n"
        "<b>➕ ADD NEW SERVICE (Step 2 of 3)</b>\n"
        f"<b>Title:</b> {html.escape(title)}\n\n"
        "Now send a short <b>Description</b> explaining the service:\n"
        "</blockquote>"
    )
    await message.reply(text, reply_markup=get_cancel_admin_flow_keyboard(), parse_mode="HTML")

@admin_router.message(AddServiceFlow.waiting_for_description, F.text)
async def add_service_step3(message: Message, state: FSMContext):
    desc = message.text.strip()
    await state.update_data(new_svc_desc=desc)
    await state.set_state(AddServiceFlow.waiting_for_price)
    text = (
        "<blockquote>\n"
        "<b>➕ ADD NEW SERVICE (Step 3 of 3)</b>\n"
        "Send the <b>Price in INR</b> (e.g. <code>199</code> or <code>499</code>):\n"
        "</blockquote>"
    )
    await message.reply(text, reply_markup=get_cancel_admin_flow_keyboard(), parse_mode="HTML")

@admin_router.message(AddServiceFlow.waiting_for_price, F.text)
async def add_service_finish(message: Message, state: FSMContext):
    raw = message.text.strip().replace("₹", "").replace(",", "")
    try:
        price = float(raw)
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.reply("⚠️ Please enter a valid numeric price (e.g. <code>199</code>):", parse_mode="HTML")
        return

    data = await state.get_data()
    title = data["new_svc_title"]
    desc = data["new_svc_desc"]

    # Generate a clean unique ID from title
    clean_slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:16] or "svc"
    svc_id = f"{clean_slug}_{uuid.uuid4().hex[:4]}"

    success = await add_service(svc_id, title, desc, price, "Custom fulfillment by Admin.")
    await state.clear()

    if success:
        text = (
            "<blockquote>\n"
            "<b>🎉 SERVICE CREATED!</b>\n"
            f"<b>Title:</b> {html.escape(title)}\n"
            f"<b>Price:</b> ₹{price:.0f}\n"
            f"<b>ID:</b> <code>{svc_id}</code>\n"
            "</blockquote>\n\n"
            "This item is now live in the store catalog for all customers!"
        )
    else:
        text = "⚠️ An error occurred while creating the service in the database."

    await message.reply(text, reply_markup=get_admin_dashboard_keyboard(), parse_mode="HTML")

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
        "<blockquote>\n"
        "<b>📢 BROADCAST ANNOUNCEMENT</b>\n"
        "Send the message you want to broadcast to all registered users.\n"
        "• You can send <b>plain text</b> or a <b>photo with caption</b>.\n"
        "<i>You will receive a preview before confirmation.</i>\n"
        "</blockquote>"
    )
    await query.message.edit_text(text, reply_markup=get_cancel_admin_flow_keyboard(), parse_mode="HTML")

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
        "<blockquote>\n"
        "<b>📢 BROADCAST PREVIEW (Photo)</b>\n"
        f"<b>Audience:</b> {len(all_users)} registered users\n"
        "</blockquote>\n\n"
        f"📝 <b>Caption:</b>\n{html.escape(caption) if caption else '<i>(No caption)</i>'}\n\n"
        "Ready to send to all users?"
    )
    await message.reply_photo(
        photo=photo_file_id,
        caption=preview_text,
        reply_markup=get_broadcast_confirm_keyboard(),
        parse_mode="HTML"
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
        "<blockquote>\n"
        "<b>📢 BROADCAST PREVIEW</b>\n"
        f"<b>Audience:</b> {len(all_users)} registered users\n"
        "</blockquote>\n\n"
        f"{html.escape(text_content)}\n\n"
        "Ready to send to all users?"
    )
    await message.reply(preview_text, reply_markup=get_broadcast_confirm_keyboard(), parse_mode="HTML")

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
    status_msg = await query.message.answer(f"⏳ <b>Broadcasting in progress...</b> (0/{total})", parse_mode="HTML")
    await state.clear()

    sent_count = 0
    blocked_count = 0

    for idx, uid in enumerate(all_users, 1):
        try:
            if content_type == "photo":
                await bot.send_photo(
                    chat_id=uid,
                    photo=data["photo_file_id"],
                    caption=data.get("caption", "")
                )
            else:
                await bot.send_message(
                    chat_id=uid,
                    text=data["text_content"]
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
                await status_msg.edit_text(f"⏳ <b>Broadcasting in progress...</b> ({idx}/{total})", parse_mode="HTML")
            except Exception:
                pass

    report = (
        "<blockquote>\n"
        "<b>🎉 BROADCAST COMPLETED</b>\n"
        f"<b>Delivered:</b> {sent_count} users\n"
        f"<b>Blocked / Failed:</b> {blocked_count} users\n"
        f"<b>Total Audience:</b> {total} users\n"
        "</blockquote>"
    )
    await status_msg.edit_text(report, reply_markup=get_admin_dashboard_keyboard(), parse_mode="HTML")

@admin_router.callback_query(F.data == "broadcast_action:cancel")
async def broadcast_cancel(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await query.answer("Broadcast cancelled.")
    await query.message.edit_text(
        "<blockquote>\n"
        "<b>❌ BROADCAST CANCELLED</b>\n"
        "</blockquote>",
        reply_markup=get_admin_dashboard_keyboard(),
        parse_mode="HTML"
    )
