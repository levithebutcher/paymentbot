from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from database import get_services, get_service
from keyboards.user_keyboards import get_services_keyboard, get_service_detail_keyboard

services_router = Router()

@services_router.message(F.text == "🛍️ View Services")
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

    text = "📋 **Available Services Catalog:**\n\nSelect a service to view full details and proceed to payment:"
    kb = get_services_keyboard(services)

    if isinstance(event, CallbackQuery):
        await event.answer()
        # If the callback came from a photo message, send a new message instead of edit_text
        if event.message.photo:
            await event.message.answer(text, reply_markup=kb, parse_mode="Markdown")
        else:
            await event.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await event.answer(text, reply_markup=kb, parse_mode="Markdown")

@services_router.callback_query(F.data.startswith("select_service:"))
async def handle_select_service(query: CallbackQuery):
    await query.answer()
    service_id = query.data.split(":")[1]
    service = await get_service(service_id)

    if not service:
        await query.message.answer("⚠️ Service not found or no longer available.")
        return

    text = (
        f"🏷️ **{service['title']}**\n\n"
        f"📝 **Description:**\n{service['description']}\n\n"
        f"💰 **Price:** `₹{service['price_inr']:.0f}`\n\n"
        "To purchase this service, click **Pay Now & Order** below to get the payment QR Code."
    )

    kb = get_service_detail_keyboard(service_id)
    if query.message.photo:
        await query.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await query.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
