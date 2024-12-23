from sqlalchemy import create_engine, Column, Integer, String, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

Base = declarative_base()
engine = create_engine(
    os.getenv('DATABASE_URL', 'sqlite:///data/telegram_forwarder.db'),
    pool_size=20,  # 增加连接池大小
    max_overflow=0,  # 禁止溢出
    pool_timeout=30,  # 连接超时时间
    pool_recycle=1800  # 每30分钟回收连接
)
Session = sessionmaker(bind=engine)

class Source(Base):
    __tablename__ = 'sources'
    
    id = Column(Integer, primary_key=True)
    chat_id = Column(String, nullable=False)  # 来源ID
    target_chat_id = Column(String, nullable=False)  # 目标ID
    chat_type = Column(String, nullable=False)  # channel, group, private
    filter_mode = Column(String, nullable=False)  # whitelist or blacklist
    parse_mode = Column(String, default='markdown')  # markdown or html

class Keyword(Base):
    __tablename__ = 'keywords'
    
    id = Column(Integer, primary_key=True)
    target_chat_id = Column(String, nullable=False)  # 关联的目标ID
    word = Column(String, nullable=False)
    is_whitelist = Column(Boolean, default=True)  # True for whitelist, False for blacklist

class MessageFormat(Base):
    __tablename__ = 'message_formats'
    
    id = Column(Integer, primary_key=True)
    chat_id = Column(String, nullable=False, unique=True)  # 来源聊天ID
    parse_mode = Column(String, nullable=False, default='markdown')  # markdown or html

class RegexFormat(Base):
    __tablename__ = 'regex_formats'
    
    id = Column(Integer, primary_key=True)
    chat_id = Column(String, nullable=False, unique=True)  # 来源聊天ID,添加unique约束
    pattern = Column(String, nullable=False)  # 正则表达式模式
    parse_mode = Column(String, nullable=False, default='markdown')  # markdown or html

class PreviewSetting(Base):
    __tablename__ = 'preview_settings'
    
    id = Column(Integer, primary_key=True)
    chat_id = Column(String, nullable=False, unique=True)  # 来源聊天ID
    enable_preview = Column(Boolean, default=False)  # 是否启用预览

def init_db():
    Base.metadata.create_all(engine) 