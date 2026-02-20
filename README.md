# AI Briefing System 交付文档 & 使用说明

## 1. 系统简介 (Project Overview)
本系统是一个自动化的 AI 简报生成平台，旨在每日定时收集、分析并推送**对普通人有用**的前沿 AI 资讯（变现、效率、学习、生活改善等）。系统包含两大核心模块：
*   **GitHub 趋势**: 追踪每日热门开源项目，生成简明摘要。
*   **AI 新闻**: 聚合 Hugging Face, Google AI, DeepMind 等权威 RSS 源，通过语义聚类发现热点话题，并使用 LLM 生成中文简报。

最终产出的简报会通过飞书应用消息推送至指定群组。

---

## 2. 功能特性 (Features)
*   **多源采集**: 支持 GitHub Trending API (Python) 及标准 RSS 协议。
*   **智能分析**:
    *   **价值优先**: 以“对普通人有用”为核心信号进行排序（变现机会、效率提升、学习成长、生活改善、安全合规）。
    *   **LLM 摘要**: 集成 GLM-4 (智谱 AI) 模型，生成更强调现实收益的项目/新闻解读（"One-liner", "Why it matters", "Key Features"）。
    *   **提示词模板化**: 使用 `prompt_templates.yaml` 配置 repo/news 模板，避免硬编码。
    *   **语义聚类**: 使用 RapidFuzz 对海量 RSS 新闻进行聚类，自动去重并识别高价值话题（Cluster）。
    *   **补齐策略**: 当新闻不足时，自动扩大窗口并降低阈值进行补齐。
    *   **链接选择策略**: 同一话题只选一个链接，优先非 arxiv，必要时回退。
    *   **反馈闭环**: 用户反馈会影响后续排序与过滤（近 30 天）。
    *   **双分支产出**: Branch1 应用卡片推送（含反馈按钮），Branch2 生成 docx 公众号稿。
*   **持久化存储**: 使用 PostgreSQL (配合 pgvector 扩展) 存储原始数据、聚类结果及历史简报。
*   **自动化调度**: 基于 Systemd Timer 实现每日定时无人值守运行。
*   **弹性架构**: 模块化设计 (Collector -> Ranker -> Briefing -> Pusher)，支持单独运行或全流程编排。

---

## 3. 技术栈 (Tech Stack)
*   **语言**: Python 3.12
*   **数据库**: PostgreSQL 15+ (pgvector 扩展)
*   **LLM 服务**: 兼容 OpenAI 接口的模型服务 (当前配置：ZhipuAI GLM-4)
*   **部署环境**: Linux (CentOS/Ubuntu), Sytemd
*   **关键库**:
    *   `psycopg`: 数据库连接
    *   `feedparser`: RSS 解析
    *   `rapidfuzz`: 文本相似度计算 (聚类)
    *   `requests`, `python-dotenv`, `PyYAML`: 基础网络与配置
    *   `lark-oapi`: 飞书应用消息与事件长连接

---

## 4. 部署指南 (Deployment Guide)

### 4.1 环境准备
目标服务器需安装以下基础软件：
```bash
# 安装 Python 3.12 (示例)
sudo apt-get install python3.12 python3.12-venv python3.12-dev

# 安装 PostgreSQL 及 pgvector
sudo apt-get install postgresql postgresql-contrib
# (需确保已安装 pgvector 扩展，具体视发行版而定)

# 安装 Graphviz 与中文字体（用于流程图）
sudo apt-get install graphviz fonts-noto-cjk
```

### 4.2 代码部署
将项目代码上传至服务器 `/opt/ai_briefing` 目录：
```bash
# 示例路径结构
/opt/ai_briefing/
├── src/                # 源代码
│   ├── main.py          # 主入口
│   ├── ai_briefing/      # 核心模块
│   └── scripts/          # 事件 worker 等脚本
├── deploy/             # 部署配置 (systemd)
├── configs/            # 配置文件（模板/规格/RSS）
├── images/             # 图片输出目录
├── tests/              # 测试脚本
├── PostgreSQL.ini      # 表结构与迁移说明
├── .env                # 配置文件
└── README.md           # 说明文档
```

