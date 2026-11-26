import os, logging, sqlite3, asyncio
from datetime import datetime, timezone
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

load_dotenv()
TOKEN=os.getenv("BOT_TOKEN","").strip()
EDITOR_CHAT=os.getenv("EDITOR_CHAT_ID","").strip()
EDITOR_IDS={int(x.strip()) for x in os.getenv("EDITOR_USER_IDS","").split(",") if x.strip().isdigit()}
DB=os.getenv("DB_PATH","submissions.sqlite3")
if not TOKEN or not EDITOR_CHAT: raise RuntimeError("Fill BOT_TOKEN and EDITOR_CHAT_ID in .env")
EDITOR_CHAT=int(EDITOR_CHAT)
logging.basicConfig(level=logging.INFO)
bot=Bot(TOKEN); dp=Dispatcher(storage=MemoryStorage())
CATS=["Город и благоустройство","ЖКХ","Происшествия","Транспорт","Афиша","История района","Другое"]
cat_kb=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=c)] for c in CATS]+[[KeyboardButton(text="Отмена")]],resize_keyboard=True)
home_kb=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📰 Предложить новость")],[KeyboardButton(text="ℹ️ Помощь")]],resize_keyboard=True)
class Flow(StatesGroup):
    category=State(); material=State(); place=State()
def connect():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
with connect() as c:
    c.execute("""CREATE TABLE IF NOT EXISTS submissions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,username TEXT,name TEXT,category TEXT,details TEXT,place TEXT,kind TEXT,file_id TEXT,caption TEXT,status TEXT DEFAULT 'pending',created TEXT)""")
def mod_kb(i):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Одобрить",callback_data=f"ok:{i}"),InlineKeyboardButton(text="❌ Отклонить",callback_data=f"no:{i}")]])
def get(i):
    with connect() as c: return c.execute("SELECT * FROM submissions WHERE id=?",(i,)).fetchone()
def status(i,s):
    with connect() as c: c.execute("UPDATE submissions SET status=? WHERE id=?",(s,i))
async def notify_editor(i):
    r=get(i)
    msg=(f"📰 <b>Заявка #{i}</b>\nКатегория: <b>{r['category']}</b>\nМесто: <b>{r['place'] or 'не указано'}</b>\nАвтор: {r['name']} (@{r['username'] or 'нет'})\nUser ID: <code>{r['user_id']}</code>\nДата: {r['created']}\n\n<b>Материал:</b>\n{r['details'] or r['caption'] or '—'}\n\nСтатус: ожидает проверки")
    kwargs={"chat_id":EDITOR_CHAT,"caption":msg,"parse_mode":"HTML","reply_markup":mod_kb(i)}
    if r["kind"]=="photo": await bot.send_photo(photo=r["file_id"],**kwargs)
    elif r["kind"]=="video": await bot.send_video(video=r["file_id"],**kwargs)
    elif r["kind"]=="document": await bot.send_document(document=r["file_id"],**kwargs)
    else: await bot.send_message(chat_id=EDITOR_CHAT,text=msg,parse_mode="HTML",reply_markup=mod_kb(i))
@dp.message(CommandStart())
async def start(m,state):
    await state.clear()
    await m.answer("👋 Привет! Это бот районного медиа <b>Новости Преображенки</b>.\n\nПрисылайте текст, фото, видео или историю района. Материалы проверяет редакция перед публикацией.",parse_mode="HTML",reply_markup=home_kb)
@dp.message(Command("help"))
@dp.message(F.text=="ℹ️ Помощь")
async def helpmsg(m):
    await m.answer("Нажмите «Предложить новость», выберите категорию, отправьте материал и укажите место (или «Пропустить»). /news — начать.",reply_markup=home_kb)
@dp.message(Command("news"))
@dp.message(F.text=="📰 Предложить новость")
async def begin(m,state):
    await state.clear(); await state.set_state(Flow.category)
    await m.answer("Выберите раздел:",reply_markup=cat_kb)
