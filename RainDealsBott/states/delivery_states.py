from aiogram.fsm.state import (
    StatesGroup,
    State
)


class DeliverOrder(StatesGroup):
    content = State()
