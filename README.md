# 文件储存分享机器人

> 版权所有 © 岁岁 | Telegram: @qqfaka

一款功能完整的 Telegram 文件储存与分享机器人，支持免费、付费、提取码三种分享权限，最大支持 4GB 文件。

## 功能

| 功能 | 说明 |
|------|------|
| 📁 文件上传 | 直接发送文件即可上传，支持文档/图片/视频/音频 |
| 🆓 免费分享 | 生成分享口令，任何人可直接获取 |
| 💰 付费下载 | 设定价格，买家扣余额，卖家自动到账（平台抽成 10%） |
| 🔐 提取码 | 设置 4~8 位提取码，凭码取文件 |
| 🔍 找文件 | 查看自己上传的所有文件 |
| 🔎 搜索文件 | 关键词搜索公开文件 |
| ❤️ 收藏箱 | 收藏喜欢的文件，随时取用 |
| 💰 充值系统 | 管理员手动充值，余额实时到账 |

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/Guyi888/file-share-bot.git
cd file-share-bot
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置

打开 `bot.py`，修改以下两处：

```python
BOT_TOKEN = "你的BotToken"      # 从 @BotFather 获取
ADMIN_IDS = [你的用户ID]         # 你的 Telegram 用户 ID
```

### 4. 运行

```bash
python bot.py
```

## 使用说明

### 上传文件

直接向机器人发送任意文件，按提示选择权限：

- **🆓 免费** — 生成 `/get XXXXXX` 口令，发给任何人即可
- **💰 付费** — 设定价格，他人需扣余额才能下载
- **🔐 提取码** — 设置 4~8 位密码，持码者才能获取

### 获取文件

```
/get <分享码>
```

### 管理员充值

```
/recharge <用户ID> <金额>
```

## 部署到服务器（CentOS）

```bash
pip3 install python-telegram-bot==21.6
nohup python3 bot.py &
```

推荐使用宝塔面板进程守护管理器长期运行。

## 项目结构

```
file-share-bot/
├── bot.py           # 主程序
├── requirements.txt # 依赖列表
└── filebot.db       # SQLite 数据库（运行后自动生成）
```

## 依赖

- Python 3.8+
- python-telegram-bot 21.6

---

**© 2025 岁岁 | Telegram: @qqfaka**
