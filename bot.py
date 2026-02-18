import os
import re
import json
from datetime import datetime
from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")  # твой Telegram user_id

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN is not set")

# ---- Простая "БД" каталога (для демо) ----
# Можно потом заменить на Google Sheets.
CATALOG = {
    "luna_mini": {
        "name": "Luna Mini",
        "price": 32900,
        "colors": ["чёрный", "бежевый"],
        "desc": "Компактная сумка на каждый день. Фурнитура премиум.",
    },
    "aura": {
        "name": "AURA",
        "price": 45900,
        "colors": ["чёрный", "молочный"],
        "desc": "Новая коллекция. Строгая форма, мягкая кожа.",
    },
    "vera": {
        "name": "Vera",
        "price": 38900,
        "colors": ["шоколад", "чёрный"],
        "desc": "Вместительная модель, отлично под офис и поездки.",
    },
    "iris": {
        "name": "Iris",
        "price": 29900,
        "colors": ["серый", "чёрный"],
        "desc": "Лёгкая базовая сумка. Хороший вариант на подарок.",
    },
    "nova": {
        "name": "Nova",
        "price": 51900,
        "colors": ["чёрный"],
        "desc": "Премиум-линейка. Максимум деталей и качества.",
    },
}

# ---- Хранилище заявок (для демо) ----
ORDERS = []  # список словарей

# ---- Состояния (Conversation) ----
WAIT_MODEL_OR_PHOTO, WAIT_CITY, WAIT_PHONE = range(3)


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👜 Узнать цену", callback_data="price")],
        [InlineKeyboardButton("📦 Каталог", callback_data="catalog")],
        [InlineKeyboardButton("🚚 Доставка", callback_data="delivery")],
        [InlineKeyboardButton("👩‍💼 Менеджер", callback_data="manager")],
    ])


def catalog_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for key, item in CATALOG.items():
        rows.append([InlineKeyboardButton(f"{item['name']} — {item['price']} ₸", callback_data=f"item:{key}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back")])
    return InlineKeyboardMarkup(rows)


def item_keyboard(item_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Оформить заказ", callback_data=f"order:{item_key}")],
        [InlineKeyboardButton("📦 Каталог", callback_data="catalog")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back")],
    ])


def safe_text(s: str) -> str:
    # Мы НЕ используем Markdown/HTML, чтобы не ловить "Can't parse entities"
    return s


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Здравствуйте! Я виртуальный менеджер магазина сумок 👜\n\n"
        "Могу:\n"
        "• подсказать цену и наличие\n"
        "• помочь выбрать модель\n"
        "• оформить заявку менеджеру\n\n"
        "Выберите действие:"
    )
    await update.message.reply_text(safe_text(text), reply_markup=main_menu())


async def on_menu_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    data = q.data

    if data == "price":
        await q.message.reply_text(
            "Напишите название модели (например: Luna Mini) или нажмите «Каталог».\n"
            "Если хотите — можете прислать фото, я предложу похожие варианты (демо).",
            reply_markup=catalog_keyboard()
        )
        return WAIT_MODEL_OR_PHOTO

    if data == "catalog":
        await q.message.reply_text("Выберите модель:", reply_markup=catalog_keyboard())
        return ConversationHandler.END

    if data == "delivery":
        await q.message.reply_text(
            "🚚 Доставка:\n"
            "• По городу: 1–2 дня\n"
            "• По Казахстану: 2–5 дней\n"
            "• Оплата и условия уточнит менеджер после заявки.\n\n"
            "Хотите оформить заказ?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Оформить заказ", callback_data="price")],
                [InlineKeyboardButton("⬅️ Назад", callback_data="back")],
            ])
        )
        return ConversationHandler.END

    if data == "manager":
        await q.message.reply_text(
            "👩‍💼 Менеджер подключится после заявки.\n"
            "Нажмите «Узнать цену» → выберите модель → «Оформить заказ».",
            reply_markup=main_menu()
        )
        return ConversationHandler.END

    if data == "back":
        await q.message.reply_text("Главное меню:", reply_markup=main_menu())
        return ConversationHandler.END

    # Показ конкретного товара
    if data.startswith("item:"):
        key = data.split(":", 1)[1]
        item = CATALOG.get(key)
        if not item:
            await q.message.reply_text("Не нашёл модель в каталоге.", reply_markup=main_menu())
            return ConversationHandler.END

        text = (
            f"👜 {item['name']}\n"
            f"💰 Цена: {item['price']} ₸\n"
            f"🎨 Цвета: {', '.join(item['colors'])}\n"
            f"📝 Описание: {item['desc']}\n\n"
            "Оформляем заказ?"
        )
        await q.message.reply_text(safe_text(text), reply_markup=item_keyboard(key))
        return ConversationHandler.END

    # Начинаем оформление
    if data.startswith("order:"):
        key = data.split(":", 1)[1]
        item = CATALOG.get(key)
        if not item:
            await q.message.reply_text("Не нашёл модель в каталоге.", reply_markup=main_menu())
            return ConversationHandler.END

        context.user_data["order_item_key"] = key
        await q.message.reply_text("Отлично! Напишите, пожалуйста, ваш город:")
        return WAIT_CITY

    return ConversationHandler.END


def find_item_by_text(text: str):
    t = text.strip().lower()
    # очень простой матчинг для демо
    for key, item in CATALOG.items():
        if item["name"].lower() in t:
            return key
    # если пользователь ввёл часть названия
    for key, item in CATALOG.items():
        if any(word in item["name"].lower() for word in t.split()):
            return key
    return None


