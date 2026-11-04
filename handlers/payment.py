import os
import uuid
import re
import html
from datetime import datetime
from PIL import Image
import winocr
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from config import config
from database import (
    get_service,
    create_order,
    submit_order_proof,
    get_order,
    get_setting,
    save_admin_order_message
)
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
    await create_order(
        order_id=order_id,
        user_id=user.id,
        service_id=service_id,
        amount=service["price_inr"],
        username=user.username,
        full_name=user.full_name
    )

    # Store order info in FSM state
    await state.set_state(OrderFlow.waiting_for_screenshot)
    await state.update_data(order_id=order_id, service_id=service_id, price=service["price_inr"])

    upi_id = await get_setting("upi_id", config.UPI_ID)
    upi_name = await get_setting("upi_name", config.UPI_NAME)
    qr_path = await get_setting("qr_image_path", config.QR_IMAGE_PATH)

    if not os.path.isabs(qr_path):
        qr_path = os.path.abspath(qr_path)

    # Fallback to default assets/qr_code.png if specified path does not exist
    if not os.path.exists(qr_path):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        fallback_qr = os.path.join(base_dir, "assets", "qr_code.png")
        if os.path.exists(fallback_qr):
            qr_path = fallback_qr

    caption = (
        f"🧾 **Order Generated:** `#{order_id}`\n\n"
        f"📌 **Service:** {service['title']}\n"
        f"💰 **Amount to Pay:** `₹{service['price_inr']:.0f}`\n\n"
        f"📲 **UPI ID:** `{upi_id}` *(Tap to copy)*\n"
        f"👤 **Payee Name:** {upi_name}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📝 **Payment Steps:**\n"
        "1. Scan the QR code above or pay to the UPI ID.\n"
        "2. Complete the payment of exact amount in your UPI app.\n"
        "3. Take a screenshot of the successful payment screen.\n"
        "4. **Upload the screenshot here as a photo.**"
    )

    cancel_kb = get_cancel_order_keyboard(order_id)
    sent_msg = None

    # Delete previous service detail message to keep chat history clean
    try:
        await query.message.delete()
    except Exception:
        pass

    if os.path.exists(qr_path):
        try:
            photo = FSInputFile(qr_path)
            sent_msg = await query.message.answer_photo(
                photo=photo,
                caption=caption,
                reply_markup=cancel_kb,
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Error sending QR photo: {e}")
            sent_msg = await query.message.answer(caption, reply_markup=cancel_kb, parse_mode="Markdown")
    else:
        # Fallback if QR image is not yet placed in assets
        sent_msg = await query.message.answer(
            f"⚠️ QR Image not found at `{qr_path}`.\n\n" + caption,
            reply_markup=cancel_kb,
            parse_mode="Markdown"
        )

    if sent_msg:
        await state.update_data(qr_msg_id=sent_msg.message_id)

@payment_router.callback_query(F.data.startswith("cancel_order:"))
async def handle_cancel_order(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await query.answer("Order cancelled.")
    # Delete the payment QR message completely
    try:
        await query.message.delete()
    except Exception:
        pass

    await query.message.answer(
        "❌ **Order cancelled.** You can browse our services anytime.",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="Markdown"
    )

@payment_router.message(OrderFlow.waiting_for_screenshot, F.photo)
async def handle_screenshot_upload(message: Message, state: FSMContext, bot: Bot):
    user = message.from_user
    photo_file_id = message.photo[-1].file_id

    data = await state.get_data()
    order_id = data.get("order_id")
    price = data.get("price", 0.0)
    qr_msg_id = data.get("qr_msg_id")

    if not order_id:
        await state.clear()
        await message.reply("⚠️ Order session expired. Please start again from /services.")
        return

    # 1. Download image for automated OCR scan (verifying amount on receipt)
    upload_dir = "assets/user_uploads"
    os.makedirs(upload_dir, exist_ok=True)
    temp_img_path = os.path.join(upload_dir, f"{order_id}.jpg")
    await bot.download(message.photo[-1], destination=temp_img_path)

    ocr_text = ""
    amount_found = False
    extracted_utr = None
    try:
        img = Image.open(temp_img_path)
        res = await winocr.recognize_pil(img, lang="en")
        ocr_text = res.text or ""

        # Check if expected amount (e.g. 199, 199.00) is visible in the text
        price_int = int(price)
        if str(price_int) in ocr_text or f"{price:.2f}" in ocr_text or f"{price:.0f}" in ocr_text:
            amount_found = True

        # Try to find a UTR-like 10-14 digit sequence in OCR
        utr_match = re.search(r"\b\d{10,14}\b", ocr_text)
        if utr_match:
            extracted_utr = utr_match.group(0)
    except Exception as e:
        print(f"OCR Scan error: {e}")
    finally:
        if os.path.exists(temp_img_path):
            try:
                os.remove(temp_img_path)
            except Exception:
                pass

    # 2. Update Database: mark order as PENDING_VERIFICATION
    await submit_order_proof(order_id=order_id, screenshot_file_id=photo_file_id, utr=extracted_utr)

    # 3. Clean up the user's QR code card (remove cancel button)
    if qr_msg_id:
        try:
            await bot.edit_message_reply_markup(
                chat_id=message.chat.id,
                message_id=qr_msg_id,
                reply_markup=None
            )
        except Exception:
            pass

    # 4. Clear user's FSM state
    await state.clear()

    # 5. Send warm confirmation message to USER (no manual UTR prompt!)
    order_info = await get_order(order_id)
    service_title = order_info["service_title"] if order_info else "Selected Service"

    user_receipt_text = (
        "🙏 **Payment Screenshot Received! Thank You!**\n\n"
        f"🧾 **Order ID:** `#{order_id}`\n"
        f"👤 **Customer ID:** `{user.id}`\n"
        f"📌 **Service:** {service_title}\n"
        f"💰 **Amount:** ₹{price:.0f}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⏳ **Kripya thoda patience rakhein.**\n"
        "Hamari admin team bank account me payment verify kar rahi hai.\n"
        "Jaise hi verification complete hoga, aapka order / access aapko **yahin bot me turant automatically deliver** kar diya jayega! 🚀\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )
    await message.reply(user_receipt_text, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")

    # 6. Forward Verification Card to Admin:
    # (Send to Admin Group if configured, AND to all Admin DMs so you NEVER miss a payment!)
    if amount_found:
        ocr_badge = f"✅ <b>MATCHED</b>: ₹{price:.0f} detected in receipt image"
        plain_badge = f"✅ MATCHED: ₹{price:.0f} detected in receipt image"
    else:
        ocr_badge = f"⚠️ <b>CAUTION</b>: ₹{price:.0f} not clearly detected in OCR scan (Please verify receipt visually)"
        plain_badge = f"⚠️ CAUTION: ₹{price:.0f} not clearly detected in OCR scan (Please verify receipt visually)"

    username_str = f"@{user.username}" if user.username else "No username"
    safe_name = html.escape(user.full_name or "Anonymous")
    safe_username = html.escape(username_str)
    safe_service = html.escape(service_title)
    safe_utr = html.escape(extracted_utr) if extracted_utr else "Not detected in scan"

    admin_caption_html = (
        "🔔 <b>NEW PAYMENT VERIFICATION REQUEST</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🧾 <b>Order ID:</b> <code>#{order_id}</code>\n"
        f"👤 <b>Customer:</b> {safe_name} ({safe_username})\n"
        f"🆔 <b>Customer ID:</b> <code>{user.id}</code>\n"
        f"📌 <b>Service:</b> {safe_service}\n"
        f"💰 <b>Order Amount:</b> <code>₹{price:.0f}</code>\n"
        f"🔢 <b>UTR / Ref:</b> <code>{safe_utr}</code>\n\n"
        f"🔍 <b>Auto-Scan:</b> {ocr_badge}\n"
        f"🕒 <b>Submitted:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👉 <i>Action:</i> Tap <b>Approve</b> to deliver default service link, OR <b>Reply to this message</b> with any custom file/link/message to deliver it directly to this customer!"
    )

    admin_caption_plain = (
        "🔔 NEW PAYMENT VERIFICATION REQUEST\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🧾 Order ID: #{order_id}\n"
        f"👤 Customer: {user.full_name} ({username_str})\n"
        f"🆔 Customer ID: {user.id}\n"
        f"📌 Service: {service_title}\n"
        f"💰 Order Amount: ₹{price:.0f}\n"
        f"🔢 UTR / Ref: {extracted_utr or 'Not detected'}\n\n"
        f"🔍 Auto-Scan: {plain_badge}\n"
        f"🕒 Submitted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👉 Action: Tap Approve or Reply to this message with a file to deliver!"
    )

    admin_kb = get_admin_verification_keyboard(order_id)

    # Collect all destinations: Admin Group + all Admin DMs
    destinations = set()
    if config.ADMIN_GROUP_ID and config.ADMIN_GROUP_ID != 0:
        destinations.add(config.ADMIN_GROUP_ID)
    for admin_id in config.ADMIN_IDS:
        destinations.add(admin_id)

    for dest_id in destinations:
        try:
            sent = await bot.send_photo(
                chat_id=dest_id,
                photo=photo_file_id,
                caption=admin_caption_html,
                reply_markup=admin_kb,
                parse_mode="HTML"
            )
            # Save mapping so if admin replies to this card with a file, bot delivers to the exact user!
            await save_admin_order_message(sent.message_id, dest_id, order_id)
        except TelegramBadRequest as e:
            print(f"TelegramBadRequest sending HTML to {dest_id}: {e}. Retrying with plain text fallback...")
            try:
                sent = await bot.send_photo(
                    chat_id=dest_id,
                    photo=photo_file_id,
                    caption=admin_caption_plain,
                    reply_markup=admin_kb
                )
                await save_admin_order_message(sent.message_id, dest_id, order_id)
            except Exception as e2:
                print(f"Failed fallback sending to {dest_id}: {e2}")
        except Exception as e:
            print(f"Error forwarding payment verification to {dest_id}: {e}")

@payment_router.message(OrderFlow.waiting_for_screenshot)
async def handle_invalid_screenshot_message(message: Message):
    await message.reply(
        "⚠️ **Please upload a screenshot image (photo) of your payment.**\n\n"
        "If you want to abort this order, click Cancel Order above or type /cancel."
    )
