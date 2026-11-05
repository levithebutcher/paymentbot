import html
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from database import get_services, get_service
from keyboards.user_keyboards import get_services_keyboard, get_service_detail_keyboard

services_router = Router()

@services_router.message(F.text.in_({"💎 View Services", "🛍️ View Services"}))
@services_router.callback_query(F.data == "back_to_services")
async def show_services_catalog(event: Message | CallbackQuery):
    services = await get_services()
    if not services:
        msg = "⚠️ No services are currently available. Please check back later."
        if isinstance(event, CallbackQuery):
            await event.answer(msg, show_alert=True)
        else:
            await event.answer(msg)
        return

    text = (
        "<blockquote>\n"
        "<b>💎 SERVICES CATALOG</b>\n"
        "Select an item below to view full details & pricing:\n"
        "</blockquote>"
    )
    kb = get_services_keyboard(services)

    if isinstance(event, CallbackQuery):
        await event.answer()
        # If the callback came from a photo message, delete the photo and send clean catalog
        if event.message.photo:
            try:
                await event.message.delete()
            except Exception:
                pass
            await event.message.answer(text, reply_markup=kb, parse_mode="HTML")
        else:
            try:
                await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception:
                await event.message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await event.answer(text, reply_markup=kb, parse_mode="HTML")

@services_router.callback_query(F.data.startswith("select_service:"))
async def handle_select_service(query: CallbackQuery):
    await query.answer()
    service_id = query.data.split(":")[1]
    service = await get_service(service_id)

    if not service:
        await query.message.answer("⚠️ Service not found or no longer available.")
        return

    safe_title = html.escape(service['title'])
    safe_desc = html.escape(service['description'] or "Premium digital service.")

    text = (
        "<blockquote>\n"
        f"<b>💎 {safe_title}</b>\n"
        f"<b>Price:</b> ₹{service['price_inr']:.0f}\n"
        f"<b>Details:</b> {safe_desc}\n"
        "</blockquote>\n\n"
        "<i>Tap 'Proceed to Payment' to generate your UPI QR Code.</i>"
    )

    kb = get_service_detail_keyboard(service_id)
    if query.message.photo:
        try:
            await query.message.delete()
        except Exception:
            pass
        await query.message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        try:
            await query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await query.message.answer(text, reply_markup=kb, parse_mode="HTML")
