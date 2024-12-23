import os
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Message
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from models import Session, Source, Keyword, init_db, MessageFormat, RegexFormat, PreviewSetting
from math import ceil
import tempfile
from telegram.constants import ParseMode
from FastTelethon import download_file, upload_file
import time
from collections import defaultdict, OrderedDict
from telethon.errors import ServerError
import shutil
from telethon.tl.types import ChannelParticipantsAdmins

load_dotenv()

# Telegram API credentials
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
USER_ID = int(os.getenv('USER_ID'))
PHONE_NUMBER = os.getenv('PHONE_NUMBER')

# Initialize Telethon client
# 确保 sessions 目录存在
os.makedirs('sessions', exist_ok=True)

client = TelegramClient(
    'sessions/forwarder_session',
    API_ID,
    API_HASH,
    connection_retries=None,  # 无限重试
    retry_delay=1  # 1���
)

# Debug mode
DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'

# 添加新的常量
ITEMS_PER_PAGE = 5  # 每页显示的项目数

# 添加消息组缓存
message_groups = defaultdict(list)
last_message_time = defaultdict(float)
GROUP_TIME_WINDOW = 1.0  # 1秒内的消息视为同一组

# 添加一个消息ID缓存
class LRUCache:
    def __init__(self, capacity=100):
        self.cache = OrderedDict()
        self.capacity = capacity

    def get(self, key):
        if key not in self.cache:
            return False
        self.cache.move_to_end(key)
        return True

    def put(self, key):
        if key in self.cache:
            self.cache.move_to_end(key)
        else:
            if len(self.cache) >= self.capacity:
                self.cache.popitem(last=False)
            self.cache[key] = True

# 创建消息缓存实例
message_cache = LRUCache()

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
        "2. /unbinding - 解除当前窗口的所有绑定\n"
        "3. /add <关键字> - 添加当前窗口的过滤关键字\n"
        "4. /remove <关键字> - 删除当前窗口的过滤关键字\n"
        "5. /list - 查看当前窗口的配置信息\n"
        "6. /export - 导出当前窗口的关键字列表\n"
        "7. /switch <来源ID或链接> <格式> - 设置指定来源的消息格式(html/markdown)\n"
        "8. /regex <来源ID或链接> <正则表达式> [格式] - 设置正则表达式消息格式\n"
        "9. /regex_list <来源ID或链接> - 查看正则表达式规则\n"
        "10. /regex_remove <来源ID或链接> - 移除正则表达式规则\n"
        "11. /preview <来源ID或链接> <on/off> - 设置链接预览开关\n\n"
        "🤖 机器人已准备就绪！"
    )

