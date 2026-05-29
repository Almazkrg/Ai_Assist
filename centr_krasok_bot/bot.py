import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta

from anthropic import Anthropic
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from company_data import COMPANY_KNOWLEDGE_BASE
logging.basicConfig(
    format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
TELEGRAM_TOKEN    = os.environ["TELEGRAM_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
MAX_CONTEXT_MESSAGES = 10
CONTEXT_TTL_HOURS    = 2
MAX_RESPONSE_TOKENS  = 600
QUICK_BUTTONS = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("🎨 Какие краски есть?",   callback_data="q_краски"),
        InlineKeyboardButton("📍 Где магазин?",          callback_data="q_адрес"),
    ],
    [
        InlineKeyboardButton("🚚 Как заказать?",         callback_data="q_доставка"),
        InlineKeyboardButton("💰 Есть акции?",           callback_data="q_акции"),
    ],
    [
        InlineKeyboardButton("🏷️ Какие бренды?",        callback_data="q_бренды"),
        InlineKeyboardButton("📞 Контакты",              callback_data="q_контакты"),
    ],
])

SYSTEM_PROMPT = f"""Ты — дружелюбный AI-ассистент интернет-магазина «Центр Красок #1» (centr-krasok.kz).
Твоя задача — отвечать на вопросы покупателей ИСКЛЮЧИТЕЛЬНО на основе базы знаний ниже.

БАЗА ЗНАНИЙ:
{COMPANY_KNOWLEDGE_BASE}

ПРАВИЛА:
1. Отвечай ТОЛЬКО на основе базы знаний. Не придумывай факты.
2. Если вопрос не про компанию — вежливо объясни, что помогаешь только по вопросам магазина.
3. Если информации нет в базе — скажи честно и предложи позвонить: +7 778 061-50-00.
4. Отвечай на языке пользователя (русский / казахский / английский).
5. Будь краток и конкретен. Используй эмодзи умеренно.
6. Цены на конкретные товары — отправляй на сайт centr-krasok.kz.
7. Никогда не называй себя ChatGPT — ты ассистент «Центр Красок #1».
"""

anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)
conversation_store: dict = defaultdict(
    lambda: {"messages": [], "last_activity": datetime.now()}
)


def get_conversation(chat_id: int) -> list[dict]:
    data = conversation_store[chat_id]
    if datetime.now() - data["last_activity"] > timedelta(hours=CONTEXT_TTL_HOURS):
        data["messages"] = []
        logger.info(f"Контекст сброшен: chat_id={chat_id}")
    data["last_activity"] = datetime.now()
    return data["messages"]


def add_message(chat_id: int, role: str, content: str) -> None:
    messages = get_conversation(chat_id)
    messages.append({"role": role, "content": content})
    if len(messages) > MAX_CONTEXT_MESSAGES:
        conversation_store[chat_id]["messages"] = messages[-MAX_CONTEXT_MESSAGES:]

async def ask_claude(chat_id: int, user_text: str) -> str:
    add_message(chat_id, "user", user_text)
    try:
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=MAX_RESPONSE_TOKENS,
            system=SYSTEM_PROMPT,
            messages=get_conversation(chat_id),
        )
        reply = response.content[0].text.strip()
        add_message(chat_id, "assistant", reply)
        logger.info(f"[{chat_id}] AI ответил ({len(reply)} симв.)")
        return reply
    except Exception as e:
        logger.error(f"Ошибка Claude API: {e}", exc_info=True)
        return (
            "⚠️ Произошла ошибка. Попробуйте ещё раз или позвоните нам:\n"
            "📞 +7 778 061-50-00"
        )


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id    = update.effective_chat.id
    first_name = update.effective_user.first_name or "друг"

    conversation_store[chat_id] = {"messages": [], "last_activity": datetime.now()}

    welcome = (
        f"👋 Привет, {first_name}!\n\n"
        "Я — AI-ассистент магазина «Центр Красок #1» 🎨\n\n"
        "Отвечаю на вопросы о компании, красках, доставке и многом другом.\n\n"
        "Выберите вопрос или напишите свой 👇"
    )
    await update.message.reply_text(welcome, reply_markup=QUICK_BUTTONS)


async def handle_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    conversation_store[chat_id] = {"messages": [], "last_activity": datetime.now()}
    await update.message.reply_text(
        "🔄 История очищена. Начнём заново!",
        reply_markup=QUICK_BUTTONS,
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    chat_id   = update.effective_chat.id
    user_text = update.message.text.strip()
    username  = update.effective_user.username or update.effective_user.first_name
    logger.info(f"[{chat_id}] @{username}: {user_text[:80]}")

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    reply = await ask_claude(chat_id, user_text)

    await update.message.reply_text(reply, reply_markup=QUICK_BUTTONS)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer() 

    chat_id = update.effective_chat.id

    questions = {
        "q_краски":   "Какие краски есть в наличии?",
        "q_адрес":    "Где находится магазин? Адрес и режим работы?",
        "q_доставка": "Как сделать заказ и оформить доставку?",
        "q_акции":    "Какие сейчас есть акции и скидки?",
        "q_бренды":   "Какие бренды красок представлены?",
        "q_контакты": "Контакты компании: телефон, email, соцсети.",
    }

    user_text = questions.get(query.data, query.data)
    logger.info(f"[{chat_id}] Кнопка: {user_text}")

    await query.message.reply_text(f"🙋 {user_text}")

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    reply = await ask_claude(chat_id, user_text)
    await query.message.reply_text(reply, reply_markup=QUICK_BUTTONS)

def main() -> None:
    logger.info("Запуск бота «Центр Красок #1»...")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("reset", handle_reset))
    app.add_handler(CommandHandler("help",  handle_start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Бот запущен. Ожидание сообщений...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
