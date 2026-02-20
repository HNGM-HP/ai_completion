# AGENTS.md

本文件用于指导自动化编码代理在本仓库内工作。
请严格遵循以下约定，优先保证“对普通人有用”的资讯质量。

## 范围与目标
- 目标内容：变现机会、效率提升、学习成长、生活改善、安全合规。
- 产出格式：可读、可推送、可追踪。
- 风格要求：清晰、具体、避免夸大。

## 仓库结构
- `src/main.py`：主入口，支持 `--run-rss`/`--run-github`/`--run-all`/`--push-only`。
- `src/ai_briefing/collector`：采集器（GitHub/RSS）。
- `src/ai_briefing/ranker`：聚类与评分逻辑。
- `src/ai_briefing/briefing`：LLM 生成简报。
- `src/ai_briefing/output_builder.py`：分支产出拼装（Branch1/Branch2）。
- `src/ai_briefing/pusher`：飞书推送（应用消息/文档）。
- `src/ai_briefing/image_generation.py`：图片生成与保存。
- `src/scripts`：运维脚本（去重、重生成、检查、事件 worker）。
- `src/scripts/run_feishu_events.py`：飞书长连接事件 worker。
- `tests/test_rss_feeds.py`：RSS 可用性测试脚本。
- `configs/`：配置文件（`prompt_templates.yaml`/`branch_specs.yaml`/`rss_sources.yaml`）。

## 构建 / 依赖
无传统 build 步骤，直接运行 Python。

安装依赖：
```
python -m pip install -r requirements.txt
```

## 运行命令（常用）
RSS 流程（不推送）：
```
python -u src/main.py --run-rss --no-push
```

GitHub 流程（不推送）：
```
python -u src/main.py --run-github --no-push
```

全流程（含推送）：
```
python -u src/main.py --run-all
```

仅推送待发送简报：
```
python -u src/main.py --push-only
```

反馈事件长连接 worker：
```
python -u src/scripts/run_feishu_events.py
```

## 运行流程说明
1) 采集阶段：抓取 GitHub/RSS 数据写入 `repos`、`items` 与 `raw_items`。
2) 聚类阶段：对 RSS 聚类并评分，生成 `clusters`。
3) 生成阶段：去重后调用 LLM，写入 `outputs`（Branch1/Branch2）。
4) 推送阶段：Branch1 通过应用卡片推送；Branch2 生成 docx 文档。
5) 反馈阶段：事件 worker 写入 `user_feedback` 并影响后续排序。

## AI 目录初始化说明
（以下内容从 `AI/AGENTS.md` 合并）

本目录用于放置与 AI 简报系统相关的运行说明、策略配置与排障记录。

运行方式（本机手动）：
1) RSS 新闻采集与生成（不推送）：
```
python -u src/main.py --run-rss --no-push
```
2) GitHub 项目采集与生成（不推送）：
```
python -u src/main.py --run-github --no-push
```
3) 全流程（含推送）：
```
python -u src/main.py --run-all
```

维护建议：
- 先用 --no-push 验证数据与简报质量，再打开推送。
- 观察日志中的 duplicates/skip 统计，判断 RSS 是否有新增。
- 如推送未收到，检查应用权限 `im:message:send` 与 `FEISHU_PUSH_CHAT_ID`。
- 反馈不生效时，检查事件 worker 是否在运行。

## 测试命令
当前无 pytest 配置，测试为脚本式：

运行 RSS 源可用性测试：
```
python -u tests/test_rss_feeds.py
```

运行 LLM Provider 最小验证：
```
python -u src/scripts/test_llm_providers.py
```

单测某一条 RSS：
- 编辑 `tests/test_rss_feeds.py`，临时只保留 1 条候选源。
- 测试完成后恢复原列表。

## Lint / Format
- 当前无统一 lint/format 命令。
- 保持与现有代码风格一致，避免引入未配置的格式化器。

## 关键环境变量
- `DATABASE_URL`：PostgreSQL 连接串。
- `FEISHU_APP_ID` / `FEISHU_APP_SECRET`：飞书应用凭证。
- `FEISHU_PUSH_CHAT_ID`：应用推送固定群会话 ID。
- `FEISHU_EVENT_ENCRYPT_KEY` / `FEISHU_EVENT_VERIFICATION_TOKEN`：事件长连接配置（WebSocket模式无需配置）。

