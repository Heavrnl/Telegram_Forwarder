import os
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from models import Session, Source, Keyword, Config, init_db
from math import ceil
import tempfile
from telegram.constants import ParseMode
from FastTelethon import download_file, upload_file
import time
from collections import defaultdict
from telethon.errors import ServerError
import shutil

load_dotenv()

# Telegram API credentials
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
USER_ID = int(os.getenv('USER_ID'))
PHONE_NUMBER = os.getenv('PHONE_NUMBER')

# Initialize Telethon client
client = TelegramClient(
    'sessions/forwarder_session',
    API_ID,
    API_HASH,
    connection_retries=None,  # 无限重试
    retry_delay=1  # 重试间隔1秒
)

# Debug mode
DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'

# 添加新的常量
ITEMS_PER_PAGE = 5  # 每页显示的项目数

# 添加消息组缓存
message_groups = defaultdict(list)
last_message_time = defaultdict(float)
GROUP_TIME_WINDOW = 1.0  # 1秒内的消息视为同一组

class Timer:
    def __init__(self, time_between=2):
        self.start_time = time.time()
        self.time_between = time_between

    def can_send(self):
        if time.time() > (self.start_time + self.time_between):
            self.start_time = time.time()
            return True
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != USER_ID:
        return
    
    await update.message.reply_text(
        "欢迎使用 Telegram 转发机器人！\n\n"
        "📝 使用说明：\n"
        "1. /binding <来源ID或链接> - 绑定来源聊天窗口（消息将转发到当前聊天窗口）\n"
        "2. /unbinding - 解除所有绑定\n"
        "3. /add <关键字> - 添加过滤关键字\n"
        "4. /remove <关键字> - 删除过滤关���字\n"
        "5. /list - 查看当前绑定信息"
    )

