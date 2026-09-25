"""
utils/ui.py

Everything the bot shows to a user or admin lives in ONE message per
chat -- the "card". Tapping a button updates that same card instead of
sending a new message underneath it, and typing a reply (quantity,
amount, tx hash, promo code, etc.) also updates that same card instead
of spamming the chat with a fresh bubble for every step.

Two helpers cover every situation in this codebase:

- show(callback, ...)        -> use inside @router.callback_query handlers.
                                 Edits the tapped message in place.

- update_card(message, ...)  -> use inside @router.message handlers that
                                 are replying to a typed answer (quantity,
                                 deposit amount, tx hash, promo code, ...).
                                 Edits the card that was last shown via
                                 show(..., state=state), and deletes the
                                 user's input message so it doesn't linger
                                 in the chat.

Both fall back to sending a fresh message only when editing is truly
impossible (card too old / deleted / never existed yet), so nothing
ever silently fails to respond.
"""

import logging
from html.parser import HTMLParser

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

logger = logging.getLogger(__name__)

# Telegram's hard cap on message text (after HTML entity parsing).
# Leave real headroom below the true 4096 limit for the truncation
# notice itself plus any small counting differences.
TELEGRAM_TEXT_LIMIT = 4096
SAFE_TEXT_LIMIT = 3900

# Keys used inside FSMContext data to remember which message is the
# "card" for a given chat, so text-reply steps know what to edit.
_CARD_CHAT_ID_KEY = "_card_chat_id"
_CARD_MESSAGE_ID_KEY = "_card_message_id"


class _HTMLTruncator(HTMLParser):
    """Cuts HTML-formatted text down to `limit` visible characters
    without ever leaving a tag unclosed. Text like product
    descriptions may contain real <blockquote>/<b> tags (e.g. typed
    by an admin) — a plain text[:limit] slice could sever a tag mid-
    way and either get rejected by Telegram or render broken."""

    def __init__(self, limit: int):
        super().__init__(convert_charrefs=False)
        self.limit = limit
        self.output: list[str] = []
        self.open_tags: list[str] = []
        self.count = 0
        self.truncated = False

    def handle_starttag(self, tag, attrs):
        if self.truncated:
            return
        attr_str = "".join(f' {k}="{v}"' for k, v in attrs if v is not None)
        self.output.append(f"<{tag}{attr_str}>")
        self.open_tags.append(tag)

    def handle_startendtag(self, tag, attrs):
        if self.truncated:
            return
        attr_str = "".join(f' {k}="{v}"' for k, v in attrs if v is not None)
        self.output.append(f"<{tag}{attr_str}/>")

    def handle_endtag(self, tag):
        if self.truncated:
            return
        self.output.append(f"</{tag}>")
        for i in range(len(self.open_tags) - 1, -1, -1):
            if self.open_tags[i] == tag:
                del self.open_tags[i]
                break

    def handle_data(self, data):
        if self.truncated:
            return
        remaining = self.limit - self.count
        if remaining <= 0:
            self.truncated = True
            return
        if len(data) > remaining:
            self.output.append(data[:remaining])
            self.count += remaining
            self.truncated = True
        else:
            self.output.append(data)
            self.count += len(data)

    def handle_entityref(self, name):
        if self.truncated:
            return
        if self.count >= self.limit:
            self.truncated = True
            return
        self.output.append(f"&{name};")
        self.count += 1

    def handle_charref(self, name):
        if self.truncated:
            return
        if self.count >= self.limit:
            self.truncated = True
            return
        self.output.append(f"&#{name};")
        self.count += 1

    def get_result(self) -> str:
        result = "".join(self.output)
        for tag in reversed(self.open_tags):
            result += f"</{tag}>"
        return result


def truncate_html(text: str, limit: int = SAFE_TEXT_LIMIT) -> str:
    """Safely shorten HTML-formatted text to at most `limit` visible
    characters, always leaving well-formed HTML (every opened tag is
    closed). Appends a short notice when content was actually cut."""
    if len(text) <= limit:
        return text
    parser = _HTMLTruncator(limit)
    parser.feed(text)
    result = parser.get_result()
    if parser.truncated:
        result += "\n\n<i>… (message truncated — too long to display in full)</i>"
    return result


def _kwargs(reply_markup, parse_mode):
    """Only pass parse_mode through when explicitly given, so callers
    that don't set it keep relying on the bot's default parse mode
    (HTML, configured in main.py) instead of Telegram disabling
    parsing entirely."""
    kwargs = {"reply_markup": reply_markup}
    if parse_mode is not None:
        kwargs["parse_mode"] = parse_mode
    return kwargs