### 飞书应用权限清单（快捷导入）

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
- `GITHUB_TOKEN`：GitHub GraphQL Token。
- `LLM_PROVIDER`：LLM 提供方（默认 `glm`）。
- `LLM_MODEL`：默认模型（可写成 `provider:model`）。
- `GLM_API_KEY` / `GLM_BASE_URL`：GLM 配置。
- `OPENAI_API_KEY` / `OPENAI_BASE_URL`：OpenAI 兼容配置。
- `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL`：DeepSeek 兼容配置。
- `TONGYI_API_KEY` / `TONGYI_BASE_URL`：通义千问兼容配置。
- `MINIMAX_API_KEY` / `MINIMAX_BASE_URL`：MiniMax 兼容配置。
- `GOOGLE_AI_API_KEY` / `GOOGLE_OPENAI_BASE_URL`：Gemini 兼容配置。
- `GLM_ENABLE_THINKING`：是否启用 Thinking。
- 模型字段支持 `provider:model` 前缀路由。
- `LLM_TIMEOUT_SECONDS`：LLM 超时（秒）。
- `LLM_MAX_WORKERS`：LLM 并发数。
- `LLM_RETRY_MAX`：LLM 重试次数。
- `LLM_RETRY_BACKOFF_SECONDS`：LLM 重试退避秒数。
- `LLM_CACHE_ENABLED`：LLM 缓存开关。
- `PROMPT_TEMPLATES_FILE`：提示词模板路径。
- `RSS_SOURCES_FILE`：RSS 源文件路径。
- `RSS_MAX_WORKERS`：RSS 并发抓取数。
- `NEWS_WINDOW_HOURS`：新闻聚类窗口（小时）。
- `NEWS_BACKFILL_MAX_STEPS`：新闻补齐步骤次数。
- `NEWS_BACKFILL_WINDOW_MULTIPLIER`：补齐窗口倍数。
- `NEWS_BACKFILL_THRESHOLD_STEP`：补齐时相似度下降幅度。
- `BRIEF_DEDUP_HOURS`：简报去重窗口（小时）。
- `FEISHU_GROUP_BY_KIND`：按新闻/项目分组推送。
- `GRAPHVIZ_FONT`：Graphviz 中文字体名（流程图渲染）。

## 数据库与迁移
- 表结构见 `PostgreSQL.ini`。
- 迁移辅助脚本在 `PostgreSQL.ini` 底部（可重复执行）。
- 所有写入使用 `psycopg` 与 `get_conn(settings)`。
- 对简报的去重以 24 小时窗口为主。

## 代码风格（事实）
- 语言：Python 3.12。
- 缩进：当前代码使用 4 空格。
- 命名：函数/变量多为 `snake_case`，类名为 `CamelCase`，常量为大写。
- 日志：使用 `logging`，日志内容多为中文或中英混合。
- 时间：使用 `datetime` UTC 时间。

## 代码风格（要求）
- 新增代码保持 4 空格缩进，避免混用 2 空格。
- import 顺序：标准库 → 第三方 → 本地模块，中间空一行。
- 避免 `import *`，尽量显式导入。
- 公共函数建议添加类型提示。
- 禁止使用 `Any`，必须给出清晰类型。
- 变量名用 `snake_case`，函数名以动词开头。
- 新增注释请使用简体中文，简短准确。

## 错误处理与日志
- 采集/推送失败必须记录错误原因。
- 网络请求必须有超时，避免卡死。
- 数据库写入失败应回滚并记录日志。
- 飞书接口返回 `code != 0` 视为失败。

## 价值优先策略
- 排序优先级：变现 > 效率 > 学习 > 生活改善 > 安全合规。
- 评分必须体现普通人收益，而不是仅凭热度。
- 简报必须明确“对普通人有什么好处”。

## 运行脚本（维护）
- 清理待推送：`src/scripts/clear_pending_briefs.py`
- 强制重生成新闻：`src/scripts/force_regenerate_news.py`
- 清理重复简报：`src/scripts/clear_duplicate_briefs.py`
- 事件 worker：`src/scripts/run_feishu_events.py`

## 提示词模板
- 模板文件：`configs/prompt_templates.yaml`
- 修改模板后无需改代码，重启任务即可生效。

## 链接选择策略
- 新闻简报只选一个链接。
- 优先非 arxiv 链接，只有无其他来源时才回退 arxiv。
- 选择过程可复现（以聚类 id 为随机种子）。

## 变更约束
- 修改表结构必须同步 `PostgreSQL.ini` 与 README。
- 修改环境变量必须同步 README。
- 不能在日志中输出密钥或 `.env` 内容。

## 你可能会用到的命令
打开管理菜单：
```
python -u src/scripts/manage.py
```

仅 RSS 抓取（不生成简报）：
```
python -u src/main.py --rss-collect-only
```

仅基于已有数据生成简报：
```
python -u src/main.py --rss-brief-only
```

## 没有发现的规则文件
- 未发现 `.cursor/rules/` 或 `.cursorrules`。
- 未发现 `.github/copilot-instructions.md`。

## 排错提示（常见）
- RSS 0 条：多为重复或 hash 冲突，查看采集日志中 duplicates。
- 推送未收到：确认应用消息权限与 `publish_log`。
- 反馈未生效：确认事件 worker 运行与事件订阅配置。
- GitHub 卡顿：调整 `LLM_TIMEOUT_SECONDS` 与 `LLM_MAX_WORKERS`。
- LLM 失败：确认当前 provider 的 API Key/Base URL 与网络可达性。

## 维护清单（执行前确认）
- [ ] `.env` 已配置且未泄露
- [ ] 数据库迁移已执行
- [ ] 使用 `--no-push` 做过一次验证
- [ ] 事件 worker 已启动
- [ ] 日志无连续超时
