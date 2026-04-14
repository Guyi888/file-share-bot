import os
import logging
import random
import string
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)

# ── 配置 ──────────────────────────────────────────────────────────────────────
BOT_TOKEN  = "YOUR_BOT_TOKEN_HERE"
ADMIN_IDS  = [123456789]          # 替换成你的 Telegram 用户 ID
DB_FILE    = "filebot.db"
PLATFORM_FEE = 0.1               # 平台抽成 10%

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ── 对话状态 ──────────────────────────────────────────────────────────────────
PERM_SELECT, PRICE_INPUT, CODE_INPUT, EXTRACT_INPUT, SEARCH_INPUT = range(5)


# ════════════════════════════════════════════════════════════════════════════
# 数据库
# ════════════════════════════════════════════════════════════════════════════

def db_connect():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def db_init():
    conn = db_connect()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id    INTEGER PRIMARY KEY,
            username   TEXT,
            first_name TEXT,
            balance    REAL    DEFAULT 0,
            income     REAL    DEFAULT 0,
            join_date  TEXT
        );
        CREATE TABLE IF NOT EXISTS files (
            share_id       TEXT PRIMARY KEY,
            owner_id       INTEGER,
            file_name      TEXT,
            file_type      TEXT,
            tg_file_id     TEXT,
            permission     TEXT DEFAULT 'free',
            price          REAL DEFAULT 0,
            code           TEXT,
            download_count INTEGER DEFAULT 0,
            upload_date    TEXT,
            description    TEXT
        );
        CREATE TABLE IF NOT EXISTS favorites (
            user_id  INTEGER,
            share_id TEXT,
            add_date TEXT,
            PRIMARY KEY (user_id, share_id)
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount  REAL,
            type    TEXT,
            date    TEXT,
            note    TEXT
        );
    """)
    conn.commit()
    conn.close()


def ensure_user(user):
    conn = db_connect()
    conn.execute("""
        INSERT OR IGNORE INTO users (user_id, username, first_name, join_date)
        VALUES (?, ?, ?, ?)
    """, (user.id, user.username or "", user.first_name or "", datetime.now().strftime("%Y-%m-%d")))
    conn.commit()
    conn.close()


def get_user(user_id):
    conn = db_connect()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row


def get_file(share_id):
    conn = db_connect()
    row = conn.execute("SELECT * FROM files WHERE share_id=?", (share_id,)).fetchone()
    conn.close()
    return row


def gen_share_id():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=8))


def count_user_files(user_id):
    conn = db_connect()
    n = conn.execute("SELECT COUNT(*) FROM files WHERE owner_id=?", (user_id,)).fetchone()[0]
    conn.close()
    return n


# ════════════════════════════════════════════════════════════════════════════
# 主菜单
# ════════════════════════════════════════════════════════════════════════════

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 找文件", callback_data="find"),
         InlineKeyboardButton("🔎 搜索文件", callback_data="search")],
        [InlineKeyboardButton("💰 充值",   callback_data="recharge"),
         InlineKeyboardButton("📥 提取",   callback_data="extract")],
        [InlineKeyboardButton("❤️ 收藏箱", callback_data="favorites"),
         InlineKeyboardButton("⚙️ 设置",   callback_data="settings")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)
    user = get_user(update.effective_user.id)
    file_count = count_user_files(update.effective_user.id)

    text = (
        f"👋 岁岁，欢迎使用文件储存助手！\n\n"
        f"邀请码：`{update.effective_user.id}`\n"
        f"用户名：@{user['username'] or '未设置'}\n"
        f"粉丝余额：{user['balance']:.2f} U\n"
        f"收入：{user['income']:.2f} U\n"
        f"已分享：{file_count} 个文件\n\n"
        f"您可以直接发送文件，我会为您生成提取码。\n"
        f"支持设置文件权限：付费｜免费｜提取码\n"
        f"最大支持 4GB 文件。"
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=main_menu_keyboard(),
                                        parse_mode="Markdown")
    else:
        await update.callback_query.edit_message_text(text, reply_markup=main_menu_keyboard(),
                                                      parse_mode="Markdown")


# ════════════════════════════════════════════════════════════════════════════
# 文件上传流程
# ════════════════════════════════════════════════════════════════════════════

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)
    msg = update.message

    # 识别文件类型
    if msg.document:
        file_id   = msg.document.file_id
        file_name = msg.document.file_name or "文件"
        file_type = "document"
    elif msg.photo:
        file_id   = msg.photo[-1].file_id
        file_name = "图片.jpg"
        file_type = "photo"
    elif msg.video:
        file_id   = msg.video.file_id
        file_name = msg.video.file_name or "视频.mp4"
        file_type = "video"
    elif msg.audio:
        file_id   = msg.audio.file_id
        file_name = msg.audio.file_name or "音频"
        file_type = "audio"
    elif msg.voice:
        file_id   = msg.voice.file_id
        file_name = "语音消息"
        file_type = "voice"
    else:
        return ConversationHandler.END

    # 暂存到 context
    context.user_data["pending_file"] = {
        "file_id": file_id, "file_name": file_name, "file_type": file_type
    }

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🆓 免费分享",  callback_data="perm_free")],
        [InlineKeyboardButton("💰 付费下载",  callback_data="perm_paid")],
        [InlineKeyboardButton("🔐 设置提取码", callback_data="perm_code")],
    ])
    await msg.reply_text(
        f"📁 已收到文件：`{file_name}`\n\n请设置文件权限：",
        reply_markup=keyboard, parse_mode="Markdown"
    )
    return PERM_SELECT


async def perm_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "perm_free":
        context.user_data["pending_file"]["permission"] = "free"
        await _save_file(query, context)
        return ConversationHandler.END

    elif data == "perm_paid":
        context.user_data["pending_file"]["permission"] = "paid"
        await query.edit_message_text("💰 请输入下载价格（单位：U，例如：2.5）：")
        return PRICE_INPUT

    elif data == "perm_code":
        context.user_data["pending_file"]["permission"] = "code"
        await query.edit_message_text("🔐 请设置提取码（4~8位数字或字母）：")
        return CODE_INPUT


async def price_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text.strip())
        if price <= 0:
            raise ValueError
        context.user_data["pending_file"]["price"] = price
        await _save_file_msg(update.message, context)
    except ValueError:
        await update.message.reply_text("❌ 请输入有效的正数金额，例如：2.5")
        return PRICE_INPUT
    return ConversationHandler.END


async def code_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    if not (4 <= len(code) <= 8 and code.isalnum()):
        await update.message.reply_text("❌ 提取码须为 4~8 位数字或字母，请重新输入：")
        return CODE_INPUT
    context.user_data["pending_file"]["code"] = code
    await _save_file_msg(update.message, context)
    return ConversationHandler.END


async def _save_file(query, context):
    """从 callback_query 保存文件"""
    f = context.user_data.pop("pending_file")
    share_id = gen_share_id()
    conn = db_connect()
    conn.execute("""
        INSERT INTO files (share_id, owner_id, file_name, file_type, tg_file_id,
                           permission, price, code, upload_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (share_id, query.from_user.id, f["file_name"], f["file_type"], f["file_id"],
          f.get("permission", "free"), f.get("price", 0), f.get("code"),
          datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()

    perm_map = {"free": "🆓 免费", "paid": f"💰 付费 {f.get('price',0):.2f}U", "code": "🔐 提取码"}
    code_line = f"\n提取码：`{f['code']}`" if f.get("code") else ""
    await query.edit_message_text(
        f"✅ 文件已保存！\n\n"
        f"📁 文件名：{f['file_name']}\n"
        f"🔑 权限：{perm_map[f.get('permission','free')]}\n"
        f"🔗 分享口令：`/get {share_id}`{code_line}\n\n"
        f"发送口令给好友即可分享！",
        parse_mode="Markdown"
    )


async def _save_file_msg(message, context):
    """从 message 保存文件"""
    f = context.user_data.pop("pending_file")
    share_id = gen_share_id()
    conn = db_connect()
    conn.execute("""
        INSERT INTO files (share_id, owner_id, file_name, file_type, tg_file_id,
                           permission, price, code, upload_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (share_id, message.from_user.id, f["file_name"], f["file_type"], f["file_id"],
          f.get("permission", "free"), f.get("price", 0), f.get("code"),
          datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()

    perm_map = {"free": "🆓 免费", "paid": f"💰 付费 {f.get('price',0):.2f}U", "code": "🔐 提取码"}
    code_line = f"\n提取码：`{f['code']}`" if f.get("code") else ""
    await message.reply_text(
        f"✅ 文件已保存！\n\n"
        f"📁 文件名：{f['file_name']}\n"
        f"🔑 权限：{perm_map[f.get('permission','free')]}\n"
        f"🔗 分享口令：`/get {share_id}`{code_line}\n\n"
        f"发送口令给好友即可分享！",
        parse_mode="Markdown"
    )


# ════════════════════════════════════════════════════════════════════════════
# 获取文件 /get <share_id>
# ════════════════════════════════════════════════════════════════════════════

async def get_file_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)
    if not context.args:
        await update.message.reply_text("用法：`/get <分享码>`", parse_mode="Markdown")
        return

    share_id = context.args[0].strip()
    file = get_file(share_id)
    if not file:
        await update.message.reply_text("❌ 未找到该文件，请检查分享码。")
        return

    uid = update.effective_user.id

    # 免费
    if file["permission"] == "free":
        await _send_file(update, context, file)

    # 提取码
    elif file["permission"] == "code":
        context.user_data["extract_share_id"] = share_id
        await update.message.reply_text("🔐 该文件需要提取码，请输入：")
        return  # 等待下一条消息（由 extract_input handler 处理）

    # 付费
    elif file["permission"] == "paid":
        if uid == file["owner_id"]:
            await _send_file(update, context, file)
            return
        user = get_user(uid)
        price = file["price"]
        if user["balance"] < price:
            await update.message.reply_text(
                f"💰 该文件需要 {price:.2f}U 才能下载\n"
                f"您当前余额：{user['balance']:.2f}U\n\n"
                f"请先充值后再下载。",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💰 去充值", callback_data="recharge")
                ]])
            )
            return
        # 扣费
        earn = price * (1 - PLATFORM_FEE)
        conn = db_connect()
        conn.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (price, uid))
        conn.execute("UPDATE users SET income=income+? WHERE user_id=?", (earn, file["owner_id"]))
        conn.execute("INSERT INTO transactions (user_id,amount,type,date,note) VALUES (?,?,?,?,?)",
                     (uid, -price, "download", datetime.now().strftime("%Y-%m-%d %H:%M"), share_id))
        conn.commit()
        conn.close()
        await _send_file(update, context, file)


async def _send_file(update, context, file):
    """发送文件给用户"""
    uid = update.effective_user.id
    conn = db_connect()
    conn.execute("UPDATE files SET download_count=download_count+1 WHERE share_id=?",
                 (file["share_id"],))
    conn.commit()
    conn.close()

    caption = (f"📁 {file['file_name']}\n"
               f"📅 上传：{file['upload_date']}\n"
               f"⬇️ 下载：{file['download_count']+1} 次")

    fav_btn = InlineKeyboardMarkup([[
        InlineKeyboardButton("❤️ 收藏", callback_data=f"fav_{file['share_id']}")
    ]])

    try:
        if file["file_type"] == "document":
            await update.message.reply_document(file["tg_file_id"], caption=caption, reply_markup=fav_btn)
        elif file["file_type"] == "photo":
            await update.message.reply_photo(file["tg_file_id"], caption=caption, reply_markup=fav_btn)
        elif file["file_type"] == "video":
            await update.message.reply_video(file["tg_file_id"], caption=caption, reply_markup=fav_btn)
        elif file["file_type"] in ("audio",):
            await update.message.reply_audio(file["tg_file_id"], caption=caption, reply_markup=fav_btn)
        elif file["file_type"] == "voice":
            await update.message.reply_voice(file["tg_file_id"], caption=caption)
        else:
            await update.message.reply_document(file["tg_file_id"], caption=caption, reply_markup=fav_btn)
    except Exception as e:
        await update.message.reply_text(f"❌ 发送文件失败：{e}")


# ════════════════════════════════════════════════════════════════════════════
# 提取码输入（非对话流程，用于 /get 后续）
# ════════════════════════════════════════════════════════════════════════════

async def extract_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理点击"提取"按钮"""
    query = update.callback_query
    await query.answer()
    context.user_data["extract_mode"] = True
    await query.edit_message_text("📥 请输入分享码或提取码：")
    return EXTRACT_INPUT


async def extract_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    ensure_user(update.effective_user)

    # 如果是等待提取码验证
    if "extract_share_id" in context.user_data:
        share_id = context.user_data.pop("extract_share_id")
        file = get_file(share_id)
        if file and file["code"] == text:
            await _send_file(update, context, file)
        else:
            await update.message.reply_text("❌ 提取码错误，请重新输入：")
            context.user_data["extract_share_id"] = share_id
            return EXTRACT_INPUT
        return ConversationHandler.END

    # 当做分享码处理
    file = get_file(text)
    if not file:
        await update.message.reply_text("❌ 未找到该文件，请检查分享码。")
        return ConversationHandler.END

    if file["permission"] == "free":
        await _send_file(update, context, file)
    elif file["permission"] == "code":
        context.user_data["extract_share_id"] = text
        await update.message.reply_text("🔐 请输入该文件的提取码：")
        return EXTRACT_INPUT
    elif file["permission"] == "paid":
        user = get_user(update.effective_user.id)
        await update.message.reply_text(
            f"💰 该文件需要 {file['price']:.2f}U\n余额：{user['balance']:.2f}U\n"
            f"使用 `/get {text}` 确认购买。", parse_mode="Markdown"
        )
    return ConversationHandler.END


# ════════════════════════════════════════════════════════════════════════════
# 搜索文件
# ════════════════════════════════════════════════════════════════════════════

async def search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🔎 请输入要搜索的文件名关键词：")
    return SEARCH_INPUT


async def search_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyword = update.message.text.strip()
    conn = db_connect()
    rows = conn.execute(
        "SELECT * FROM files WHERE file_name LIKE ? AND permission='free' LIMIT 10",
        (f"%{keyword}%",)
    ).fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("😔 没有找到相关文件。", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    text = f"🔎 搜索「{keyword}」，共找到 {len(rows)} 个文件：\n\n"
    for r in rows:
        text += f"📁 {r['file_name']}\n`/get {r['share_id']}`\n⬇️ {r['download_count']} 次下载\n\n"

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())
    return ConversationHandler.END


# ════════════════════════════════════════════════════════════════════════════
# 收藏
# ════════════════════════════════════════════════════════════════════════════

async def fav_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    share_id = query.data.replace("fav_", "")
    uid = query.from_user.id
    conn = db_connect()
    try:
        conn.execute("INSERT OR IGNORE INTO favorites (user_id,share_id,add_date) VALUES (?,?,?)",
                     (uid, share_id, datetime.now().strftime("%Y-%m-%d")))
        conn.commit()
        await query.answer("❤️ 已收藏！", show_alert=False)
    except Exception:
        pass
    conn.close()


async def favorites_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    conn = db_connect()
    rows = conn.execute("""
        SELECT f.* FROM files f
        JOIN favorites fav ON f.share_id=fav.share_id
        WHERE fav.user_id=?
    """, (uid,)).fetchall()
    conn.close()

    if not rows:
        await query.edit_message_text("❤️ 收藏箱为空。\n\n下载文件后点击「收藏」即可保存。",
                                      reply_markup=InlineKeyboardMarkup([[
                                          InlineKeyboardButton("🔙 返回", callback_data="back")
                                      ]]))
        return

    text = f"❤️ 我的收藏（{len(rows)} 个）：\n\n"
    for r in rows:
        perm = {"free": "🆓", "paid": "💰", "code": "🔐"}.get(r["permission"], "")
        text += f"{perm} {r['file_name']}\n`/get {r['share_id']}`\n\n"

    await query.edit_message_text(text, parse_mode="Markdown",
                                  reply_markup=InlineKeyboardMarkup([[
                                      InlineKeyboardButton("🔙 返回", callback_data="back")
                                  ]]))


# ════════════════════════════════════════════════════════════════════════════
# 充值 & 我的文件
# ════════════════════════════════════════════════════════════════════════════

async def recharge_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "💰 充值说明\n\n"
        "请联系管理员进行充值。\n"
        "充值完成后余额会自动到账。\n\n"
        f"您的 ID：`{query.from_user.id}`\n"
        "请将此 ID 发给管理员。",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 返回", callback_data="back")
        ]])
    )


