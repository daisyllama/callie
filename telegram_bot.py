import logging
import os
from datetime import datetime

import pytz
from pyairtable import Table
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from openai_api import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_THINK,
    DEFAULT_OPENAI_MODEL,
    OpenAIMacroError,
    get_macros_from_meal_description,
)


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def get_gmt8_today():
    tz = pytz.timezone("Asia/Singapore")
    return datetime.now(tz).date()


def parse_bool_env(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_int_set_env(name):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return set()
    values = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            values.add(int(part))
        except ValueError:
            logger.warning("Skipping invalid TELEGRAM_ALLOWED_USER_IDS value: %s", part)
    return values


def parse_int_env(name, default):
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning("Invalid %s value %r. Falling back to %s", name, raw, default)
        return default


def get_meals_table():
    api_key = os.environ.get("AIRTABLE_API_KEY")
    base_id = os.environ.get("AIRTABLE_BASE_ID")
    if not api_key or not base_id:
        raise RuntimeError("AIRTABLE_API_KEY and AIRTABLE_BASE_ID are required for telegram bot.")
    return Table(api_key, base_id, "Meals")


def save_meal_to_airtable(meals_table, meal_date, meal_name, calories, protein, fat, cholesterol, carbs):
    meals_table.create(
        {
            "date": meal_date.strftime("%Y-%m-%d"),
            "meal": meal_name,
            "calories_kcal": 0 if calories is None else calories,
            "protein_g": 0 if protein is None else protein,
            "fat_g": 0 if fat is None else fat,
            "cholesterol_mg": 0 if cholesterol is None else cholesterol,
            "carbs_g": 0 if carbs is None else carbs,
        }
    )


def format_macro_preview(payload):
    return (
        "I parsed this meal:\n\n"
        f"Meal: {payload['meal_name'] or '(unknown)'}\n"
        f"Calories: {payload['calories']} kcal\n"
        f"Protein: {payload['protein']} g\n"
        f"Fat: {payload['fat']} g\n"
        f"Cholesterol: {payload['cholesterol']} mg\n"
        f"Carbs: {payload['carbs']} g\n\n"
        "Save this to Airtable?"
    )


def normalize_macro_payload(macro_tuple):
    meal_name, calories, protein, fat, cholesterol, carbs = macro_tuple
    return {
        "meal_name": (meal_name or "").strip(),
        "calories": 0 if calories is None else int(calories),
        "protein": 0 if protein is None else int(protein),
        "fat": 0 if fat is None else int(fat),
        "cholesterol": 0 if cholesterol is None else int(cholesterol),
        "carbs": 0 if carbs is None else int(carbs),
    }


def is_allowed_user(update: Update, allowed_ids):
    if not allowed_ids:
        return True
    user = update.effective_user
    return bool(user and user.id in allowed_ids)


async def deny_if_not_allowed(update: Update, allowed_ids):
    if is_allowed_user(update, allowed_ids):
        return False

    if update.message:
        await update.message.reply_text("You are not authorized to use this bot.")
    elif update.callback_query:
        await update.callback_query.answer("Unauthorized", show_alert=True)
    return True


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    allowed_ids = context.bot_data["allowed_ids"]
    if await deny_if_not_allowed(update, allowed_ids):
        return

    await update.message.reply_text(
        "Send a meal description and I’ll estimate macros, then ask for confirmation before saving.\n\n"
        "Examples:\n"
        "- 2 eggs and toast\n"
        "- chicken rice with cucumber\n\n"
        "Commands:\n"
        "/start\n"
        "/help\n"
        "/log <meal description>"
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    allowed_ids = context.bot_data["allowed_ids"]
    if await deny_if_not_allowed(update, allowed_ids):
        return

    await update.message.reply_text(
        "Usage:\n"
        "1) Send meal text (or /log <meal>).\n"
        "2) Review parsed macros.\n"
        "3) Tap Save or Cancel.\n\n"
        "Config env vars:\n"
        "TELEGRAM_BOT_TOKEN, AIRTABLE_API_KEY, AIRTABLE_BASE_ID, OPENAI_API_KEY\n"
        "Optional: TELEGRAM_USE_LOCAL_MODEL=true"
    )


async def parse_and_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, meal_description: str):
    allowed_ids = context.bot_data["allowed_ids"]
    if await deny_if_not_allowed(update, allowed_ids):
        return

    meal_description = (meal_description or "").strip()
    if not meal_description:
        await update.message.reply_text("Please send a meal description.")
        return

    use_local = context.bot_data["use_local"]
    openai_model = context.bot_data["openai_model"]
    local_model = context.bot_data["local_model"]
    max_tokens = context.bot_data["max_tokens"]
    ollama_think = context.bot_data["ollama_think"]

    try:
        macro_tuple = get_macros_from_meal_description(
            meal_description,
            model=openai_model,
            max_tokens=max_tokens,
            use_local=use_local,
            local_model=local_model,
            think=ollama_think,
        )
        payload = normalize_macro_payload(macro_tuple)
    except OpenAIMacroError as exc:
        await update.message.reply_text(f"AI error: {exc}")
        return
    except Exception as exc:
        logger.exception("Unexpected parsing error")
        await update.message.reply_text(f"Unexpected error: {exc}")
        return

    context.user_data["pending_macro"] = payload

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Save ✅", callback_data="save_meal"),
                InlineKeyboardButton("Cancel ❌", callback_data="cancel_meal"),
            ]
        ]
    )

    await update.message.reply_text(format_macro_preview(payload), reply_markup=keyboard)


