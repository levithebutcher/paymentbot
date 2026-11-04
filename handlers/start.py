from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from database import upsert_user, get_services, get_user_orders
from keyboards.user_keyboards import get_main_menu_keyboard, get_services_keyboard

start_router = Router()

@start_router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    if user:
        await upsert_user(user.id, user.username, user.full_name)

    welcome_text = (
        f"👋 **Namaste {user.first_name if user else 'Friend'}!**\n\n"
        "Welcome to our automated **Payment & Service Bot**.\n\n"
        "Here you can browse available services, pay securely via **UPI QR Code**, "
        "and receive instant access once your payment proof is verified.\n\n"
        "👇 **Choose an option below to get started:**"
    )
    
    await message.answer(welcome_text, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
    
    # Also present the catalog directly
    services = await get_services()
    if services:
        await message.answer(
            "📋 **Available Services Catalog:**\nSelect a service below to view details and pricing:",
            reply_markup=get_services_keyboard(services),
            parse_mode="Markdown"
        )

@start_router.message(Command("help"))
@start_router.message(F.text == "ℹ️ Help & Support")
async def handle_help(message: Message):
    help_text = (
        "💡 **How to Order & Pay:**\n\n"
        "1. Tap **🛍️ View Services** and pick the service you want.\n"
        "2. Tap **💳 Pay Now & Order** to get the UPI QR Code and UPI ID.\n"
        "3. Scan the QR code using any UPI App (GPay, PhonePe, Paytm, CRED, etc.).\n"
        "4. Upload the **payment confirmation screenshot** in this chat.\n"
        "5. Enter the **12-digit UTR / Reference Number** from your banking receipt.\n"
        "6. Our team verifies the transaction and your service is delivered automatically!\n\n"
        "⚠️ **Note:** To prevent fraud, all UTRs are checked against our database. Reusing old or fake screenshots will be rejected.\n\n"
        "Need help? Contact support or type /cancel to abort an active order."
    )
    await message.answer(help_text, parse_mode="Markdown")

@start_router.message(Command("cancel"))
async def handle_cancel(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("ℹ️ There is no active order in progress.", reply_markup=get_main_menu_keyboard())
        return

    await state.clear()
    await message.answer(
        "❌ **Order cancelled.** You can start a fresh order anytime from the menu.",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="Markdown"
    )

@start_router.message(F.text == "📦 My Orders")
@start_router.callback_query(F.data == "view_my_orders")
async def handle_my_orders(event: Message | CallbackQuery):
    user_id = event.from_user.id
    orders = await get_user_orders(user_id)
    
    if not orders:
        text = "📦 **You have not placed any orders yet.**\n\nBrowse our services to make your first purchase!"
    else:
        text = "📦 **Your Recent Orders:**\n\n"
        for o in orders:
            status = o['status']
            if status == "COMPLETED":
                badge = "✅ COMPLETED"
            elif status == "PENDING_VERIFICATION":
                badge = "⏳ UNDER VERIFICATION"
            elif status == "REJECTED":
                badge = f"❌ REJECTED ({o.get('rejection_reason', 'Unverified')})"
            else:
                badge = "🟡 PENDING PAYMENT"

            text += (
                f"• **Order:** `#{o['order_id']}`\n"
                f"  Service: {o['service_title']}\n"
                f"  Amount: ₹{o['amount']:.0f}\n"
                f"  Status: {badge}\n"
                f"  Date: {o['created_at']}\n\n"
            )

    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.answer(text, parse_mode="Markdown")
    else:
        await event.answer(text, parse_mode="Markdown")