async def show(
    callback: CallbackQuery,
    text: str,
    reply_markup=None,
    parse_mode: str | None = None,
    state=None,
):
    """
    Single-card navigation for button taps: edits the tapped message
    in place instead of sending a new one underneath it.

    Pass state=... whenever this screen may be followed by a typed
    reply (e.g. "send the quantity", "send the amount") so that the
    follow-up message handler knows which card to keep editing.
    """
    kwargs = _kwargs(reply_markup, parse_mode)

    try:
        msg = await callback.message.edit_text(text, **kwargs)
    except TelegramBadRequest as e:
        err = str(e).lower()
        if "message is not modified" in err:
            msg = callback.message
        elif "message is too long" in err:
            # The text itself exceeds Telegram's 4096-char limit (e.g.
            # a long product description). Truncate safely (keeping
            # HTML well-formed) and retry instead of repeating the
            # exact failure on the fallback send below.
            logger.warning("show(): message too long (%d chars), truncating", len(text))
            safe_text = truncate_html(text)
            safe_kwargs = _kwargs(reply_markup, parse_mode)
            try:
                msg = await callback.message.edit_text(safe_text, **safe_kwargs)
            except TelegramBadRequest as e2:
                logger.info("show(): edit_text failed after truncation (%s), sending a new message", e2)
                msg = await callback.message.answer(safe_text, **safe_kwargs)
        else:
            # Card can no longer be edited (too old, deleted, or the
            # very first message in the chat isn't text) -- fall back
            # to sending a fresh one rather than losing the response.
            logger.info("show(): edit_text failed (%s), sending a new message", e)
            msg = await callback.message.answer(text, **kwargs)

    if state is not None:
        await state.update_data(
            **{_CARD_CHAT_ID_KEY: msg.chat.id, _CARD_MESSAGE_ID_KEY: msg.message_id}
        )

    return msg


async def update_card(
    message: Message,
    state=None,
    text: str = "",
    reply_markup=None,
    parse_mode: str | None = None,
    delete_input: bool = True,
    chat_id: int | None = None,
    message_id: int | None = None,
):
    """
    Single-card navigation for typed replies: edits the same card that
    show() last displayed instead of sending a new message, and
    deletes the user's input message so the chat stays a single,
    continuously-updating card.

    - state: FSMContext to read the tracked card id from (and to keep
      tracking it going forward). Pass None if you already have the
      exact chat_id/message_id to edit (e.g. you captured them earlier
      in the same handler, before clearing the state).
    - chat_id/message_id: explicit override, used instead of / in
      addition to whatever is in state.

    Falls back to sending (and starting to track) a brand new card if
    there's nothing to edit yet, or the old card can't be edited
    anymore.
    """
    if delete_input:
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
        except Exception:
            pass

    if (chat_id is None or message_id is None) and state is not None:
        data = await state.get_data()
        chat_id = chat_id or data.get(_CARD_CHAT_ID_KEY)
        message_id = message_id or data.get(_CARD_MESSAGE_ID_KEY)

    kwargs = _kwargs(reply_markup, parse_mode)

    if chat_id and message_id:
        try:
            msg = await message.bot.edit_message_text(
                text, chat_id=chat_id, message_id=message_id, **kwargs
            )
            if state is not None:
                await state.update_data(
                    **{_CARD_CHAT_ID_KEY: msg.chat.id, _CARD_MESSAGE_ID_KEY: msg.message_id}
                )
            return msg
        except TelegramBadRequest as e:
            err = str(e).lower()
            if "message is not modified" in err:
                return None
            if "message is too long" in err:
                logger.warning("update_card(): message too long (%d chars), truncating", len(text))
                text = truncate_html(text)
                kwargs = _kwargs(reply_markup, parse_mode)
                try:
                    msg = await message.bot.edit_message_text(
                        text, chat_id=chat_id, message_id=message_id, **kwargs
                    )
                    if state is not None:
                        await state.update_data(
                            **{_CARD_CHAT_ID_KEY: msg.chat.id, _CARD_MESSAGE_ID_KEY: msg.message_id}
                        )
                    return msg
                except TelegramBadRequest as e2:
                    logger.info("update_card(): edit failed after truncation (%s), sending a new card", e2)
            else:
                logger.info("update_card(): edit failed (%s), sending a new card", e)

    msg = await message.answer(text, **kwargs)
    if state is not None:
        await state.update_data(
            **{_CARD_CHAT_ID_KEY: msg.chat.id, _CARD_MESSAGE_ID_KEY: msg.message_id}
        )
    return msg