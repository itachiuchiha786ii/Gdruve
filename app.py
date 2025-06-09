import os
import asyncio
import logging
import threading
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
)
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import nest_asyncio

nest_asyncio.apply()

# Logging
logging.basicConfig(level=logging.INFO)

# Flask App
app = Flask(__name__)

@app.route('/')
def home():
    return "\ud83d\ude80 Bot is running!"

# Telegram Bot Token
TELEGRAM_TOKEN = "7817479276:AAHRhQ2lTVFX6QmOqPEMfXoQp2t25dJ6u_0"

# Directory for saving incoming files
DOWNLOAD_DIR = "/data/data/com.termux/files/home/bot_files"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# In-memory session to store folder name per user
user_sessions = {}

# Google Drive: Create or Get Folder
def get_or_create_folder(service, folder_name):
    # Search for folder
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    items = results.get('files', [])

    if items:
        return items[0]['id']
    else:
        # Create folder
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        folder = service.files().create(body=file_metadata, fields='id').execute()
        return folder.get('id')

# Google Drive: Upload File
def upload_to_drive(file_path, file_name, folder_name):
    creds = Credentials.from_authorized_user_file(
        "token.json", ['https://www.googleapis.com/auth/drive.file']
    )
    service = build('drive', 'v3', credentials=creds)

    folder_id = get_or_create_folder(service, folder_name)
    file_metadata = {
        'name': file_name,
        'parents': [folder_id]
    }
    media = MediaFileUpload(file_path, resumable=True)
    uploaded_file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id'
    ).execute()
    return uploaded_file.get('id')

# Command: /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Send me the Google Drive folder name you'd like to use.")

# Handle text messages (expect folder name)
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    folder_name = update.message.text.strip()
    user_sessions[chat_id] = folder_name
    await update.message.reply_text(f"Folder set to: {folder_name}. Now send me a file to upload.")

# Handle file uploads
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    folder_name = user_sessions.get(chat_id)

    if not folder_name:
        await update.message.reply_text(" Please send the folder name first.")
        return

    file = update.message.document or update.message.video or update.message.audio
    if not file:
        await update.message.reply_text(" No valid file received.")
        return

    file_name = file.file_name or "file"
    file_path = os.path.join(DOWNLOAD_DIR, file_name)

    await update.message.reply_text(" Downloading file...")
    telegram_file = await context.bot.get_file(file.file_id)
    await telegram_file.download_to_drive(file_path)

    await update.message.reply_text(" Uploading to Google Drive...")
    try:
        file_id = upload_to_drive(file_path, file_name, folder_name)
        await update.message.reply_text(
            f" Uploaded: https://drive.google.com/file/d/{file_id}/view"
        )
    except Exception as e:
        logging.error(f"Upload error: {e}")
        await update.message.reply_text(f"Upload failed: {e}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

# Telegram Bot Setup
async def main():
    app_ = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app_.add_handler(CommandHandler("start", start))
    app_.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app_.add_handler(MessageHandler(filters.Document.ALL | filters.VIDEO | filters.AUDIO, handle_file))

    logging.info("Bot polling started.")
    await app_.run_polling()

# Run Flask App in Background
def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# Start Everything
if __name__ == "__main__":
    import asyncio
    import nest_asyncio
    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())