"""
╔══════════════════════════════════════════════╗
║   Social Media Downloader Bot - Telegram     ║
║   يدعم: YouTube, Instagram, TikTok, Twitter  ║
╚══════════════════════════════════════════════╝

المتطلبات:
    pip install python-telegram-bot yt-dlp instaloader requests

الإعداد:
    1. أنشئ بوت من @BotFather واحصل على TOKEN
    2. ضع التوكن في متغير BOT_TOKEN أدناه
    3. شغّل: python bot.py
"""

import os
import re
import logging
import asyncio
import tempfile
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
import yt_dlp

# ─────────────────────────────────────────────
#  الإعدادات
# ─────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN")   # ← ضع توكنك هنا

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# المنصات المدعومة
SUPPORTED_PLATFORMS = {
    "youtube":   r"(youtube\.com|youtu\.be)",
    "instagram": r"(instagram\.com|instagr\.am)",
    "tiktok":    r"(tiktok\.com|vm\.tiktok\.com)",
    "twitter":   r"(twitter\.com|x\.com|t\.co)",
    "facebook":  r"(facebook\.com|fb\.watch|fb\.com)",
    "reddit":    r"(reddit\.com|redd\.it)",
    "pinterest": r"(pinterest\.com|pin\.it)",
    "snapchat":  r"(snapchat\.com)",
    "twitch":    r"(twitch\.tv|clips\.twitch\.tv)",
    "vimeo":     r"(vimeo\.com)",
}

PLATFORM_EMOJI = {
    "youtube":   "🔴",
    "instagram": "📸",
    "tiktok":    "🎵",
    "twitter":   "🐦",
    "facebook":  "🔵",
    "reddit":    "🟠",
    "pinterest": "📌",
    "snapchat":  "👻",
    "twitch":    "💜",
    "vimeo":     "🎬",
    "unknown":   "🌐",
}

# ─────────────────────────────────────────────
#  مساعدات
# ─────────────────────────────────────────────

def detect_platform(url: str) -> str:
    for name, pattern in SUPPORTED_PLATFORMS.items():
        if re.search(pattern, url, re.IGNORECASE):
            return name
    return "unknown"


def extract_urls(text: str) -> list[str]:
    pattern = r"https?://[^\s]+"
    return re.findall(pattern, text)


def format_size(bytes_val: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} TB"


def format_duration(seconds: int) -> str:
    if not seconds:
        return "—"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ─────────────────────────────────────────────
#  جلب معلومات الفيديو
# ─────────────────────────────────────────────

def get_video_info(url: str) -> dict | None:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info
    except Exception as e:
        logger.error(f"Error fetching info: {e}")
        return None


def get_available_formats(info: dict) -> list[dict]:
    """استخراج الجودات المتاحة"""
    formats = []
    seen = set()

    for f in info.get("formats", []):
        height = f.get("height")
        ext = f.get("ext", "mp4")
        vcodec = f.get("vcodec", "none")
        acodec = f.get("acodec", "none")

        # تجاهل الصوت فقط في القائمة الرئيسية
        if vcodec == "none" or height is None:
            continue

        label = f"{height}p"
        if label in seen:
            continue
        seen.add(label)

        formats.append({
            "format_id": f["format_id"],
            "label": label,
            "height": height,
            "ext": ext,
            "filesize": f.get("filesize") or f.get("filesize_approx"),
        })

    # ترتيب تنازلي حسب الجودة
    formats.sort(key=lambda x: x["height"], reverse=True)

    # أضف خيار الصوت فقط
    formats.append({
        "format_id": "bestaudio/best",
        "label": "🎵 صوت فقط (MP3)",
        "height": 0,
        "ext": "mp3",
        "filesize": None,
        "audio_only": True,
    })

    return formats[:8]  # أقصى 8 خيارات


# ─────────────────────────────────────────────
#  تحميل الفيديو
# ─────────────────────────────────────────────

