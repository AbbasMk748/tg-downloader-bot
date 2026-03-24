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

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")

SUPPORTED_PLATFORMS = {
    "youtube":   r"(youtube\.com|youtu\.be)",
    "instagram": r"(instagram\.com|instagr\.am)",
    "tiktok":    r"(tiktok\.com|vm\.tiktok\.com|vt\.tiktok\.com)",
    "twitter":   r"(twitter\.com|x\.com|t\.co)",
    "facebook":  r"(facebook\.com|fb\.watch|fb\.com)",
    "reddit":    r"(reddit\.com|redd\.it)",
    "twitch":    r"(twitch\.tv|clips\.twitch\.tv)",
    "vimeo":     r"(vimeo\.com)",
}

PLATFORM_EMOJI = {
    "youtube": "🔴", "instagram": "📸", "tiktok": "🎵",
    "twitter": "🐦", "facebook": "🔵", "reddit": "🟠",
    "twitch": "💜", "vimeo": "🎬", "unknown": "🌐",
}

def detect_platform(url):
    for name, pattern in SUPPORTED_PLATFORMS.items():
        if re.search(pattern, url, re.IGNORECASE):
            return name
    return "unknown"

def extract_urls(text):
    return re.findall(r"https?://[^\s]+", text)

def format_size(b):
    if not b:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.1f}{unit}"
        b /= 1024
    return f"{b:.1f}GB"

def format_duration(s):
    if not s:
        return "—"
    m, s = divmod(int(s), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

def get_video_info(url):
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as e:
        logger.error(f"Info error: {e}")
        return None

def get_formats(info):
    formats = []
    seen = set()
    for f in info.get("formats", []):
        h = f.get("height")
        if not h or f.get("vcodec") == "none":
            continue
        label = f"{h}p"
        if label in seen:
            continue
        seen.add(label)
        formats.append({
            "format_id": f["format_id"],
            "label": label,
            "height": h,
            "filesize": f.get("filesize") or f.get("filesize_approx"),
        })
    formats.sort(key=lambda x: x["height"], reverse=True)
    formats.append({"format_id": "bestaudio/best", "label": "🎵 صوت MP3", "height": 0, "filesize": None, "audio": True})
    return formats[:8]

def download_video(url, format_id, outdir):
    audio = format_id.startswith("bestaudio")
    opts = {
        "quiet": True,
        "outtmpl": os.path.join(outdir, "%(title).50s.%(ext)s"),
    }
    if audio:
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    else:
        opts["format"] = f"{format_id}+bestaudio/best[height<={format_id}]/best"
        opts["merge_output_format"] = "mp4"
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        files = list(Path(outdir).iterdir())
        return str(files[0]) if files else None
    except Exception as e:
        logger.error(f"Download error: {e}")
        return None

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"👋 أهلاً {update.effective_user.first_name}!\n\n"
        "🤖 *بوت تحميل السوشيال ميديا*\n\n"
        "📤 أرسل رابط أي فيديو من:\n"
        "🔴 YouTube  📸 Instagram  🎵 TikTok\n"
        "🐦 Twitter  🔵 Facebook  🟠 Reddit\n\n"
        "وسأحمله لك فوراً ✅",
        parse_mode="Markdown"
    )

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *طريقة الاستخدام:*\n\n"
        "1️⃣ انسخ رابط الفيديو\n"
        "2️⃣ أرسله هنا\n"
        "3️⃣ اختر الجودة\n"
        "4️⃣ انتظر التحميل ✅\n\n"
        "⚠️ الحد الأقصى 50MB",
        parse_mode="Markdown"
    )

async def handle_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    urls = extract_urls(update.message.text or "")
    if not urls:
        await update.message.reply_text("❌ أرسل رابط صالح من يوتيوب أو تيك توك...")
        return

    url = urls[0]
    platform = detect_platform(url)
    emoji = PLATFORM_EMOJI.get(platform, "🌐")

    msg = await update.message.reply_text(f"{emoji} جاري جلب معلومات الفيديو...")

    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(None, get_video_info, url)

    if not info:
        await msg.edit_text("❌ تعذّر جلب الفيديو. تأكد أن الرابط صحيح وغير خاص.")
        return

    title = info.get("title", "بدون عنوان")[:60]
    duration = format_duration(info.get("duration", 0))
    uploader = info.get("uploader") or info.get("channel") or "—"
    formats = get_formats(info)

    keyboard = []
    row = []
    for fmt in formats:
        size = f" ({format_size(fmt['filesize'])})" if fmt.get("filesize") else ""
        btn = InlineKeyboardButton(
            fmt["label"] + size,
            callback_data=f"dl|{url[:180]}|{fmt['format_id']}"
        )
        row.append(btn)
        if len(row) == 2 or fmt.get("audio"):
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])

    ctx.user_data["title"] = title

    await msg.edit_text(
        f"{emoji} *{title}*\n\n⏱ المدة: `{duration}`\n👤 {uploader}\n\n📥 *اختر الجودة:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("✅ تم الإلغاء.")
        return

    parts = query.data.split("|", 2)
    if len(parts) != 3:
        await query.edit_message_text("❌ خطأ.")
        return

    _, url, format_id = parts
    await query.edit_message_text("⏳ جاري التحميل...")

    with tempfile.TemporaryDirectory() as tmpdir:
        loop = asyncio.get_event_loop()
        filepath = await loop.run_in_executor(None, download_video, url, format_id, tmpdir)

        if not filepath or not os.path.exists(filepath):
            await query.edit_message_text("❌ فشل التحميل. جرّب جودة أخرى.")
            return

        size = os.path.getsize(filepath)
        if size > 50 * 1024 * 1024:
            await query.edit_message_text(f"⚠️ الملف كبير جداً ({format_size(size)}). جرّب جودة أقل.")
            return

        await query.edit_message_text("📤 جاري الرفع...")
        ext = Path(filepath).suffix.lower()
        title = ctx.user_data.get("title", "")

        try:
            with open(filepath, "rb") as f:
                if ext in (".mp3", ".m4a", ".ogg"):
                    await ctx.bot.send_audio(chat_id=query.message.chat_id, audio=f, caption=f"🎵 {title}", read_timeout=120, write_timeout=120)
                else:
                    await ctx.bot.send_video(chat_id=query.message.chat_id, video=f, caption=f"📥 {title}", supports_streaming=True, read_timeout=120, write_timeout=120)
            await query.delete_message()
        except Exception as e:
            await query.edit_message_text(f"❌ فشل الإرسال: {str(e)[:100]}")

async def handle_unknown(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أرسل رابط فيديو أو اكتب /help")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"https?://"), handle_url))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unknown))
    print("✅ البوت يعمل...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