@dp.message(Flow.category)
async def category(m,state):
    if m.text=="Отмена": await state.clear(); return await m.answer("Отменено.",reply_markup=home_kb)
    if m.text not in CATS: return await m.answer("Выберите раздел кнопкой.",reply_markup=cat_kb)
    await state.update_data(category=m.text); await state.set_state(Flow.material)
    await m.answer("Отправьте текст, фото, видео или документ. Подпись к медиа тоже принимается.",reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Отмена")]],resize_keyboard=True))
@dp.message(Flow.material)
async def material(m,state):
    if m.text=="Отмена": await state.clear(); return await m.answer("Отменено.",reply_markup=home_kb)
    if m.photo: kind,fileid,caption="photo",m.photo[-1].file_id,m.caption or ""; details=caption
    elif m.video: kind,fileid,caption="video",m.video.file_id,m.caption or ""; details=caption
    elif m.document: kind,fileid,caption="document",m.document.file_id,m.caption or ""; details=caption
    elif m.text: kind,fileid,caption="text",None,""; details=m.text
    else: return await m.answer("Пришлите текст, фотографию, видео или документ.")
    await state.update_data(kind=kind,file_id=fileid,caption=caption,details=details)
    await state.set_state(Flow.place)
    await m.answer("Укажите место или адрес. Если не хотите указывать, напишите «Пропустить».")
@dp.message(Flow.place)
async def place(m,state):
    if m.text=="Отмена": await state.clear(); return await m.answer("Отменено.",reply_markup=home_kb)
    place_text="" if (m.text or "").lower().strip() in ("пропустить","нет","не знаю","-") else (m.text or "")
    d=await state.get_data(); u=m.from_user; stamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    with connect() as c:
        cur=c.execute("INSERT INTO submissions(user_id,username,name,category,details,place,kind,file_id,caption,status,created) VALUES(?,?,?,?,?,?,?,?,?,'pending',?)",(u.id,u.username,u.full_name,d["category"],d["details"],place_text,d["kind"],d["file_id"],d["caption"],stamp)); i=cur.lastrowid
    try: await notify_editor(i)
    except Exception: logging.exception("Editor delivery failed")
    await state.clear()
    await m.answer(f"✅ Материал принят под номером #{i}. Редакция проверит его перед возможной публикацией.",reply_markup=home_kb)
@dp.callback_query(F.data.startswith("ok:"))
async def approve(q):
    i=int(q.data.split(":")[1])
    if q.from_user.id not in EDITOR_IDS: return await q.answer("Нет доступа",show_alert=True)
    r=get(i)
    if not r or r["status"]!="pending": return await q.answer("Уже обработано",show_alert=True)
    status(i,"approved")
    try: await bot.send_message(r["user_id"],f"✅ Ваш материал #{i} одобрен редакцией. Публикация на сайте производится отдельно.")
    except Exception: pass
    await q.message.edit_reply_markup(reply_markup=None); await q.answer("Одобрено")
    await q.message.reply(f"🟢 Заявка #{i} одобрена. (Публикация на сайте пока вручную.)")
@dp.callback_query(F.data.startswith("no:"))
async def reject(q):
    i=int(q.data.split(":")[1])
    if q.from_user.id not in EDITOR_IDS: return await q.answer("Нет доступа",show_alert=True)
    r=get(i)
    if not r or r["status"]!="pending": return await q.answer("Уже обработано",show_alert=True)
    status(i,"rejected")
    try: await bot.send_message(r["user_id"],f"Спасибо за материал #{i}. Редакция пока не планирует его публиковать.")
    except Exception: pass
    await q.message.edit_reply_markup(reply_markup=None); await q.answer("Отклонено")
    await q.message.reply(f"🔴 Заявка #{i} отклонена.")
@dp.message()
async def fallback(m):
    await m.answer("Чтобы отправить новость, нажмите кнопку или /news. Справка: /help",reply_markup=home_kb)
async def main():
    logging.info("Bot polling started")
    await dp.start_polling(bot)
if __name__=="__main__": asyncio.run(main())
