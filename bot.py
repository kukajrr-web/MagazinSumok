import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from ai_engine import ask_ai
from catalog import CATALOG

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

logging.basicConfig(level=logging.INFO)

# Демo фото (сюда вставим file_id после первого получения)
PHOTO_MODEL_MAP = {
    # "AgACAgQAAxkBAA..." : "luna_mini"
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Здравствуйте 👜\n"
        "Пришлите фото сумки или напишите, что вас интересует."
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_id = update.message.photo[-1].file_id

    if file_id in PHOTO_MODEL_MAP:
        key = PHOTO_MODEL_MAP[file_id]
        item = CATALOG[key]

        await update.message.reply_text(
            f"Это модель {item['name']} 👜\n"
            f"Цена: {item['price']} ₸\n"
            f"В наличии цвета: {', '.join(item['colors'])}\n\n"
            "Оформляем заказ?"
        )

    else:
        await update.message.reply_text(
            "Эта модель есть в нашем каталоге.\n"
            "Чтобы назвать точную цену, напишите название модели или уточните цвет."
        )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text

    ai_reply = ask_ai(user_text)

    await update.message.reply_text(ai_reply)

async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    await app.bot.delete_webhook(drop_pending_updates=True)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