async def binding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != USER_ID:
        return
    
    if not context.args:
        await update.message.reply_text("请提供源聊天窗口 ID 或链接")
        return
    
    session = Session()
    try:
        # 获取当前聊天窗口ID（作为目标）
        target_chat_id = str(update.effective_chat.id)
        bound_sources = []
        
        # 添加新绑定
        for source in context.args:
            # 处理链接格式
            if 'https://t.me/' in source:
                try:
                    chat = await client.get_entity(source)
                    chat_id = str(chat.id)
                    chat_type = 'channel' if chat.broadcast else 'group' if chat.megagroup else 'private'
                    source_title = chat.title
                    bound_sources.append(f"{source_title} ({chat_id})")
                except Exception as e:
                    print(f"获取聊天ID失败: {str(e)}")
                    bound_sources.append(f"未知 ({source})")
                    continue
            else:
                chat_id = source
                try:
                    chat = await client.get_entity(int(chat_id))
                    chat_type = 'channel' if chat.broadcast else 'group' if chat.megagroup else 'private'
                    source_title = chat.title
                    bound_sources.append(f"{source_title} ({chat_id})")
                except:
                    chat_type = 'unknown'
                    bound_sources.append(chat_id)
            
            # 检查是否已经存在该绑定
            existing = session.query(Source).filter(
                Source.chat_id == chat_id,
                Source.target_chat_id == target_chat_id
            ).first()
            
            if not existing:
                new_source = Source(
                    chat_id=chat_id,
                    target_chat_id=target_chat_id,
                    chat_type=chat_type,
                    filter_mode='whitelist'  # 默认使用白名单模式
                )
                session.add(new_source)
                
                # 创建模式选择按钮
                keyboard = [
                    [
                        InlineKeyboardButton("白名单模式", callback_data=f"mode_whitelist_{chat_id}"),
                        InlineKeyboardButton("黑名单模式", callback_data=f"mode_blacklist_{chat_id}")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    f"✅ 绑定成功\n"
                    f"📤 来源: {bound_sources[-1]}\n"
                    f"📥 目标: 当前聊天窗口\n\n"
                    f"请选择此绑定选择过滤模：",
                    reply_markup=reply_markup
                )
            else:
                await update.message.reply_text(f"⚠️ 已存在的绑定: {bound_sources[-1]}")
        
        session.commit()
        
        if not bound_sources:
            await update.message.reply_text("❌ 没有添加任何有效的来源")
            return
        
        # 打印试信息
        print("\n绑定信息：")
        print(f"📤 已绑定来源: {', '.join(bound_sources)}")
        print(f"📥 目标: {target_chat_id}")
        
    except Exception as e:
        print(f"绑定过程出错: {str(e)}")
        await update.message.reply_text(f"❌ 绑定失败: {str(e)}")
    finally:
        session.close()

async def unbinding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """解除当前窗口的所有绑定"""
    if update.effective_user.id != USER_ID:
        return
    
    session = Session()
    try:
        current_chat_id = str(update.effective_chat.id)
        
        # 删除当前口作为目标的所有绑定
        target_bindings = session.query(Source).filter(
            Source.target_chat_id == current_chat_id
        ).delete()
        
        # 删除当前窗作为来源的所有绑定
        source_bindings = session.query(Source).filter(
            Source.chat_id == current_chat_id
        ).delete()
        
        # 如果是目标窗口，同时删除其关键字
        session.query(Keyword).filter(
            Keyword.target_chat_id == current_chat_id
        ).delete()
        
        session.commit()
        
        if target_bindings or source_bindings:
            await update.message.reply_text("✅ 已解除当前窗口的所有绑定关系")
        else:
            await update.message.reply_text("❌ 当前窗口没有任何绑定关系")
    
    except Exception as e:
        await update.message.reply_text(f"❌ 解绑失败: {str(e)}")
    finally:
        session.close()

async def add_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """添加当前窗口的关键字"""
    if update.effective_user.id != USER_ID:
        return
    
    if not context.args:
        await update.message.reply_text("请提供要添加的关键字")
        return
    
    # 检查消息是否已经处理过
    message_id = f"{update.effective_chat.id}_{update.message.message_id}"
    if message_cache.get(message_id):
        return
    message_cache.put(message_id)
    
    session = Session()
    try:
        current_chat_id = str(update.effective_chat.id)
        
        # 检查当前窗口否是目标窗口
        source = session.query(Source).filter(
            Source.target_chat_id == current_chat_id
        ).first()
        
        if not source:
            await update.message.reply_text("❌ 只能在目标窗口中管理关键字")
            return
        
        added_words = []
        existed_words = []
        
        for word in context.args:
            # 将关键字转换为小写
            word = word.lower()
            
            # 检查关键字是否已存在
            existing = session.query(Keyword).filter(
                Keyword.target_chat_id == current_chat_id,
                Keyword.word == word
            ).first()
            
            if existing:
                existed_words.append(word)
                continue
            
            # 添加小写的关键字
            keyword = Keyword(
                target_chat_id=current_chat_id,
                word=word,
                is_whitelist=(source.filter_mode == 'whitelist')
            )
            session.add(keyword)
            added_words.append(word)
        
        session.commit()
        
        # 构建响应消息
        response_parts = []
        if added_words:
            response_parts.append(f"✅ 已添加关键字: {', '.join(added_words)}")
        if existed_words:
            response_parts.append(f"⚠️ 已存在的关键字: {', '.join(existed_words)}")
        
        await update.message.reply_text("\n".join(response_parts) or "没有添加任何关键字")
    
    finally:
        session.close()

async def remove_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """删除当前窗口的关键字"""
    if update.effective_user.id != USER_ID:
        return
    
    if not context.args:
        await update.message.reply_text("请提供要删除的关键字")
        return
    
    session = Session()
    try:
        current_chat_id = str(update.effective_chat.id)
        
        # 检查当前窗口是否是目标窗口
        is_target = session.query(Source).filter(
            Source.target_chat_id == current_chat_id
        ).first() is not None
        
        if not is_target:
            await update.message.reply_text("❌ 只能在目标窗口中管理关键字")
            return
        
        removed_words = []
        not_found_words = []
        
        for word in context.args:
            # 将要删除的关键字转换为小写
            word = word.lower()
            
            # 只删除当前窗口的关键字
            result = session.query(Keyword).filter(
                Keyword.target_chat_id == current_chat_id,
                Keyword.word == word
            ).delete()
            
            if result:
                removed_words.append(word)
            else:
                not_found_words.append(word)
        
        session.commit()
        
        # 构建响应消息
        response_parts = []
        if removed_words:
            response_parts.append(f"✅ 已删除关键字: {', '.join(removed_words)}")
        if not_found_words:
            response_parts.append(f"❓ 未找到关键字: {', '.join(not_found_words)}")
        
        await update.message.reply_text("\n".join(response_parts) or "没有删除任何关键字")
    
    finally:
        session.close()

async def mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    mode, source_chat_id = query.data.split('_')[1:]
    
    session = Session()
    try:
        source = session.query(Source).filter(
            Source.chat_id == source_chat_id,
            Source.target_chat_id == str(update.effective_chat.id)
        ).first()
        
        if source:
            source.filter_mode = mode
            session.commit()
            await query.edit_message_text(f"已将 {source.chat_id} 的转发模式设置为 {mode} 模式！")
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
    global regex_format, preview_setting
    
    # 检查消息是否已经处理过
    message_id = f"{event.chat_id}_{event.message.id}"
    if message_cache.get(message_id):
        return
    message_cache.put(message_id)
    
    # 检查是否是命令消息
    if event.message.text and event.message.text.startswith('/'):
        # 获取发送者权限
        chat = await event.get_chat()
        sender = None
        
        try:
            # 于频道消息，检查发送者是否是管理员
            if event.is_channel:
                admins = await client.get_participants(chat, filter=ChannelParticipantsAdmins)
                admin_ids = [admin.id for admin in admins]
                if USER_ID in admin_ids:
                    sender = await client.get_entity(USER_ID)
                    print(f"\n收到新息事件: {event}")
                    print(f"消息类型: {type(event.message)}")
                    print(f"来源: {event.chat if event.chat else '未知'}")
        except Exception as e:
            print(f"获取发送者信息失败: {str(e)}")
            return
        
        # 如果是管理员发送的命令，直接处理命令
        if sender and sender.id == USER_ID:
            message_text = event.message.text
            command = message_text.split()[0][1:]  # 移除 '/'
            args = message_text.split()[1:] if len(message_text.split()) > 1 else []
            
            # 创建一个带有必要属性的模拟 update 对象
            class DummyMessage:
                def __init__(self, chat_id, text):
                    self.chat_id = chat_id
                    self.text = text
                    self.chat = type('Chat', (), {'id': chat_id})()
                    self.from_user = type('User', (), {'id': USER_ID})()
                    self.message_id = int(time.time() * 1000)  # 使用时间戳作为消息ID
                
                async def reply_text(self, text, **kwargs):
                    return await application.bot.send_message(
                        chat_id=self.chat_id,
                        text=text,
                        **kwargs
                    )
                
                async def reply_document(self, document, filename=None, caption=None):
                    return await application.bot.send_document(
                        chat_id=self.chat_id,
                        document=document,
                        filename=filename,
                        caption=caption
                    )
            
            class DummyContext:
                def __init__(self, args):
                    self.args = args
            
            class DummyUpdate:
                def __init__(self, message):
                    self.message = message
                    self.effective_user = type('User', (), {'id': USER_ID})()
                    self.effective_chat = type('Chat', (), {'id': message.chat_id})()
            
            # 创建模拟对象
            dummy_message = DummyMessage(event.chat_id, message_text)
            update = DummyUpdate(dummy_message)
            context = DummyContext(args)
            
            # 获取所有命令处理函数的映射
            command_handlers = {
                'start': start,
                'binding': binding,
                'unbinding': unbinding,
                'add': add_keywords,
                'remove': remove_keywords,
                'list': list_info,
                'switch': switch_format,
                'regex': regex_format,
                'regex_list': regex_list,
                'regex_remove': regex_remove,
                'preview': preview_setting,
                'export': export_keywords,
            }
            
            # 根据命令调用相应的处理函数
            try:
                if command in command_handlers:
                    await command_handlers[command](update, context)
                else:
                    print(f"未知命令: {command}")
            except Exception as e:
                print(f"处理命令时出错: {str(e)}")
                await application.bot.send_message(
                    chat_id=event.chat_id,
                    text=f"❌ 执行命令时出错: {str(e)}"
                )
            return

    # 处理普通消息的转发逻辑...
    session = Session()
    try:
        # 获取聊天信息
        chat = await event.get_chat()
        
        # 取消息来源和查询
        sources = session.query(Source).filter(
            Source.chat_id == str(chat.id)
        ).all()
        
        if not sources:
            return
        
        # 获取消息文本
        message_text = event.message.text if event.message.text else ''
        
        # 对每个目标都进行转发
        for source in sources:
            # 打印消息信息
            print(f"\n收到消息 - 来自: {chat.title or chat.id} ({chat.id})")
            print(f"📝 消息内容: {message_text[:50]}{'...' if len(message_text) > 50 else ''}")
            print(f"⚙️ 当前模式: {'白名单' if source.filter_mode == 'whitelist' else '黑名单'}")
            
            # 检查关键词匹配
            keywords = session.query(Keyword).filter(
                Keyword.target_chat_id == source.target_chat_id
            ).all()
            
            # 将消息内容转换为小写进行匹配
            message_text_lower = message_text.lower()
            
            # 检查是否匹配任何关键词
            matched = False
            for keyword in keywords:
                if keyword.word in message_text_lower:  # 使用小写内容进行匹配
                    matched = True
                    break
            
            # 据过滤模式决定是否转发
            should_forward = (
                (source.filter_mode == 'whitelist' and matched) or
                (source.filter_mode == 'blacklist' and not matched)
            )
            
            if should_forward:
                try:
                    content = message_text
                    # 获取预览置
                    preview_setting = session.query(PreviewSetting).filter(
                        PreviewSetting.chat_id == str(chat.id)
                    ).first()
                    # 默认关闭预览，除非明确设置开启
                    disable_preview = not (preview_setting and preview_setting.enable_preview)
                    
                    # 获取消息格式设置
                    format_setting = session.query(MessageFormat).filter(
                        MessageFormat.chat_id == str(chat.id)
                    ).first()
                    
                    # 获取正则格式设置
                    regex_formats = session.query(RegexFormat).filter(
                        RegexFormat.chat_id == str(chat.id)
                    ).all()
                    
                    # 检查正则匹配并处理内容
                    parse_mode = 'markdown'  # 默认格式
                    if regex_formats:
                        import re
                        for regex_format in regex_formats:
                            try:
                                pattern = regex_format.pattern
                                # 不再对模式进行转义
                                # 使用正则表达式替换内容，保留链接部分
                                if '[' in content and '](' in content:
                                    # 处理带链接的文本
                                    parts = content.split('](')
                                    text_part = parts[0][1:]  # 移除开头的 [
                                    link_part = parts[1]  # 包含链接和可能的其他文本
                                    
                                    # 只处理文本部分
                                    text_part = re.sub(pattern, '', text_part)
                                    content = f'[{text_part}]({link_part}'
                                else:
                                    # 处理普通文本
                                    content = re.sub(pattern, '', content)
                                    
                                parse_mode = regex_format.parse_mode
                                # 打印调试信息
                                print(f"��配到正则表达式: {pattern}")
                                print(f"处理后的内容: {content}")
                                print(f"使用格式: {parse_mode}")
                            except re.error as e:
                                print(f"正则表达式错误: {str(e)}")
                                continue
                    else:
                        # 如果没有则规则，使用默认格式设置
                        parse_mode = format_setting.parse_mode if format_setting else 'markdown'
                    
                    # 只有当内容不为空时才发送消息
                    if content.strip():
                        await application.bot.send_message(
                            chat_id=source.target_chat_id,
                            text=content,
                            parse_mode=ParseMode.HTML if parse_mode == 'html' else ParseMode.MARKDOWN,
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
        
        # 如果还没有权限，则开交互式登录
        if not await client.is_user_authorized():
            print("\n需进行 Telegram 账号验证")
            phone = os.getenv('PHONE_NUMBER')
            if not phone:
                phone = input("请输入您的 Telegram 手机号 (格式如: +86123456789): ")
            else:
                print(f"使用环境变量中的手机号: {phone}")
            
            # 发送验证码
            await client.send_code_request(phone)
            
            # 输入验证码
            code = input("\n输入收到的验证码: ")
            
            try:
                await client.sign_in(phone, code)
            except SessionPasswordNeededError:
                # 如果启用了两步验证，需要输入密码
                password = input("\n请输入您的两步验证密码: ")
                await client.sign_in(password=password)
        
        print("\nTelethon 客户端登录成！")
        
    except Exception as e:
        print(f"\n登录过程出现错误: {str(e)}")
        raise e

async def send_startup_message():
    """发送启动成功消息"""
    try:
        await application.bot.send_message(
            chat_id=USER_ID,
            text="欢迎使用 Telegram 转发机器人！\n\n"
        "📝 使用说明：\n"
        "1. /binding <来源ID或链接> - 绑定来源聊天窗口（消息将转发到当前聊天窗口）\n"
        "2. /unbinding - 解除当前窗口的所有绑定\n"
        "3. /add <关键字> - 添加当前窗口的过滤关键字\n"
        "4. /remove <关键字> - 删除当前窗口的过滤关键字\n"
        "5. /list - 查看当前窗口的配置信息\n"
        "6. /export - 导出当前窗口的关键字列表\n"
        "7. /switch <来源ID或链接> <格式> - 设置指定来源的消息格式(html/markdown)\n"
        "8. /regex <来源ID或链接> <正则表达式> [格式] - 设置正则表达式消息格式\n"
        "9. /regex_list <来源ID或链接> - 查看正则表达式规则\n"
        "10. /regex_remove <来源ID或链接> - 移除正则表达式规则\n"
        "11. /preview <来源ID或链接> <on/off> - 设置链接预览开关\n\n"
        "🤖 机器人已准备就绪！"
        )
    except Exception as e:
        print(f"发送启动消息失败: {str(e)}")

async def setup_and_run():
    """设置并运行所有组件"""
    try:
        # Start Telethon client with authentication
        await start_client()
        
        # 改消息处理器，同时处理频道息
        client.add_event_handler(handle_new_message, events.NewMessage())
        client.add_event_handler(handle_new_message, events.MessageEdited())  # 可选：处理编辑的消息
        
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
            ("list", "查看当前配置信息"),
            ("export", "导出当前窗口的关键字列表"),
            ("switch", "设置指定来源的消息格式"),
            ("regex", "设置正则表达式消息格式")  # 添加 regex 命令说明
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

        # 等待所有任务完成或直到被中断
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
    """显示当前聊天窗口的配置信息和键字列表"""
    if update.effective_user.id != USER_ID:
        return
    
    session = Session()
    try:
        # 获取当前聊天窗口ID
        current_chat_id = str(update.effective_chat.id)
        
        # 检查当前窗口绑定信息
        sources_as_target = session.query(Source).filter(
            Source.target_chat_id == current_chat_id
        ).all()
        
        sources_as_source = session.query(Source).filter(
            Source.chat_id == current_chat_id
        ).all()
        
        if sources_as_target:
            # 如果是目标窗口，显示所有来源
            source_info = []
            for source in sources_as_target:
                try:
                    chat = await client.get_entity(int(source.chat_id))
                    source_info.append(
                        f"- {chat.title} ({source.chat_id}) "
                        f"[{'白名单' if source.filter_mode == 'whitelist' else '黑名单'}]"
                    )
                except:
                    source_info.append(
                        f"- {source.chat_id} "
                        f"[{'白名单' if source.filter_mode == 'whitelist' else '黑名单'}]"
                    )
            
            info_text = [
                "📋 当前配置信息：",
                "\n📤 来源窗口:",
                *source_info,
                "\n📝 关键词列表："
            ]
            
            # 获取关键词列表
            keywords = session.query(Keyword).filter(
                Keyword.target_chat_id == current_chat_id
            ).all()
            
        elif sources_as_source:
            # 如果是来源窗口，显示所有目标
            target_info = []
            for source in sources_as_source:
                try:
                    chat = await client.get_entity(int(source.target_chat_id))
                    target_info.append(
                        f"- {chat.title} ({source.target_chat_id}) "
                        f"[{'白名单' if source.filter_mode == 'whitelist' else '黑名单'}]"
                    )
                except:
                    target_info.append(
                        f"- {source.target_chat_id} "
                        f"[{'白名单' if source.filter_mode == 'whitelist' else '黑名单'}]"
                    )
            
            info_text = [
                "当前配置信息：",
                "\n📥 转发至:",
                *target_info
            ]
            
            # 不显示关词列表，因为关键词是按目标窗口存储的
            keywords = []
        else:
            await update.message.reply_text("当前窗口未配置任何转发规则")
            return
        
        # 显示关键词列表
        if keywords:
            total_pages = ceil(len(keywords) / 50)
            current_keywords = keywords[:50]
            info_text.extend([f"{i+1}. {kw.word}" for i, kw in enumerate(current_keywords)])
            if total_pages > 1:
                info_text.append(f"\n页码: 1/{total_pages}")
                keyboard = [[InlineKeyboardButton("️下一页", callback_data="list_keywords_1")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
            else:
                reply_markup = None
        else:
            info_text.append("暂无关键字")
            reply_markup = None
        
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
                await query.edit_message_text("无关键词")
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
                    "📋 当前置息：",
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

async def export_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """导出当前窗口的所有关键字"""
    if update.effective_user.id != USER_ID:
        return
    
    session = Session()
    try:
        current_chat_id = str(update.effective_chat.id)
        
        # 检查当前窗口是否是目标窗口
        is_target = session.query(Source).filter(
            Source.target_chat_id == current_chat_id
        ).first() is not None
        
        if not is_target:
            await update.message.reply_text("❌ 只能导出目标窗的关键字")
            return
        
        # 获取当前窗口的所有关键字
        keywords = session.query(Keyword).filter(
            Keyword.target_chat_id == current_chat_id
        ).all()
        
        if not keywords:
            await update.message.reply_text("❌ 当前窗口没有任何关键字")
            return
        
        # 将关键字用空格连接
        keywords_text = " ".join(kw.word for kw in keywords)
        
        await update.message.reply_text(
            f"📤 当前口的关键字列表：\n\n"
            f"{keywords_text}"
        )
    
    finally:
        session.close()

async def switch_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """切换来源的消息解析格式"""
    if update.effective_user.id != USER_ID:
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("请提供来源聊天窗口和格式 (html/markdown)\n例如: /switch https://t.me/channel_name html")
        return
    
    source = context.args[0]
    parse_mode = context.args[1].lower()
    
    if parse_mode not in ['html', 'markdown']:
        await update.message.reply_text("❌ 格式必须是 html 或 markdown")
        return
    
    session = Session()
    try:
        # 处理链接格式
        if 'https://t.me/' in source:
            try:
                chat = await client.get_entity(source)
                chat_id = str(chat.id)
                source_title = chat.title
            except Exception as e:
                await update.message.reply_text(f"❌ 获取聊天信息失败: {str(e)}")
                return
        else:
            chat_id = source
            try:
                chat = await client.get_entity(int(chat_id))
                source_title = chat.title
            except:
                source_title = chat_id
        
        # 更新或创建式设置
        format_setting = session.query(MessageFormat).filter(
            MessageFormat.chat_id == chat_id
        ).first()
        
        if format_setting:
            format_setting.parse_mode = parse_mode
            action = "更新"
        else:
            format_setting = MessageFormat(
                chat_id=chat_id,
                parse_mode=parse_mode
            )
            session.add(format_setting)
            action = "设置"
        
        session.commit()
        
        await update.message.reply_text(
            f"✅ 已{action}消息格式\n"
            f"📤 来源: {source_title} ({chat_id})\n"
            f"📝 格式: {parse_mode}"
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ 设置失败: {str(e)}")
    finally:
        session.close()

async def regex_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """设置指定来源的正则表达式消息格式"""
    if update.effective_user.id != USER_ID:
        return
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "请提供来源聊天窗口和正则表达式\n"
            "例如: /regex https://t.me/channel_name \\*\\* [html/markdown]\n"
            "格式数可选，默认使用 markdown"
        )
        return
    
    source = context.args[0]
    # 获取中间的所有参数作为正则表达式，并处理转义字符
    if len(context.args) > 2 and context.args[-1].lower() in ['html', 'markdown']:
        pattern = ' '.join(context.args[1:-1])
        parse_mode = context.args[-1].lower()
    else:
        pattern = ' '.join(context.args[1:])
        parse_mode = 'markdown'
    
    # 处理正则表达式中的特殊字符
    pattern = pattern.replace('\\*', '\\*')  # 确保星号被正确转义
    
    if parse_mode not in ['html', 'markdown']:
        await update.message.reply_text("❌ 格式必须是 html 或 markdown")
        return
    
    session = Session()
    try:
        # 处理链接格式
        if 'https://t.me/' in source:
            try:
                chat = await client.get_entity(source)
                chat_id = str(chat.id)
                source_title = chat.title
            except Exception as e:
                await update.message.reply_text(f"❌ 获取聊天信息失败: {str(e)}")
                return
        else:
            chat_id = source
            try:
                chat = await client.get_entity(int(chat_id))
                source_title = chat.title
            except:
                source_title = chat_id
        
        # 验证正表达式是否有效
        try:
            import re
            re.compile(pattern)
        except re.error:
            await update.message.reply_text("❌ 无效的正则表达式")
            return
        
        # 更新或创建正则格式设置
        regex_format = session.query(RegexFormat).filter(
            RegexFormat.chat_id == chat_id
        ).first()
        
        if regex_format:
            regex_format.pattern = pattern
            regex_format.parse_mode = parse_mode
            action = "更新"
        else:
            regex_format = RegexFormat(
                chat_id=chat_id,
                pattern=pattern,
                parse_mode=parse_mode
            )
            session.add(regex_format)
            action = "添加"
        
        session.commit()
        
        await update.message.reply_text(
            f"✅ 已{action}正则格式规则\n"
            f"📤 来源: {source_title} ({chat_id})\n"
            f"📝 正则: {pattern}\n"
            f"📝 格式: {parse_mode}"
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ 设置失败: {str(e)}")
    finally:
        session.close()

async def regex_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """列出指定来源的正则表达式规则"""
    if update.effective_user.id != USER_ID:
        return
    
    if not context.args:
        await update.message.reply_text("请提供来源聊天窗口\n例如: /regex_list https://t.me/channel_name")
        return
    
    source = context.args[0]
    session = Session()
    try:
        # 处理链接格式
        if 'https://t.me/' in source:
            try:
                chat = await client.get_entity(source)
                chat_id = str(chat.id)
                source_title = chat.title
            except Exception as e:
                await update.message.reply_text(f"❌ 获取聊天信息失败: {str(e)}")
                return
        else:
            chat_id = source
            try:
                chat = await client.get_entity(int(chat_id))
                source_title = chat.title
            except:
                source_title = chat_id
        
        # 查询正则格式设置
        regex_format = session.query(RegexFormat).filter(
            RegexFormat.chat_id == chat_id
        ).first()
        
        if regex_format:
            await update.message.reply_text(
                f"📋 正则格式则\n"
                f"📤 来源: {source_title} ({chat_id})\n"
                f"📝 正则: {regex_format.pattern}\n"
                f"📝 格式: {regex_format.parse_mode}"
            )
        else:
            await update.message.reply_text(f"❌ 未找到 {source_title} 的则格式规则")
        
    except Exception as e:
        await update.message.reply_text(f"❌ 查询失败: {str(e)}")
    finally:
        session.close()

async def regex_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """移除指定来源的正则表达式规则"""
    if update.effective_user.id != USER_ID:
        return
    
    if not context.args:
        await update.message.reply_text("请提供来源聊天窗口\n例如: /regex_remove https://t.me/channel_name")
        return
    
    source = context.args[0]
    session = Session()
    try:
        # 处理链接格式
        if 'https://t.me/' in source:
            try:
                chat = await client.get_entity(source)
                chat_id = str(chat.id)
                source_title = chat.title
            except Exception as e:
                await update.message.reply_text(f"❌ 获取聊天信息失败: {str(e)}")
                return
        else:
            chat_id = source
            try:
                chat = await client.get_entity(int(chat_id))
                source_title = chat.title
            except:
                source_title = chat_id
        
        # 删除正则格式设置
        deleted = session.query(RegexFormat).filter(
            RegexFormat.chat_id == chat_id
        ).delete()
        
        session.commit()
        
        if deleted:
            await update.message.reply_text(
                f"✅ 已移除正则格式规则\n"
                f"📤 来源: {source_title} ({chat_id})"
            )
        else:
            await update.message.reply_text(f"❌ 未找到 {source_title} 的正则格式规则")
        
    except Exception as e:
        await update.message.reply_text(f"❌ 移除失败: {str(e)}")
    finally:
        session.close()

async def preview_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """置指定来源的链接预览"""
    if update.effective_user.id != USER_ID:
        return
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "请提供来源聊天窗口和预览设置(on/off)\n"
            "例如: /preview https://t.me/channel_name on"
        )
        return
    
    source = context.args[0]
    preview_mode = context.args[1].lower()
    
    if preview_mode not in ['on', 'off']:
        await update.message.reply_text("❌ 预览设置必须是 on 或 off")
        return
    
    session = Session()
    try:
        # 处理链接格式
        if 'https://t.me/' in source:
            try:
                chat = await client.get_entity(source)
                chat_id = str(chat.id)
                source_title = chat.title
            except Exception as e:
                await update.message.reply_text(f"❌ 获取聊天信息失败: {str(e)}")
                return
        else:
            chat_id = source
            try:
                chat = await client.get_entity(int(chat_id))
                source_title = chat.title
            except:
                source_title = chat_id
        
        # 更新或创建预览设置
        preview_setting = session.query(PreviewSetting).filter(
            PreviewSetting.chat_id == chat_id
        ).first()
        
        enable_preview = preview_mode == 'on'
        
        if preview_setting:
            preview_setting.enable_preview = enable_preview
            action = "更新"
        else:
            preview_setting = PreviewSetting(
                chat_id=chat_id,
                enable_preview=enable_preview
            )
            session.add(preview_setting)
            action = "添加"
        
        session.commit()
        
        await update.message.reply_text(
            f"✅ 已{action}链接预览设置\n"
            f"📤 来源: {source_title} ({chat_id})\n"
            f"📝 ��览: {'开启' if enable_preview else '关闭'}"
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ 设置失败: {str(e)}")
    finally:
        session.close()

def main():
    # 创建必要的目录
    for directory in ['sessions', 'data', 'temp']:
        os.makedirs(directory, exist_ok=True)
    
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
    application.add_handler(CommandHandler("export", export_keywords))
    application.add_handler(CommandHandler("switch", switch_format))
    application.add_handler(CommandHandler("regex", regex_format))
    application.add_handler(CommandHandler("regex_list", regex_list))
    application.add_handler(CommandHandler("regex_remove", regex_remove))
    application.add_handler(CommandHandler("preview", preview_setting))
    
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