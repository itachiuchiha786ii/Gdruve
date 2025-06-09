import os
import asyncio
import logging
import base64
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import nest_asyncio

# Apply nested asyncio for compatibility with Flask + Telegram bot
nest_asyncio.apply()

# Logging
logging.basicConfig(level=logging.INFO)

# Flask App (for Render health check)
app = Flask(__name__)
@app.route('/')
def home():
    return "🚀 Bot is running!"

# Environment Variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GOOGLE_TOKEN_B64 = os.getenv("GOOGLE_TOKEN_B64")
GOOGLE_CREDS_B64 = os.getenv("GOOGLE_CREDS_B64")

# Temp directory to store files (Render uses /tmp)
DOWNLOAD_DIR = "/tmp"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# In-memory session to store folder name per user
user_sessions = {}

# Decode credentials from environment
def get_credentials():
    try:
        token_json = base64.b64decode(GOOGLE_TOKEN_B64).decode('utf-8')
        creds_json = base64.b64decode(GOOGLE_CREDS_B64).decode('utf-8')

        creds = Credentials.from_authorized_user_info(
            info=eval(token_json),
            scopes=['https://www.googleapis.com/auth/drive.file']
        )
        return creds
    except Exception as e:
        logging.error(f"Credential decoding failed: {e}")
        return None

# Create or get a folder in Google Drive
def get_or_create_folder(service, folder_name):
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    items = results.get('files', [])
    if items:
        return items[0]['id']
    else:
        file_metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}
        folder = service.files().create(body=file_metadata, fields='id').execute()
        return folder.get('id')

# Upload file to Google Drive
def upload_to_drive(file_path, file_name, folder_name):
    creds = get_credentials()
    if not creds:
        raise Exception("Invalid Google credentials.")

    service = build('drive', 'v3', credentials=creds)
    folder_id = get_or_create_folder(service, folder_name)

    file_metadata = {'name': file_name, 'parents': [folder_id]}
    media = MediaFileUpload(file_path, resumable=True)
    uploaded_file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id'
    ).execute()
    return uploaded_file.get('id')

# /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Send me the Google Drive folder name you'd like to use.")

# Handle folder name input
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    folder_name = update.message.text.strip()
    user_sessions[chat_id] = folder_name
    await update.message.reply_text(f"✅ Folder set to: {folder_name}. Now send a file to upload.")

# Handle file upload
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    folder_name = user_sessions.get(chat_id)

    if not folder_name:
        await update.message.reply_text("⚠️ Please send the folder name first.")
        return

    file = update.message.document or update.message.video or update.message.audio
    if not file:
        await update.message.reply_text("❌ No valid file received.")
        return

    file_name = file.file_name or "file"
    file_path = os.path.join(DOWNLOAD_DIR, file_name)

    await update.message.reply_text("📥 Downloading file...")
    telegram_file = await context.bot.get_file(file.file_id)
    await telegram_file.download_to_drive(file_path)

    await update.message.reply_text("📤 Uploading to Google Drive...")
    try:
        file_id = upload_to_drive(file_path, file_name, folder_name)
        await update.message.reply_text(f"✅ Uploaded:\nhttps://drive.google.com/file/d/{file_id}/view")
    except Exception as e:
        logging.error(f"Upload error: {e}")
        await update.message.reply_text(f"❌ Upload failed: {e}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

# Initialize Telegram Bot
async def main():
    app_ = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_.add_handler(CommandHandler("start", start))
    app_.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app_.add_handler(MessageHandler(filters.Document.ALL | filters.VIDEO | filters.AUDIO, handle_file))

    logging.info("Bot polling started.")
    await app_.run_polling()

# Flask background runner
def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# Start bot and Flask together
if __name__ == "__main__":
    threading = __import__("threading")
    threading.Thread(target=run_flask).start()
    asyncio.run(main())