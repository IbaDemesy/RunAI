"""Canal Telegram (python-telegram-bot 22) branche sur l'orchestrateur RunAI (mock ici).

Fonctions : note vocale -> Gladia pre-enregistre -> mission ; message de suivi des 3 agents edite en place ;
validation par boutons inline avec capture ; envoi PDF/.ics/GPX ; bouton Mini App (PWA) ; partage de position.

Lancer en polling (aucune URL publique requise) : TELEGRAM_BOT_TOKEN=... python telegram_bot.py
Mini App : RUNAI_PWA_URL=https://... (HTTPS obligatoire cote Telegram).
"""

import hashlib
import hmac
import io
import json
import logging
import os
from urllib.parse import parse_qsl

from artifacts import course_gpx, race_ics, recap_pdf
from gladia_live import RUNAI_VOCABULARY
from gladia_prerecorded import transcribe_bytes
from orchestrator import AGENT_LABELS, AGENTS, MockOrchestrator
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
    WebAppInfo,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

log = logging.getLogger("runai.telegram")

STATUS_ICON = {
    "queued": "⏳",
    "running": "🔄",
    "awaiting_validation": "✋",
    "ready": "✅",
    "refused": "⛔",
    "failed": "❌",
}


def render_progress(mission) -> str:
    lines = [f"RunAI · mission {mission.id}", mission.race.get("name", "")]
    for agent in AGENTS:
        status = mission.statuses[agent]
        lines.append(
            f"{STATUS_ICON.get(status, '•')} {AGENT_LABELS[agent]} : {status.replace('_', ' ')}"
        )
    return "\n".join(lines)


def validation_keyboard(
    mission_id: str, agent: str, live_url: str | None = None
) -> InlineKeyboardMarkup:
    see = (
        InlineKeyboardButton("Voir", url=live_url)
        if live_url
        else InlineKeyboardButton("Voir", callback_data=f"see|{mission_id}|{agent}")
    )
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Je valide", callback_data=f"ok|{mission_id}|{agent}"
                ),
                InlineKeyboardButton(
                    "Refuser", callback_data=f"no|{mission_id}|{agent}"
                ),
            ],
            [see],
        ]
    )


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📍 Partager ma position", request_location=True)]],
        resize_keyboard=True,
    )


def miniapp_markup(mission_id: str | None = None) -> InlineKeyboardMarkup | None:
    url = os.environ.get("RUNAI_PWA_URL", "")
    if not url.startswith("https://"):
        return None  # Telegram refuse une WebApp hors HTTPS
    if mission_id:
        url += ("&" if "?" in url else "?") + f"mission={mission_id}"
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Ouvrir RunAI", web_app=WebAppInfo(url=url))]]
    )


def validate_init_data(init_data: str, bot_token: str) -> dict | None:
    """Verifie Telegram.WebApp.initData cote backend (core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app)."""
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return pairs if hmac.compare_digest(expected, received) else None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Dis ta course en note vocale (ex : « trouve-moi un semi en avril et prépare tout »). "
        "Je prépare inscription, hôtel et transport ; tu valides et tu paies toi-même.",
        reply_markup=main_keyboard(),
    )
    markup = miniapp_markup()
    if markup:
        await update.message.reply_text("Ou ouvre l'appli :", reply_markup=markup)


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    voice = update.message.voice or update.message.audio
    tg_file = await context.bot.get_file(voice.file_id)
    audio = bytes(await tg_file.download_as_bytearray())
    transcribe = context.bot_data.get("transcribe", transcribe_bytes)
    result = await transcribe(
        audio,
        filename="voice.ogg",
        content_type=voice.mime_type or "audio/ogg",
        vocabulary=RUNAI_VOCABULARY,
    )
    await update.message.reply_text(f"🎙️ J'ai compris : « {result.text} »")
    await launch_mission(update, context, result.text)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await launch_mission(update, context, update.message.text)


