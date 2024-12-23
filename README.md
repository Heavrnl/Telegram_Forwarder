# Telegram 消息转发机器人

一个功能强大的 Telegram 消息转发机器人，支持多源转发、关键词过滤、正则替换、格式转换等功能。

## 功能特性

- 🔄 **多源转发**：支持从多个来源转发到指定目标
- 📝 **消息格式**：支持 Markdown 和 HTML 格式
- ⚡ **实时转发**：消息实时转发，延迟极低
- 🔍 **关键词过滤**：支持白名单和黑名单模式
- 📋 **正则替换**：支持使用正则表达式处理消息内容
- 🔗 **链接预览**：可控制是否显示链接预览
- 🔒 **安全可靠**：仅限授权用户操作
- 💾 **数据持久化**：配置和数据本地保存

## 部署方法

### 1. 准备工作

1. 获取 Telegram API 凭据：
   - 访问 https://my.telegram.org/apps
   - 创建一个应用获取 `API_ID` 和 `API_HASH`

2. 获取机器人 Token：
   - 与 @BotFather 对话创建机器人
   - 获取机器人的 `BOT_TOKEN`

3. 获取用户 ID：
   - 与 @userinfobot 对话获取你的 `USER_ID`

### 2. 配置环境

1. 克隆项目：
```bash
git clone https://github.com/Heavrnl/Telegram_Forwarder.git
cd telegram-forwarder
```

2. 配置环境变量：
```bash
cp .env.example .env
```

编辑 `.env` 文件，填写以下信息：
```ini
API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token
USER_ID=your_user_id
PHONE_NUMBER=your_phone_number
```

### 3. 启动服务

首次运行（需要验证）：
```bash
docker-compose run -it telegram-forwarder
```

后台运行：
```bash
docker-compose up -d
```

## 使用说明

### 基本命令

- `/start` - 显示帮助信息
- `/binding <来源ID或链接>` - 绑定来源聊天窗口
- `/unbinding` - 解除当前窗口的所有绑定
- `/add <关键字>` - 添加过滤关键字
- `/remove <关键字>` - 删除过滤关键字
- `/list` - 查看当前配置信息
- `/export` - 导出关键字列表
- `/switch <来源> <格式>` - 设置消息格式(html/markdown)
- `/regex <来源> <正则> [格式]` - 设置正则表达式
- `/regex_list <来源>` - 查看正则规则
- `/regex_remove <来源>` - 移除正则规则
- `/preview <来源> <on/off>` - 设置链接预览

### 注意事项

1. 首次运行需要进行 Telegram 账号验证
2. 确保机器人具有目标频道/群组的管理员权限
3. 所有命令仅限授权用户（USER_ID）使用
4. 配置和数据会保存在本地的 data 目录中

## 许可证

MIT License