### 4.3 安装依赖
```bash
cd /opt/ai_briefing
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4.4 数据库初始化
确保数据库连接串正确，并初始化表结构。
> 首次运行时，系统会自动检查表结构（如果使用了 ORM 或迁移脚本）。
> 本项目当前版本依赖手动或脚本建表，请参考 `src/scripts/check_schema.py` 确认表结构 (`repos`, `items`, `clusters`, `briefs`, `outputs`, `publish_log`, `user_feedback`, `raw_items`, `factchecks`)。
> 如果已存在旧表，请执行 `PostgreSQL.ini` 底部的 Migration Helpers 进行字段同步。

---

## 5. 配置说明 (Configuration)

### 5.1 环境变量 (`.env`)
在项目根目录创建 `.env` 文件，内容如下：

```ini
# 数据库配置
DATABASE_URL=postgresql://user:password@localhost:5432/dbname

# 飞书推送配置（应用消息）
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_PUSH_CHAT_ID=oc_xxx
FEISHU_EVENT_ENCRYPT_KEY=xxx
FEISHU_EVENT_VERIFICATION_TOKEN=xxx
FEISHU_MAX_CHARS=3000   # 单条消息最大字符数（超过则拆分）
FEISHU_GROUP_BY_KIND=true # 按新闻/项目分组推送

# GitHub Token (可选，用于提高 API 限流阈值)
GITHUB_TOKEN=ghp_xxx

# LLM 配置（支持多厂商，模型可加前缀 provider:model）
LLM_PROVIDER=glm
LLM_MODEL=           # 可选，不填则按 LLM_PROVIDER 使用默认模型
GLM_API_KEY=xxx
GLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
GLM_ENABLE_THINKING=false
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
TONGYI_API_KEY=
TONGYI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MINIMAX_API_KEY=
MINIMAX_BASE_URL=https://api.minimax.io/v1
GOOGLE_AI_API_KEY=xxx
GOOGLE_OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_TIMEOUT_SECONDS=60  # LLM 请求超时时间（秒）
LLM_MAX_WORKERS=1       # LLM 并发请求数（建议与模型限额一致）
LLM_RETRY_MAX=1          # LLM 重试次数
LLM_RETRY_BACKOFF_SECONDS=2 # LLM 重试退避秒数
LLM_CACHE_ENABLED=true   # LLM 缓存开关
PROMPT_TEMPLATES_FILE=/opt/ai_briefing/configs/prompt_templates.yaml

# 任务模型拆分（可选，不填则使用 LLM_MODEL）
LLM_TASK_MODEL_REPORT=glm:glm-4.7-flashx
LLM_TASK_MODEL_FACTCHECK=glm:glm-4-plus
LLM_TASK_MODEL_DEDUP=glm:glm-z1-flash
LLM_TASK_MODEL_RANKING=glm:glm-z1-air
LLM_TASK_MODEL_WECHAT=glm:glm-4-plus
IMAGE_MODEL=google:imagen-4.0-generate-001
BRANCH_SPECS_FILE=/opt/ai_briefing/configs/branch_specs.yaml
X_ENABLED=true

# 飞书文档每日子文件夹
FEISHU_DOC_DAILY_FOLDER=true
FEISHU_DOC_DATE_FORMAT=%Y-%m-%d

# 图片生成配置
IMAGE_PROMPT_ENABLED=true
IMAGE_OUTPUT_DIR=/opt/ai_briefing/images
IMAGE_MAX_COUNT=3
IMAGE_SIZE=1024x1024
IMAGE_DOCX_PARENT_TYPE=docx_image
GRAPHVIZ_FONT=Noto Sans CJK SC

# 业务参数
DAILY_TOP_REPOS=10      # 每日处理 GitHub 项目数
DAILY_TOP_NEWS=10       # 每日生成新闻简报数
HOURLY_TOP_REPOS=5
NEWS_WINDOW_HOURS=72    # 新闻聚类与排序窗口（小时）
RSS_MAX_WORKERS=10      # RSS 并发抓取线程数上限
BRIEF_DEDUP_HOURS=24    # 简报去重窗口（小时），设为 0 可关闭
NEWS_BACKFILL_MAX_STEPS=2        # 补齐步骤次数
NEWS_BACKFILL_WINDOW_MULTIPLIER=2 # 每次补齐的窗口倍数
NEWS_BACKFILL_THRESHOLD_STEP=5    # 每次补齐的相似度下降幅度