async def log_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args).strip()
    await parse_and_confirm(update, context, text)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await parse_and_confirm(update, context, update.message.text)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    allowed_ids = context.bot_data["allowed_ids"]
    if await deny_if_not_allowed(update, allowed_ids):
        return

    query = update.callback_query
    await query.answer()

    if query.data == "cancel_meal":
        context.user_data.pop("pending_macro", None)
        await query.edit_message_text("Cancelled. Send another meal when ready.")
        return

    if query.data != "save_meal":
        await query.edit_message_text("Unknown action.")
        return

    payload = context.user_data.get("pending_macro")
    if not payload:
        await query.edit_message_text("No pending meal found. Send a new meal first.")
        return

    try:
        save_meal_to_airtable(
            context.bot_data["meals_table"],
            get_gmt8_today(),
            payload["meal_name"] or "Meal from Telegram",
            payload["calories"],
            payload["protein"],
            payload["fat"],
            payload["cholesterol"],
            payload["carbs"],
        )
        context.user_data.pop("pending_macro", None)
        await query.edit_message_text("Saved to Airtable ✅")
    except Exception as exc:
        logger.exception("Failed to save meal")
        await query.edit_message_text(f"Failed to save meal: {exc}")


def build_app():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required.")

    app: Application = ApplicationBuilder().token(token).build()

    app.bot_data["meals_table"] = get_meals_table()
    app.bot_data["use_local"] = parse_bool_env("TELEGRAM_USE_LOCAL_MODEL", default=True)
    app.bot_data["openai_model"] = os.environ.get("TELEGRAM_OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
    app.bot_data["local_model"] = os.environ.get("TELEGRAM_LOCAL_MODEL", DEFAULT_OLLAMA_MODEL)
    app.bot_data["max_tokens"] = parse_int_env("TELEGRAM_MAX_TOKENS", DEFAULT_MAX_TOKENS)
    app.bot_data["ollama_think"] = os.environ.get("TELEGRAM_OLLAMA_THINK", DEFAULT_OLLAMA_THINK)
    app.bot_data["allowed_ids"] = parse_int_set_env("TELEGRAM_ALLOWED_USER_IDS")

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("log", log_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    return app


def main():
    app = build_app()
    logger.info("Telegram bot started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