async def find_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    conn = db_connect()
    rows = conn.execute(
        "SELECT * FROM files WHERE owner_id=? ORDER BY upload_date DESC LIMIT 20", (uid,)
    ).fetchall()
    conn.close()

    if not rows:
        await query.edit_message_text(
            "📂 您还没有上传任何文件。\n\n直接发送文件即可上传！",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回", callback_data="back")
            ]])
        )
        return

    text = f"📂 我的文件（{len(rows)} 个）：\n\n"
    for r in rows:
        perm = {"free": "🆓", "paid": f"💰{r['price']}U", "code": "🔐"}.get(r["permission"], "")
        text += f"{perm} {r['file_name']}\n`/get {r['share_id']}`  ⬇️{r['download_count']}次\n\n"

    await query.edit_message_text(text, parse_mode="Markdown",
                                  reply_markup=InlineKeyboardMarkup([[
                                      InlineKeyboardButton("🔙 返回", callback_data="back")
                                  ]]))


async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)
    await query.edit_message_text(
        f"⚙️ 账户设置\n\n"
        f"用户 ID：`{query.from_user.id}`\n"
        f"用户名：@{user['username'] or '未设置'}\n"
        f"余额：{user['balance']:.2f} U\n"
        f"累计收入：{user['income']:.2f} U\n"
        f"注册日期：{user['join_date']}\n",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 返回", callback_data="back")
        ]])
    )