# RSS 源配置文件路径 (可选，默认为 ./configs/rss_sources.yaml 或 /opt/ai_briefing/configs/rss_sources.yaml)
RSS_SOURCES_FILE=/opt/ai_briefing/configs/rss_sources.yaml
```

#### 5.1.1 反馈事件长连接
启动事件 worker：
```bash
python -u src/scripts/run_feishu_events.py
```
systemd 常驻：
```bash
systemctl enable --now ai-briefing-events.service
systemctl status ai-briefing-events.service
```

#### 5.1.2 LLM Provider 最小验证
```bash
python -u src/scripts/test_llm_providers.py
```

### 5.2 RSS 源配置 (`configs/rss_sources.yaml`)
通过修改此 YAML 文件管理新闻源：

```yaml
- name: "Hugging Face Blog"
  url: "https://huggingface.co/blog/feed.xml"
  lang: "en"
  tags: ["hf", "ai"]

- name: "Google AI Blog"
  url: "https://ai.googleblog.com/atom.xml"
  lang: "en"
  tags: ["google", "research"]

- name: "Sebastian Raschka"
  url: "https://magazine.sebastianraschka.com/feed"
  lang: "en"
  tags: ["newsletter", "learning"]
```

---

### 5.3 提示词模板配置 (`configs/prompt_templates.yaml`)
用于自定义 repo/news 简报的提示词模板，支持占位符替换。

占位符（不要删除）：
- repo 模板：`{repo_full_name}`、`{repo_url}`、`{repo_description}`、`{repo_topics}`、`{repo_language}`
- news 模板：`{items_text}`、`{cluster_title}`

默认路径由 `PROMPT_TEMPLATES_FILE` 指定，示例文件位于：
`/opt/ai_briefing/configs/prompt_templates.yaml`

新增分支模板：
- `news_template_branch2`
- `repo_template_branch2`

### 5.4 分支规格配置 (`configs/branch_specs.yaml`)
用于控制 Branch1/Branch2 的结构与规则（段落开关、条数上限、低置信度分流、引用规则等）。

默认路径由 `BRANCH_SPECS_FILE` 指定，示例文件位于：
`/opt/ai_briefing/configs/branch_specs.yaml`

## 6. 使用说明 (Usage)

### 6.1 手动运行 (Manual Execution)
进入项目目录并激活虚拟环境后，使用 `src/main.py` 运行：

```bash
cd /opt/ai_briefing
source venv/bin/activate
export PYTHONPATH=/opt/ai_briefing/src

# 运行完整流程 (GitHub + RSS + 推送)
python -u src/main.py --run-all

# 仅运行 GitHub 流程
python -u src/main.py --run-github

# 仅运行 RSS/新闻 流程
python -u src/main.py --run-rss

# 运行流程但不推送 (用于测试生成)
python src/main.py --run-all --no-push
```

说明：当前推送优先使用 `outputs`（Branch1/Branch2），Branch2 仅推送已审核通过的内容。

### 6.2 记录用户反馈（最小闭环）
通过命令行将反馈写入 `user_feedback` 表：

```bash
# 直接输入指令
python -u src/scripts/record_feedback.py --command "👍 123" --topic-kind news

# 或者显式传参
python -u src/scripts/record_feedback.py --topic-kind repo --topic-ref-id 456 --label useful --reason "有用" --user-id "u_001"
```

### 6.3 输出待审队列
当 factcheck 低置信度时，Branch2 会写入 `outputs.status = review`。

```bash
# 列出待审输出
python -u src/scripts/list_outputs_review.py

