import os
import uuid
import re
from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from config import config
from database import get_service, create_order, check_utr_exists, submit_order_proof, get_order
from states.order_states import OrderFlow
from keyboards.user_keyboards import get_cancel_order_keyboard, get_main_menu_keyboard
from keyboards.admin_keyboards import get_admin_verification_keyboard

payment_router = Router()

def generate_order_id() -> str:
    return "ORD-" + uuid.uuid4().hex[:8].upper()

@payment_router.callback_query(F.data.startswith("buy_service:"))
async def handle_buy_service(query: CallbackQuery, state: FSMContext, bot: Bot):
    await query.answer()
    service_id = query.data.split(":")[1]
    service = await get_service(service_id)

    if not service:
        await query.message.answer("⚠️ Service not found. Please choose from the catalog.")
        return

    order_id = generate_order_id()
    user = query.from_user
    await create_order(order_id, user.id, service_id, service["price_inr"])

    # Store order info in FSM state
    await state.set_state(OrderFlow.waiting_for_screenshot)
    await state.update_data(order_id=order_id, service_id=service_id, price=service["price_inr"])

    caption = (
        f"🧾 **Order Generated:** `#{order_id}`\n\n"
        f"📌 **Service:** {service['title']}\n"
        f"💰 **Amount to Pay:** `₹{service['price_inr']:.0f}`\n\n"
        f"📲 **UPI ID:** `{config.UPI_ID}` *(Tap to copy)*\n"
        f"👤 **Payee Name:** {config.UPI_NAME}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📝 **Payment Steps:**\n"
        "1. Scan the QR code above or pay to the UPI ID.\n"
        "2. Complete the payment of exact amount in your UPI app.\n"
        "3. Take a screenshot of the successful payment screen.\n"
        "4. **Upload the screenshot here as a photo.**\n\n"
        "⚠️ *Do not send fake or old screenshots. All UTR numbers are verified.*"
    )

    qr_path = config.QR_IMAGE_PATH
    cancel_kb = get_cancel_order_keyboard(order_id)

    if os.path.exists(qr_path):
        photo = FSInputFile(qr_path)
        await query.message.answer_photo(
            photo=photo,
            caption=caption,
            reply_markup=cancel_kb,
            parse_mode="Markdown"
        )
    else:
        # Fallback if QR image is not yet placed in assets
        await query.message.answer(
            f"⚠️ QR Image not found at `{qr_path}`.\n\n" + caption,
            reply_markup=cancel_kb,
            parse_mode="Markdown"
        )

@payment_router.callback_query(F.data.startswith("cancel_order:"))
async def handle_cancel_order(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await query.answer("Order cancelled.")
    await query.message.answer(
        "❌ Order has been cancelled. You can browse our services anytime.",
        reply_markup=get_main_menu_keyboard()
    )

@payment_router.message(OrderFlow.waiting_for_screenshot, F.photo)
async def handle_screenshot_upload(message: Message, state: FSMContext):
    # Highest resolution photo
    photo_file_id = message.photo[-1].file_id
    await state.update_data(screenshot_file_id=photo_file_id)
    await state.set_state(OrderFlow.waiting_for_utr)

    await message.reply(
        "📸 **Screenshot received!**\n\n"
        "Now, please enter the **12-digit UPI Reference / UTR Number** from your payment receipt.\n\n"
        "*(Example: `432109876543`)*\n"
        "This helps us verify your transaction instantly with our bank ledger.",
        parse_mode="Markdown"
    )

@payment_router.message(OrderFlow.waiting_for_screenshot)
async def handle_invalid_screenshot_message(message: Message):
    await message.reply(
        "⚠️ **Please upload a screenshot image (photo) of your payment.**\n\n"
        "If you want to abort this order, type /cancel."
    )

@payment_router.message(OrderFlow.waiting_for_utr, F.text)
async def handle_utr_submission(message: Message, state: FSMContext, bot: Bot):
    raw_utr = message.text.strip().replace(" ", "").replace("-", "")

    # Basic regex validation: UPI UTRs are typically 12 numeric digits
    if not re.match(r"^[0-9A-Za-z]{8,18}$", raw_utr):
        await message.reply(
            "⚠️ **Invalid UTR / Reference Number format.**\n\n"
            "A standard UPI UTR is usually a 12-digit number (e.g., `432109876543`).\n"
            "Please check your GPay / PhonePe / Paytm receipt and re-enter the correct reference number:"
        )
        return

    # Anti-Fraud check: Check if UTR is already in database
    is_duplicate = await check_utr_exists(raw_utr)
    if is_duplicate:
        await message.reply(
            "🚨 **DUPLICATE / REUSED UTR DETECTED!**\n\n"
            f"The Transaction ID `{raw_utr}` has already been registered for a previous order.\n"
            "Submitting reused or false receipts is strictly prohibited.\n\n"
            "Please enter the genuine 12-digit UTR from your bank app, or type /cancel to abort.",
            parse_mode="Markdown"
        )
        return

    data = await state.get_data()
    order_id = data.get("order_id")
    screenshot_file_id = data.get("screenshot_file_id")

    if not order_id or not screenshot_file_id:
        await state.clear()
        await message.reply("⚠️ Session expired. Please start your order again using /services.")
        return

    success = await submit_order_proof(order_id, raw_utr, screenshot_file_id)
    if not success:
        await message.reply(
            "⚠️ This UTR has just been used by another transaction. Please check your reference number and try again."
        )
        return

    # Clear user state
    await state.clear()

    # Confirm to User
    order_info = await get_order(order_id)
    service_title = order_info["service_title"] if order_info else "Service"
    amount = order_info["amount"] if order_info else data.get("price", 0)

    user_confirmation_text = (
        "⏳ **Payment Proof Submitted for Verification!**\n\n"
        f"🧾 **Order ID:** `#{order_id}`\n"
        f"📌 **Service:** {service_title}\n"
        f"💰 **Amount:** ₹{amount:.0f}\n"
        f"🔢 **UTR Number:** `{raw_utr}`\n\n"
        "Our team has received your submission. We are verifying it against our bank ledger.\n"
        "⚡ You will receive an instant notification here once it is verified and activated!\n\n"
        "Thank you for your patience! 🙏"
    )
    await message.reply(user_confirmation_text, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")

    # Forward to Admin Group
    admin_group_id = config.ADMIN_GROUP_ID
    if admin_group_id and admin_group_id != 0:
        user = message.from_user
        username_str = f"@{user.username}" if user.username else "No username"
        admin_caption = (
            "🔔 **NEW PAYMENT VERIFICATION REQUEST**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🧾 **Order ID:** `#{order_id}`\n"
            f"👤 **Customer:** {user.full_name} ({username_str})\n"
            f"🆔 **Telegram ID:** `{user.id}`\n"
            f"📌 **Service:** {service_title}\n"
            f"💰 **Amount:** `₹{amount:.0f}`\n"
            f"🔢 **UTR Number:** `{raw_utr}`\n"
            f"🕒 **Submitted:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "👉 *Please check your UPI/Bank app for this UTR and exact amount before approving.*"
        )
        admin_kb = get_admin_verification_keyboard(order_id)

        try:
            await bot.send_photo(
                chat_id=admin_group_id,
                photo=screenshot_file_id,
                caption=admin_caption,
                reply_markup=admin_kb,
                parse_mode="Markdown"
            )
        except Exception as e:
            # If bot cannot send to admin group (e.g. wrong group ID or not added as admin)
            print(f"Error forwarding payment verification to admin group {admin_group_id}: {e}")