def download_video(url: str, format_id: str, output_dir: str) -> str | None:
    audio_only = format_id.startswith("bestaudio")

    if audio_only:
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(output_dir, "%(title).50s.%(ext)s"),
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "quiet": True,
            "no_warnings": True,
        }
    else:
        ydl_opts = {
            "format": f"{format_id}+bestaudio/best[height<={format_id}]/best",
            "outtmpl": os.path.join(output_dir, "%(title).50s.%(ext)s"),
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # أعد أول ملف في المجلد
        files = list(Path(output_dir).iterdir())
        if files:
            return str(files[0])
    except Exception as e:
        logger.error(f"Download error: {e}")

    return None


# ─────────────────────────────────────────────
#  Handlers
# ─────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (
        f"👋 أهلاً {user.first_name}!\n\n"
        "🤖 *بوت تحميل السوشيال ميديا*\n\n"
        "📤 أرسل لي رابط أي فيديو من:\n"
        "• 🔴 YouTube\n"
        "• 📸 Instagram\n"
        "• 🎵 TikTok\n"
        "• 🐦 Twitter / X\n"
        "• 🔵 Facebook\n"
        "• 🟠 Reddit\n"
        "• 💜 Twitch\n"
        "• 🎬 Vimeo\n"
        "• وأكثر...\n\n"
        "وسأقوم بتحميله لك فوراً! ✅"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *طريقة الاستخدام:*\n\n"
        "1️⃣ انسخ رابط الفيديو\n"
        "2️⃣ أرسله هنا مباشرة\n"
        "3️⃣ اختر الجودة المناسبة\n"
        "4️⃣ انتظر التحميل ✅\n\n"
        "⚠️ *ملاحظات:*\n"
        "• الحد الأقصى للملف 50 ميجابايت\n"
        "• بعض المقاطع الخاصة لا يمكن تحميلها\n"
        "• YouTube Shorts مدعومة\n\n"
        "📩 للمشاكل أرسل /start"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def handle_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    urls = extract_urls(text)

    if not urls:
        await update.message.reply_text(
            "❌ لم أجد رابطاً صالحاً.\n"
            "أرسل رابطاً من يوتيوب أو انستقرام أو تيك توك..."
        )
        return

    url = urls[0]
    platform = detect_platform(url)
    emoji = PLATFORM_EMOJI.get(platform, "🌐")

    msg = await update.message.reply_text(
        f"{emoji} جاري جلب معلومات الفيديو...",
        reply_to_message_id=update.message.message_id,
    )

    # جلب المعلومات
    info = await asyncio.get_event_loop().run_in_executor(
        None, get_video_info, url
    )

    if not info:
        await msg.edit_text(
            "❌ تعذّر جلب الفيديو.\n"
            "تأكد أن الرابط صحيح وأن المقطع غير خاص."
        )
        return

    title = info.get("title", "بدون عنوان")[:60]
    duration = format_duration(info.get("duration", 0))
    uploader = info.get("uploader") or info.get("channel") or "—"
    view_count = info.get("view_count")
    views_str = f"{view_count:,}" if view_count else "—"

    formats = get_available_formats(info)

    if not formats:
        await msg.edit_text("❌ لا توجد صيغ متاحة للتحميل.")
        return

    # بناء الأزرار
    keyboard = []
    row = []
    for i, fmt in enumerate(formats):
        size_str = format_size(fmt["filesize"]) if fmt["filesize"] else ""
        label = fmt["label"]
        if size_str:
            label += f" ({size_str})"

        callback_data = f"dl|{url[:180]}|{fmt['format_id']}"
        btn = InlineKeyboardButton(label, callback_data=callback_data[:200])

        row.append(btn)
        if len(row) == 2 or fmt.get("audio_only"):
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])

    caption = (
        f"{emoji} *{title}*\n\n"
        f"⏱ المدة: `{duration}`\n"
        f"👤 القناة: {uploader}\n"
        f"👁 المشاهدات: {views_str}\n\n"
        "📥 *اختر الجودة:*"
    )

    await msg.edit_text(
        caption,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    # حفظ بيانات الفيديو
    ctx.user_data["pending_url"] = url
    ctx.user_data["pending_title"] = title


async def handle_download_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("✅ تم الإلغاء.")
        return

    parts = query.data.split("|", 2)
    if len(parts) != 3:
        await query.edit_message_text("❌ خطأ في البيانات.")
        return

    _, url, format_id = parts

    await query.edit_message_text("⏳ جاري التحميل، يرجى الانتظار...")

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = await asyncio.get_event_loop().run_in_executor(
            None, download_video, url, format_id, tmpdir
        )

        if not filepath or not os.path.exists(filepath):
            await query.edit_message_text(
                "❌ فشل التحميل.\n"
                "قد يكون الفيديو محمياً أو الحجم كبير جداً."
            )
            return

        file_size = os.path.getsize(filepath)

        if file_size > 50 * 1024 * 1024:  # 50 MB
            await query.edit_message_text(
                f"⚠️ حجم الملف كبير جداً ({format_size(file_size)}).\n"
                "الحد الأقصى المدعوم هو 50 ميجابايت.\n"
                "جرّب جودة أقل."
            )
            return

        await query.edit_message_text("📤 جاري الرفع...")

        ext = Path(filepath).suffix.lower()
        chat_id = query.message.chat_id

        try:
            with open(filepath, "rb") as f:
                if ext in (".mp3", ".m4a", ".ogg", ".wav"):
                    await ctx.bot.send_audio(
                        chat_id=chat_id,
                        audio=f,
                        caption=f"🎵 {ctx.user_data.get('pending_title', '')}",
                        read_timeout=120,
                        write_timeout=120,
                    )
                else:
                    await ctx.bot.send_video(
                        chat_id=chat_id,
                        video=f,
                        caption=f"📥 {ctx.user_data.get('pending_title', '')}",
                        supports_streaming=True,
                        read_timeout=120,
                        write_timeout=120,
                    )

            await query.delete_message()

        except Exception as e:
            logger.error(f"Upload error: {e}")
            await query.edit_message_text(
                "❌ فشل إرسال الملف.\n"
                f"خطأ: {str(e)[:100]}"
            )


async def handle_unknown(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤔 لم أفهم طلبك.\n"
        "أرسل رابط فيديو مباشرة أو اكتب /help"
    )


# ─────────────────────────────────────────────
#  تشغيل البوت
# ─────────────────────────────────────────────

def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ خطأ: ضع توكن البوت في متغير BOT_TOKEN")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))

    # Callback buttons
    app.add_handler(CallbackQueryHandler(handle_download_choice, pattern=r"^(dl\|.+|cancel)$"))

    # URLs
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"https?://"), handle_url))

    # Unknown
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unknown))

    print("✅ البوت يعمل الآن...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