async def binding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != USER_ID:
        return
    
    if not context.args:
        await update.message.reply_text("请提供来源聊天窗口 ID 或链接")
        return
    
    session = Session()
    try:
        # 获取目标
        target_chat_id = str(update.effective_chat.id)
        
        # 清除现有绑定
        session.query(Source).delete()
        
        # 用于存储所有绑定的来源信息
        bound_sources = []
        
        # 添加新绑定
        for source in context.args:
            # 处理链接格式
            if 'https://t.me/' in source:
                chat_id = source.split('/')[-1]
                # 尝试获取真实的 chat_id
                try:
                    chat = await client.get_entity(source)
                    chat_id = str(chat.id)
                    bound_sources.append(f"{chat.title} ({chat_id})")
                except Exception as e:
                    print(f"获取聊天ID失败: {str(e)}")
                    bound_sources.append(f"未知 ({chat_id})")
            else:
                chat_id = source
                bound_sources.append(chat_id)
            
            new_source = Source(chat_id=chat_id, chat_type='unknown')
            session.add(new_source)
        
        # 更新或创建配置
        config = session.query(Config).first()
        if config:
            config.target_chat_id = target_chat_id
        else:
            config = Config(target_chat_id=target_chat_id, filter_mode='whitelist')
            session.add(config)
        
        session.commit()
        
        # 创建模式选择按钮
        keyboard = [
            [
                InlineKeyboardButton("白名单模式", callback_data="mode_whitelist"),
                InlineKeyboardButton("黑名单模式", callback_data="mode_blacklist")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # 打印调试信息
        print("\n绑定信息：")
        print(f"📤 已绑定来源: {', '.join(bound_sources)}")
        print(f"📥 目标: {target_chat_id}")
        
        await update.message.reply_text(
            f"✅ 绑定成功！\n"
            f"📤 来源窗口: {', '.join(context.args)}\n"
            f"消息将转发到当前聊天窗口\n\n"
            f"请选择过滤模式：",
            reply_markup=reply_markup
        )
    
    except Exception as e:
        print(f"绑定过程出错: {str(e)}")
        await update.message.reply_text(f"❌ 绑定失败: {str(e)}")
    finally:
        session.close()

async def unbinding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """解除所有绑定"""
    if update.effective_user.id != USER_ID:
        return
    
    session = Session()
    try:
        # 清除所有绑定
        session.query(Source).delete()
        
        # 清除配置
        session.query(Config).delete()
        
        # 清除所有关键字
        session.query(Keyword).delete()
        
        session.commit()
        await update.message.reply_text("✅ 已解除所有绑定并清除所有关键字")
    
    except Exception as e:
        await update.message.reply_text(f"❌ 解绑失败: {str(e)}")
    finally:
        session.close()

async def add_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != USER_ID:
        return
    
    if not context.args:
        await update.message.reply_text("请提供要添加的关键字")
        return
    
    session = Session()
    try:
        config = session.query(Config).first()
        is_whitelist = config.filter_mode == 'whitelist' if config else True
        
        added_words = []
        existed_words = []
        
        for word in context.args:
            # 检查关键字是否已存在
            existing = session.query(Keyword).filter(Keyword.word == word).first()
            if existing:
                existed_words.append(word)
                continue
                
            keyword = Keyword(word=word, is_whitelist=is_whitelist)
            session.add(keyword)
            added_words.append(word)
        
        session.commit()
        
        # 构建响应消息
        response_parts = []
        if added_words:
            response_parts.append(f"✅ 已添加关键字: {', '.join(added_words)}")
        if existed_words:
            response_parts.append(f"⚠️ 已存在的关键字: {', '.join(existed_words)}")
        
        await update.message.reply_text("\n".join(response_parts) or "没有加关键字")
    
    finally:
        session.close()

async def remove_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != USER_ID:
        return
    
    if not context.args:
        await update.message.reply_text("请提供要删除的关键字")
        return
    
    session = Session()
    try:
        for word in context.args:
            session.query(Keyword).filter(Keyword.word == word).delete()
        
        session.commit()
        await update.message.reply_text("关键字删除成功！")
    
    finally:
        session.close()

async def mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    mode = query.data.split('_')[1]
    
    session = Session()
    try:
        config = session.query(Config).first()
        if config:
            config.filter_mode = mode
        else:
            config = Config(target_chat_id='', filter_mode=mode)
            session.add(config)
        
        session.commit()
        await query.edit_message_text(f"已设置为{mode}模式！")
    
    finally:
        session.close()

# 添加重试装饰器
def retry_on_server_error(max_retries=3, delay=1):
    def decorator(func):
        async def wrapper(*args, **kwargs):
            retries = 0
            while retries < max_retries:
                try:
                    return await func(*args, **kwargs)
                except ServerError as e:
                    retries += 1
                    if retries == max_retries:
                        raise e
                    print(f"服务器连接错误，{delay}秒后重试 ({retries}/{max_retries})")
                    time.sleep(delay)
            return None
        return wrapper
    return decorator

@retry_on_server_error(max_retries=3)
async def get_media_group_messages(client, entity, min_id, max_id, limit):
    return await client.get_messages(
        entity=entity,
        min_id=min_id,
        max_id=max_id,
        limit=limit
    )

async def handle_new_message(event):
    session = Session()
    try:
        config = session.query(Config).first()
        if not config:
            return
        
        # 获取消息来源和检查
        sources = session.query(Source).all()
        source_ids = [source.chat_id for source in sources]
        chat = await event.get_chat()
        chat_id = str(chat.id)
        
        if chat_id not in source_ids:
            return
        
        # 获取消息文本
        message_text = event.message.text if event.message.text else ''
        
        # 打消息信息
        print(f"\n📨 收到消息 - 来自: {chat.title or chat_id} ({chat_id})")
        print(f"📝 消息内容: {message_text[:50]}{'...' if len(message_text) > 50 else ''}")
        print(f"⚙️ 当前模式: {'白名单' if config.filter_mode == 'whitelist' else '黑名单'}")
        
        # 检查关键词匹配
        keywords = session.query(Keyword).all()
        keyword_words = [keyword.word for keyword in keywords]
        matched_keywords = [word for word in keyword_words if word in message_text]
        should_forward = True
        
        if config.filter_mode == 'whitelist':
            should_forward = bool(matched_keywords)
            if matched_keywords:
                print(f"✅ 匹配白名单关键词: {', '.join(matched_keywords)}")
            else:
                print("❌ 未匹配白名单关键词，不转发")
        else:  # blacklist
            should_forward = not bool(matched_keywords)
            if matched_keywords:
                print(f"❌ 匹配黑名单关键词: {', '.join(matched_keywords)}，不转发")
            else:
                print("✅ 未匹配黑名单关键词，允许转发")
        
        if should_forward:
            try:
                content = message_text
                disable_preview = True
                
                # 处理媒体文件
                if event.message.media:
                    # 获取消息链接
                    if hasattr(chat, 'username'):
                        message_link = f"https://t.me/{chat.username}/{event.message.id}"
                    else:
                        message_link = f"https://t.me/c/{str(chat.id)[4:]}/{event.message.id}"

                    # 检查是否是媒体组消息
                    if event.message.grouped_id:
                        # 对于媒体组消息，只处理第一条消息
                        if not message_text:  # 如果是媒体组的后续消息，跳过
                            return
                        # 在第一条消息中添加链接预览
                        content = f"[\u200b]({message_link})\n\n{content}"
                        disable_preview = False
                    # 检查是否只有一张图片
                    elif hasattr(event.message.media, 'photo'):
                        # 创建临时文件目录
                        temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'temp')
                        os.makedirs(temp_dir, exist_ok=True)
                        
                        # 创建唯一的临时文件名
                        temp_file = os.path.join(temp_dir, f'temp_{int(time.time())}_{event.message.id}.jpg')
                        
                        try:
                            # 下载图片
                            await event.message.download_media(file=temp_file)
                            
                            # 发送图片和文本
                            await application.bot.send_photo(
                                chat_id=config.target_chat_id,
                                photo=open(temp_file, 'rb'),
                                caption=content,
                                parse_mode=ParseMode.MARKDOWN
                            )
                        finally:
                            # 删除临时文件
                            if os.path.exists(temp_file):
                                os.remove(temp_file)
                        return
                    else:
                        # 其他类型的媒体，添加不可见字符的链接
                        content = f"[\u200b]({message_link})\n\n{content}"
                        disable_preview = False
                
                # 只有当内容不为空时才发送消息
                if content.strip():
                    await application.bot.send_message(
                        chat_id=config.target_chat_id,
                        text=content,
                        parse_mode=ParseMode.MARKDOWN,
                        disable_web_page_preview=disable_preview
                    )
            except Exception as e:
                print(f"发送消息时出错: {str(e)}")
    
    except Exception as e:
        print(f"处理消息时出错: {str(e)}")
    finally:
        session.close()

async def start_client():
    print("正在启动 Telethon 客户端...")
    try:
        # 连接到 Telegram
        await client.connect()
        
        # 如果还没有权，则开���交互式登录
        if not await client.is_user_authorized():
            print("\n需要进行 Telegram 账号验证")
            phone = os.getenv('PHONE_NUMBER')
            if not phone:
                phone = input("请输入您的 Telegram 手机号 (格式如: +86123456789): ")
            else:
                print(f"使用环境变量中的手机号: {phone}")
            
            # 发送验证码
            await client.send_code_request(phone)
            
            # 输入验证码
            code = input("\n请输入收到的验证码: ")
            
            try:
                await client.sign_in(phone, code)
            except SessionPasswordNeededError:
                # 如果启用了两步验证，需要输入密码
                password = input("\n请输入您的两步验证密码: ")
                await client.sign_in(password=password)
        
        print("\nTelethon 客户端登成功！")
        
    except Exception as e:
        print(f"\n登录过程出现错误: {str(e)}")
        raise e

async def send_startup_message():
    """发送动成功提示消息"""
    try:
        await application.bot.send_message(
            chat_id=USER_ID,
            text="✅ 发机器人已成功启动\n\n"
                 "📝 使用说明��\n"
                 "1. /binding - 绑定来源窗口\n"
                 "2. /add - 添加过滤关键字\n"
                 "3. /remove - 删除过滤键字\n\n"
                 "🤖 机器人正在监听消息..."
        )
    except Exception as e:
        print(f"发送启动消息失败: {str(e)}")

async def setup_and_run():
    """设置并运行所有组件"""
    try:
        # Start Telethon client with authentication
        await start_client()
        
        # Add message handler
        client.add_event_handler(handle_new_message, events.NewMessage())
        
        # 启动 bot
        await application.initialize()
        await application.start()
        
        # 设置 bot 命令
        commands = [
            ("start", "显示帮助信息"),
            ("binding", "绑定来源聊天窗口"),
            ("unbinding", "解除所有绑定"),
            ("add", "添加过滤关键字"),
            ("remove", "删除过滤关键字"),
            ("list", "查看当前配置信息")
        ]
        
        await application.bot.set_my_commands(commands)
        
        # 发送启动成功消息
        await send_startup_message()
        
        # 创建并运行所有务
        polling_task = asyncio.create_task(
            application.updater.start_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True
            )
        )
        client_task = asyncio.create_task(client.run_until_disconnected())

        # 待所有任务完成或直到被中
        try:
            await asyncio.gather(polling_task, client_task)
        except asyncio.CancelledError:
            # 处理取消
            print("\n正在关闭服务...")
        finally:
            # 取消所有未完成的任务
            polling_task.cancel()
            client_task.cancel()
            try:
                await polling_task
            except asyncio.CancelledError:
                pass
            try:
                await client_task
            except asyncio.CancelledError:
                pass
        
    except Exception as e:
        print(f"运行时出错: {str(e)}")
        raise e
    finally:
        # 确保正确关闭
        await application.stop()
        await client.disconnect()

