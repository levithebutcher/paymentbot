from aiogram.fsm.state import State, StatesGroup

class OrderFlow(StatesGroup):
    waiting_for_screenshot = State()
    waiting_for_utr = State()

class AddServiceFlow(StatesGroup):
    waiting_for_id = State()
    waiting_for_title = State()
    waiting_for_description = State()
    waiting_for_price = State()
    waiting_for_delivery = State()

class EditServiceFlow(StatesGroup):
    waiting_for_new_price = State()
    waiting_for_new_delivery = State()
    waiting_for_new_title = State()

class BroadcastFlow(StatesGroup):
    waiting_for_content = State()
    waiting_for_confirmation = State()

class EditPaymentFlow(StatesGroup):
    waiting_for_upi_id = State()
    waiting_for_qr_photo = State()
    waiting_for_payee_name = State()
