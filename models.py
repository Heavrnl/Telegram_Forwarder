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
    chat_id = Column(String, nullable=False)
    chat_type = Column(String, nullable=False)  # channel, group, private

class Keyword(Base):
    __tablename__ = 'keywords'
    
    id = Column(Integer, primary_key=True)
    word = Column(String, nullable=False)
    is_whitelist = Column(Boolean, default=True)  # True for whitelist, False for blacklist

class Config(Base):
    __tablename__ = 'config'
    
    id = Column(Integer, primary_key=True)
    target_chat_id = Column(String, nullable=False)
    filter_mode = Column(String, nullable=False)  # whitelist or blacklist

def init_db():
    Base.metadata.create_all(engine) 