# ════════════════════════════════════════════════════════════════════════════
# 管理员命令
# ════════════════════════════════════════════════════════════════════════════

async def admin_recharge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    # /recharge <user_id> <amount>
    try:
        target_id = int(context.args[0])
        amount    = float(context.args[1])
        conn = db_connect()
        conn.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, target_id))
        conn.execute("INSERT INTO transactions (user_id,amount,type,date,note) VALUES (?,?,?,?,?)",
                     (target_id, amount, "recharge", datetime.now().strftime("%Y-%m-%d %H:%M"), "管理员充值"))
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE user_id=?", (target_id,)).fetchone()
        conn.close()
        await update.message.reply_text(
            f"✅ 充值成功！\n用户 {target_id} 余额：{user['balance']:.2f} U"
        )
        try:
            await context.bot.send_message(
                target_id, f"💰 您已收到 {amount:.2f}U 充值，当前余额：{user['balance']:.2f}U")
        except Exception:
            pass
    except (IndexError, ValueError):
        await update.message.reply_text("用法：/recharge <user_id> <金额>")


async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


# ════════════════════════════════════════════════════════════════════════════
# 主程序
# ════════════════════════════════════════════════════════════════════════════

def main():
    db_init()
    app = Application.builder().token(BOT_TOKEN).build()

    # 文件上传对话
    upload_conv = ConversationHandler(
        entry_points=[MessageHandler(
            filters.Document.ALL | filters.PHOTO | filters.VIDEO |
            filters.AUDIO | filters.VOICE, handle_file
        )],
        states={
            PERM_SELECT: [CallbackQueryHandler(perm_selected, pattern="^perm_")],
            PRICE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, price_input)],
            CODE_INPUT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, code_input)],
        },
        fallbacks=[CommandHandler("start", start)],
        per_message=False,
    )

    # 搜索对话
    search_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(search_callback, pattern="^search$")],
        states={
            SEARCH_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_input)],
        },
        fallbacks=[CommandHandler("start", start)],
        per_message=False,
    )

    # 提取对话
    extract_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(extract_callback, pattern="^extract$")],
        states={
            EXTRACT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, extract_input)],
        },
        fallbacks=[CommandHandler("start", start)],
        per_message=False,
    )

    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("get",      get_file_cmd))
    app.add_handler(CommandHandler("recharge", admin_recharge))
    app.add_handler(upload_conv)
    app.add_handler(search_conv)
    app.add_handler(extract_conv)
    app.add_handler(CallbackQueryHandler(find_callback,      pattern="^find$"))
    app.add_handler(CallbackQueryHandler(recharge_callback,  pattern="^recharge$"))
    app.add_handler(CallbackQueryHandler(favorites_callback, pattern="^favorites$"))
    app.add_handler(CallbackQueryHandler(settings_callback,  pattern="^settings$"))
    app.add_handler(CallbackQueryHandler(fav_callback,       pattern="^fav_"))
    app.add_handler(CallbackQueryHandler(back_callback,      pattern="^back$"))

    logger.info("文件Bot已启动...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