async def on_model_or_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Пользователь может написать название или прислать фото
    if update.message.photo:
        # демо-логика: просим выбрать из каталога
        await update.message.reply_text(
            "Спасибо за фото! Чтобы назвать точную цену, выберите модель из каталога 👇",
            reply_markup=catalog_keyboard()
        )
        return ConversationHandler.END

    text = update.message.text or ""
    key = find_item_by_text(text)

    if not key:
        await update.message.reply_text(
            "Не понял модель 😅\nВыберите из каталога или напишите название точнее:",
            reply_markup=catalog_keyboard()
        )
        return WAIT_MODEL_OR_PHOTO

    item = CATALOG[key]
    msg = (
        f"Похоже на модель: {item['name']} ✅\n"
        f"Цена: {item['price']} ₸\n"
        f"В наличии цвета: {', '.join(item['colors'])}\n\n"
        "Оформляем заказ?"
    )
    await update.message.reply_text(msg, reply_markup=item_keyboard(key))
    return ConversationHandler.END


async def on_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = (update.message.text or "").strip()
    if len(city) < 2:
        await update.message.reply_text("Напишите город текстом (например: Алматы):")
        return WAIT_CITY

    context.user_data["order_city"] = city
    await update.message.reply_text("Теперь отправьте номер телефона (пример: +7 777 123 45 67):")
    return WAIT_PHONE


def normalize_phone(s: str) -> str:
    s = s.strip()
    # оставим + и цифры
    s = re.sub(r"[^\d+]", "", s)
    return s


async def on_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone_raw = update.message.text or ""
    phone = normalize_phone(phone_raw)

    # очень мягкая валидация
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 10:
        await update.message.reply_text("Похоже, номер короткий. Отправьте номер ещё раз (пример: +7 777 123 45 67):")
        return WAIT_PHONE

    item_key = context.user_data.get("order_item_key")
    city = context.user_data.get("order_city", "—")
    item = CATALOG.get(item_key, {"name": "—", "price": 0})

    user = update.effective_user
    order = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user_id": user.id,
        "username": user.username or "",
        "name": user.full_name or "",
        "city": city,
        "phone": phone,
        "item_key": item_key,
        "item_name": item.get("name"),
        "price": item.get("price"),
    }
    ORDERS.append(order)

    # Подтверждение клиенту
    await update.message.reply_text(
        "✅ Заявка принята!\n"
        "Менеджер скоро свяжется с вами.\n\n"
        "Хотите узнать цену другой модели?",
        reply_markup=main_menu()
    )

    # Уведомление админу/менеджеру
    if ADMIN_ID:
        admin_text = (
            "🆕 НОВАЯ ЗАЯВКА\n"
            f"Время: {order['ts']}\n"
            f"Клиент: {order['name']} (@{order['username']})\n"
            f"Город: {order['city']}\n"
            f"Телефон: {order['phone']}\n"
            f"Товар: {order['item_name']} — {order['price']} ₸\n"
            f"UserID: {order['user_id']}"
        )
        try:
            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_text)
        except Exception:
            pass

    # очистка
    context.user_data.pop("order_item_key", None)
    context.user_data.pop("order_city", None)

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ок, отменил. Главное меню:", reply_markup=main_menu())
    return ConversationHandler.END


def is_admin(user_id: int) -> bool:
    return ADMIN_ID and user_id == ADMIN_ID


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "🛠 Админ-панель (демо)\n\n"
        "/orders — последние заявки\n"
        "/reset — очистить заявки (демо)\n"
    )


async def orders_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not ORDERS:
        await update.message.reply_text("Заявок пока нет.")
        return

    last = ORDERS[-10:]
    lines = ["📌 Последние заявки:"]
    for o in last:
        lines.append(
            f"- {o['ts']} | {o['item_name']} | {o['city']} | {o['phone']} | {o['name']}"
        )
    await update.message.reply_text("\n".join(lines))


async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    ORDERS.clear()
    await update.message.reply_text("Ок, заявки очищены (демо).")


def build_app():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Главное меню через callback
    app.add_handler(CallbackQueryHandler(on_menu_click))

    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("orders", orders_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))

    # Диалог: узнать цену -> модель/фото
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(on_menu_click, pattern="^price$"),
        ],
        states={
            WAIT_MODEL_OR_PHOTO: [
                MessageHandler(filters.TEXT | filters.PHOTO, on_model_or_photo),
                CallbackQueryHandler(on_menu_click, pattern="^(catalog|back|item:|order:|delivery|manager)$"),
            ],
            WAIT_CITY: [
                MessageHandler(filters.TEXT, on_city),
            ],
            WAIT_PHONE: [
                MessageHandler(filters.TEXT, on_phone),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    async def _startup(app):
        await app.bot.delete_webhook(drop_pending_updates=True)

    app.post_init = _startup

    app.add_handler(conv)

    app.run_polling(drop_pending_updates=True)


    # ВАЖНО: ConversationHandler должен быть ДО общего CallbackQueryHandler, но мы уже добавили общий.
    # Поэтому пересоберём порядок: удалим общий и добавим правильно.
    # (В python-telegram-bot порядок важен.)
    app.handlers[0].clear()
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(on_menu_click))
    return app


if __name__ == "__main__":
    await app.bot.delete_webhook(drop_pending_updates=True)
    application = build_app()
    application.run_polling()