async def list_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示当前配置信息和关键字列表"""
    if update.effective_user.id != USER_ID:
        return
    
    session = Session()
    try:
        # 获取配置信息
        config = session.query(Config).first()
        if not config:
            await update.message.reply_text("未找到任何绑定信息")
            return
        
        # 取来源信息
        sources = session.query(Source).all()
        source_info = []
        for source in sources:
            try:
                chat = await client.get_entity(int(source.chat_id))
                source_info.append(f"- {chat.title} ({source.chat_id})")
            except:
                source_info.append(f"- {source.chat_id}")
        
        # 获取目标窗口信息
        try:
            target_chat = await client.get_entity(int(config.target_chat_id))
            target_info = f"{target_chat.title} ({config.target_chat_id})"
        except:
            target_info = config.target_chat_id
        
        # 获取关键词列表
        keywords = session.query(Keyword).all()
        total_pages = ceil(len(keywords) / 50)  # 每页50个关键词
        
        # 构建第一页信息
        info_text = [
            "📋 当前配置息：",
            f"⚙️ 过滤模式: {'白名单' if config.filter_mode == 'whitelist' else '黑名单'}",
            f"📥 目标窗口: {target_info}",
            "\n📤 来源窗口:",
            *source_info,
            "\n📝 关键词列表："
        ]
        
        # 添加第一页的关键词
        current_keywords = keywords[:50]
        if keywords:
            info_text.extend([f"{i+1}. {kw.word}" for i, kw in enumerate(current_keywords)])
            if total_pages > 1:
                info_text.append(f"\n页码: 1/{total_pages}")
        else:
            info_text.append("暂无关键字")
        
        # 建分页按钮
        keyboard = []
        if total_pages > 1:
            keyboard.append([InlineKeyboardButton("️ 下一页", callback_data="list_keywords_1")])
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        await update.message.reply_text(
            "\n".join(info_text),
            reply_markup=reply_markup
        )
    
    finally:
        session.close()

async def handle_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理关键词列表分页"""
    query = update.callback_query
    await query.answer()
    
    session = Session()
    try:
        if query.data.startswith("list_keywords_"):
            page = int(query.data.split("_")[-1])
            keywords = session.query(Keyword).all()
            total_pages = ceil(len(keywords) / 50)
            
            if not keywords:
                await query.edit_message_text("暂无关键词")
                return
            
            start_idx = page * 50
            end_idx = start_idx + 50
            current_keywords = keywords[start_idx:end_idx]
            
            # 只在第一页显示配置信息
            if page == 0:
                # 取配置信
                config = session.query(Config).first()
                sources = session.query(Source).all()
                source_info = []
                for source in sources:
                    try:
                        chat = await client.get_entity(int(source.chat_id))
                        source_info.append(f"- {chat.title} ({source.chat_id})")
                    except:
                        source_info.append(f"- {source.chat_id}")
                
                # 获取目标窗口信息
                try:
                    target_chat = await client.get_entity(int(config.target_chat_id))
                    target_info = f"{target_chat.title} ({config.target_chat_id})"
                except:
                    target_info = config.target_chat_id
                
                text_lines = [
                    "📋 当前置信息：",
                    f"⚙️ 过滤模式: {'白名单' if config.filter_mode == 'whitelist' else '黑名单'}",
                    f"📥 目标窗口: {target_info}",
                    "\n📤 来源窗口:",
                    *source_info,
                    "\n📝 关键词列表："
                ]
            else:
                text_lines = ["📝 关键词列表："]
            
            # 添加关键词
            text_lines.extend([f"{i+1+start_idx}. {kw.word}" for i, kw in enumerate(current_keywords)])
            text_lines.append(f"\n页码: {page + 1}/{total_pages}")
            
            # 建分页钮
            keyboard = []
            if page > 0:
                keyboard.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"list_keywords_{page-1}"))
            if page < total_pages - 1:
                keyboard.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"list_keywords_{page+1}"))
            
            reply_markup = InlineKeyboardMarkup([keyboard]) if keyboard else None
            
            await query.edit_message_text(
                "\n".join(text_lines),
                reply_markup=reply_markup
            )
    
    finally:
        session.close()

def main():
    # Initialize database
    init_db()
    
    # Initialize bot
    global application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("binding", binding))
    application.add_handler(CommandHandler("unbinding", unbinding))  # 添加解绑命令
    application.add_handler(CommandHandler("add", add_keywords))
    application.add_handler(CommandHandler("remove", remove_keywords))
    application.add_handler(CallbackQueryHandler(mode_callback))
    application.add_handler(CommandHandler("list", list_info))
    application.add_handler(CallbackQueryHandler(handle_list_callback))
    
    # 运行应用
    try:
        asyncio.run(setup_and_run())
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    except Exception as e:
        print(f"\n程序运行出错: {str(e)}")
    finally:
        print("\n正在关闭程序...")

if __name__ == '__main__':
    import asyncio
    main() 