# 审核通过
python -u src/scripts/mark_output_approved.py --output-id 123
```

### 6.2 查看日志
程序日志默认输出到标准输出 (stdout/stderr)，在 Systemd 模式下由 journald 接管，手动模式下直接显示在终端。

### 6.3 运行流程说明
1) 采集阶段：抓取 GitHub/RSS 数据并写入 `repos` 与 `items`。
2) 聚类阶段：对 RSS 进行聚类、评分，生成 `clusters`。
3) 生成阶段：先做简报去重，再调用 LLM 生成简报写入 `briefs`。
4) 推送阶段：按类型分组 + 字符数拆分推送到飞书。

---

## 7. 自动化运维 (Automation)

系统已配置 Systemd Timer 每天上午 9:00 自动触发。

### 7.1 服务管理命令
```bash
# 查看定时器状态 (下次运行时间)
systemctl status ai-briefing.timer

# 查看上次运行的服务状态
systemctl status ai-briefing.service

# 手动触发一次后台任务
systemctl start ai-briefing.service

# 停止定时任务
systemctl stop ai-briefing.timer
systemctl disable ai-briefing.timer
```

### 7.2 故障排查 (Troubleshooting)

**问题：没有收到飞书消息？**

**1. 检查应用权限配置**

请确保飞书应用已开通以下所有权限（共13个）：

**快捷导入权限（JSON配置）：**
```json
{
  "scopes": {
    "tenant": [
      "im:message:send",
      "im:message:receive",
      "im:chat:readonly",
      "drive:drive",
      "drive:drive:readonly",
      "space:document:retrieve",
      "docx:document",
      "docx:document:create",
      "im:message.card:send",
      "card:action:trigger",
      "im:message.group_msg",
      "im:message.group_msg:readonly",
      "im:chat"
    ],
    "user": []
  }
}
```

**权限说明：**

| 类别 | 权限 | 用途 |
|------|------|------|
| **机器人** | `im:message:send` | 发送消息到群聊 |
| | `im:message:receive` | 接收消息事件 |
| **群聊** | `im:chat:readonly` | 读取群信息 |
| | `im:chat` | 群聊管理 |
| | `im:message.group_msg` | 群消息操作 |
| | `im:message.group_msg:readonly` | 读取群消息 |
| **云文档** | `drive:drive` | 编辑云文件 |
| | `drive:drive:readonly` | 查看云文件 |
| | `space:document:retrieve` | 获取文档信息 |
| **文档** | `docx:document` | 查看文档内容 |
| | `docx:document:create` | 创建文档 |
| **卡片** | `im:message.card:send` | 发送卡片消息 |
| **事件** | `card:action:trigger` | 卡片操作回调 |

配置路径：`https://open.feishu.cn/app/{YOUR_APP_ID}/auth`

**2. 检查服务日志：**
```bash
journalctl -u ai-briefing.service -n 50 -e
```

**3. 检查 `publish_log` 数据库表：**
```sql
SELECT * FROM publish_log ORDER BY created_at DESC LIMIT 5;
```

**4. 验证 `.env` 配置：**
确认 `FEISHU_APP_ID`/`FEISHU_APP_SECRET`/`FEISHU_PUSH_CHAT_ID` 是否有效。

**问题：反馈按钮点击无效？**
1.  确认事件 worker 正在运行：
    ```bash
    systemctl status ai-briefing-events.service
    ```
2.  查看事件 worker 日志：
    ```bash
    journalctl -u ai-briefing-events.service -n 50 -e
    ```

**问题：RSS 新闻为空？**
1.  检查日志中 `RSS Collector` 部分，是否有 "Failed to load sources" 或网络超时错误。
2.  确保 `configs/rss_sources.yaml` 格式正确且文件路径可读。
3.  检查 `items` 表是否有数据存入：
    ```sql
    SELECT count(*) FROM items WHERE fetched_at > NOW() - INTERVAL '1 DAY';
    ```

**问题：推送链接总是 arxiv？**
1.  查看聚类条目来源是否都来自 arxiv：
    ```sql
    SELECT domain, COUNT(*) FROM items GROUP BY domain ORDER BY COUNT(*) DESC;
    ```
2.  系统会优先选择非 arxiv 链接，仅在没有其他来源时回退。
3.  如需强制避免 arxiv，可临时移除相关 RSS 源或清理历史数据后重跑。

**问题：中文摘要生成失败？**
1.  检查 LLM API Key 是否过期。
2.  检查日志中 `generator` 部分的报错信息。