async def launch_mission(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    orch = context.bot_data["orchestrator"]
    mission = await orch.start_mission(text, "telegram", str(update.effective_chat.id))
    progress = await update.message.reply_text(
        render_progress(mission), reply_markup=miniapp_markup(mission.id)
    )
    task = context.application.create_task(
        follow_mission(
            context, update.effective_chat.id, progress.message_id, mission.id
        ),
        update=update,
    )
    context.bot_data.setdefault("tasks", []).append(task)


async def follow_mission(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, mission_id: str
) -> None:
    orch = context.bot_data["orchestrator"]
    mission = orch.missions[mission_id]
    async for upd in orch.updates(mission_id):
        await context.bot.edit_message_text(
            render_progress(mission) + f"\n\nDernière étape : {upd.detail}",
            chat_id=chat_id,
            message_id=message_id,
        )
        if upd.status == "awaiting_validation":
            await context.bot.send_photo(
                chat_id,
                photo=InputFile(
                    io.BytesIO(upd.screenshot_png or b""), filename=f"{upd.agent}.png"
                ),
                caption=f"{AGENT_LABELS[upd.agent]} : {upd.detail}\nRien n'est payé. Tu valides ?",
                reply_markup=validation_keyboard(mission_id, upd.agent),
            )


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    action, mission_id, agent = query.data.split("|")
    orch = context.bot_data["orchestrator"]
    mission = orch.missions.get(mission_id)
    if mission is None:
        await query.answer("Mission inconnue", show_alert=True)
        return
    if action == "see":
        await query.answer("Vue live H : disponible dans l'appli")
        return
    upd = await orch.decide(mission_id, agent, approved=action == "ok")
    await query.answer("Validé" if action == "ok" else "Refusé")
    await query.edit_message_caption(caption=f"{AGENT_LABELS[agent]} : {upd.detail}")
    if all(a in mission.decisions for a in AGENTS):
        await send_recap(context, query.message.chat.id, mission)


async def send_recap(context: ContextTypes.DEFAULT_TYPE, chat_id: int, mission) -> None:
    await context.bot.send_document(
        chat_id,
        InputFile(io.BytesIO(recap_pdf(mission)), filename=f"runai_{mission.id}.pdf"),
        caption="Récap du week-end",
    )
    await context.bot.send_document(
        chat_id,
        InputFile(io.BytesIO(race_ics(mission)), filename="course.ics"),
        caption="À ajouter à ton agenda",
    )
    await context.bot.send_document(
        chat_id,
        InputFile(io.BytesIO(course_gpx(mission)), filename="parcours.gpx"),
        caption="Parcours (GPX)",
    )


async def on_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    loc = update.message.location
    context.user_data["location"] = (loc.latitude, loc.longitude)
    await update.message.reply_text(
        f"📍 Position reçue ({loc.latitude:.4f}, {loc.longitude:.4f}) : je cherche le transport depuis ici."
    )


async def on_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = json.loads(update.effective_message.web_app_data.data)
    await update.effective_message.reply_text(
        f"Reçu de l'appli : {data.get('action', '?')}"
    )


def build_application(
    token: str, orchestrator=None, transcribe=None, request=None
) -> Application:
    builder = Application.builder().token(token)
    if request is not None:
        builder = builder.request(request).get_updates_request(request)
    app = builder.build()
    app.bot_data["orchestrator"] = orchestrator or MockOrchestrator(
        step_delay=float(os.environ.get("MOCK_STEP_DELAY", "3"))
    )
    if transcribe is not None:
        app.bot_data["transcribe"] = transcribe
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.LOCATION, on_location))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, on_webapp_data))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(CallbackQueryHandler(on_button))
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN manquant : creer le bot avec @BotFather (/newbot)"
        )
    app = build_application(token)
    webhook = os.environ.get(
        "TELEGRAM_WEBHOOK_URL"
    )  # https://hote/telegram ; ports autorises 443, 80, 88, 8443
    if webhook:
        app.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", "8443")),
            url_path="telegram",
            webhook_url=webhook,
            secret_token=os.environ.get("TELEGRAM_WEBHOOK_SECRET"),
        )
    else:
        app.run_polling()


if __name__ == "__main__":
    main()
