# states/deposit_states.py

from aiogram.fsm.state import State, StatesGroup


class DepositState(StatesGroup):
    waiting_network = State()
    waiting_amount = State()
    waiting_optional_promo = State()  # Optional promocode during deposit flow
    waiting_promo_code = State()      # Direct promocode redemption from menu
    waiting_txid = State()