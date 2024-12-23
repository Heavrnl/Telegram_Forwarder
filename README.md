# Telegram 消息转发机器人

一个基于 Python 的 Telegram 消息转发机器人，支持关键词过滤、媒体转发等功能。

## 功能特点

- 支持多个来源聊天/频道的消息转发
- 支持白名单/黑名单关键词过滤
- 支持图片、媒体组等多媒体消息转发
- 支持 Docker 部署
- 交互式配置，使用简单

## 环境要求

- Docker 和 Docker Compose
- Telegram API 密钥 (API_ID 和 API_HASH)
- Telegram Bot Token
- 用户 ID 和手机号

## 快速开始

1. 克隆仓库：
```bash
git clone <repository_url>
cd telegram-forwarder
```

2. 配置环境变量：
   复制 `.env.example` 到 `.env` 并填写以下信息：
```ini
# Telegram API credentials
API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token
USER_ID=your_user_id
PHONE_NUMBER=your_phone_number

# Database
DATABASE_URL=sqlite:///data/telegram_forwarder.db

# Debug mode
DEBUG=false
```

3. 启动服务：

首次运行（需要验证）：
```bash
docker-compose run -it telegram-forwarder
```

后台运行：
```bash
docker-compose up -d
```

## 使用说明

机器人支持以下命令：

- `/start` - 显示帮助信息
- `/binding <来源ID或链接>` - 绑定来源聊天窗口
- `/unbinding` - 解除所有绑定
- `/add <关键字>` - 添加过滤关键字
- `/remove <关键字>` - 删除过滤关键字
- `/list` - 查看当前配置信息


## 许可证

[MIT License](LICENSE)

