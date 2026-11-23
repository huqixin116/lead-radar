# lead-radar 获客雷达 MVP

五平台统一的只读获客名单工具：抖音视频、小红书笔记、B站视频、微博帖子、百度贴吧。
按关键词搜内容，抓评论区的人和评论，存库、打分、导出，人工审核后一条一条发。

## 它做什么

- 关键词搜索：每个平台用公开搜索页做起点，不调私有 API
- 评论抓取：抓评论者昵称、用户 ID、主页链接（页面上能看到的才取）、评论内容、时间、点赞
- 存库去重：SQLite，`data/leads.db`，按（平台、内容 ID、用户 ID、评论哈希）去重
- 意向打分：规则打分 0-4，命中“多少钱、哪里买、求链接、怎么买、推荐”等加分，广告、骗子、刷单等减分
- 待审队列：分数 ≥2 的进 `pending_review`，看板里点批准或跳过
- 单条发送：只发已批准的一条，`--dry-run` 只预览，`--confirm` 还要在浏览器里再输一次 `yes` 才点发送

## 它不做什么

- 不做自动群发、不做自动回评论、不批量跑队列
- 不绕验证码、不识别滑块、不破解签名、不调私有接口
- 不抓私密数据，只取公开页面上能看到的评论
- 不碰 MediaCrawler 的代码：本项目从零写，登录和抓取都用 Playwright 真实浏览器

违反平台规则批量发私信、发微信号、外链，很容易限流、禁私信、封号。请小批量、人工审、别发重复内容。

## 目录

```
config.yaml            配置：产品、关键词、平台、意向词、发送上限
requirements.txt       playwright + PyYAML
collector/             采集器：base.py + douyin/xiaohongshu/bilibili/weibo/tieba + login.py + run.py
storage/db.py          SQLite：contents / comments / outreach_queue + 导出 CSV
scoring/scorer.py      规则打分 0-4 + 话术草稿生成
sender/sender.py       单条发送器：--one + --confirm + 每日上限 + 3 次失败熔断
app/app.py             本地看板（标准库 http.server，无 Flask 依赖）
tests/test_mock.py     离线 Mock 测试
sample_data/           5 平台各 2 条假评论，供离线测试用
data/                  运行时生成：leads.db、auth/ 登录态、exports/
```

## 安装

Python 3.11+，Mac / Windows 通用。

```bash
cd lead-radar
pip install -r requirements.txt
playwright install chromium
```

## 第一步：改配置

打开 `config.yaml`，必须改这两处再跑真实采集：

```yaml
product_name: "你的产品名"
product_intro: "一句话介绍，不要放微信号、手机号、外链"
keywords:
  - "你的关键词1"
```

建议先只留 1 个关键词，`max_contents: 3`，`max_comments_per_content: 20`。

## 第二步：人工登录（每个平台一次）

```bash
python -m collector.login --platform douyin
python -m collector.login --platform xiaohongshu
python -m collector.login --platform bilibili
python -m collector.login --platform weibo
python -m collector.login --platform tieba
```

每个命令会打开有界面的浏览器，你自己扫码登录，登录完成后按回车，登录态保存到 `data/auth/<平台>.json`。
遇到验证码请人工通过，不要让脚本绕过。如果登录态失效，重新跑一次这个命令。

## 第三步：小批量采集（先跑 1 个平台、1 个关键词）

```bash
python -m collector.run --platform douyin --keyword 你的关键词1
```

或按 `config.yaml` 全跑（小批量测试不建议）：

```bash
python -m collector.run --all
```

没登录态会直接提示先跑 login，不会硬抓。页面结构变了、选择器失效时只记日志，不崩溃。

## 界面配置

不用改文件，在看板里就能改配置、选平台和关键词：

1. 启动看板（见下面“第四步：看板审核”），打开 http://127.0.0.1:8000/ ，页面最上方就是“配置”区。
2. 填产品名、产品介绍；在关键词框里输入一个词点“添加”，也可以直接粘贴逗号分隔的多个词；点关键词旁边的 × 可以删；意向词（购买/负面）用逗号分隔填。
3. 平台勾选：抖音 / 小红书 / B站 / 微博 / 贴吧，至少勾 1 个。
4. 数字都可以在界面上改：每平台最多内容数（1-20）、每条内容最多评论数（1-100）、每天每平台最多发送（1-50）、发送间隔最短/最长（10-600 秒，最短不能大于最长）、可发送时段开始/结束（0-23 点，开始必须小于结束）。
5. 点“保存配置”：校验通过会写回 `config.yaml`，旧文件自动备份为 `config.yaml.bak`（每次保存覆盖上一次备份）；校验不通过会直接在页面上显示错误原因，不会覆盖原文件。保存成功后页面会自动重新加载配置。
6. 页面打开时会自动从 `GET /api/config` 加载当前配置填到表单里；想放弃改动点“重新加载”即可。

接口（供调试用）：`GET /api/config` 返回当前配置 JSON；`POST /api/config` 接受 JSON，字段同 `config.yaml`，其中关键词、意向词可传列表或逗号分隔字符串。

## 界面采集（小批量）

看板“采集（小批量）”区，不用敲命令行：

1. 勾选要跑的平台（默认按配置里的平台勾选），在关键词下拉框里选一个配置里的关键词，或在“一次性关键词”框里填一个临时的词。
2. 点“开始采集”：后台按勾选的平台顺序逐个跑 `python -m collector.run --platform <平台> --keyword <关键词>`，复用采集器的命令行，不重复写采集逻辑。没登录的平台会跳过，日志里提示先扫码登录。
3. 点“刷新状态”或等页面每 3 秒自动轮询：状态区会显示正在跑哪个平台、哪个关键词，日志框（`<pre>`）显示最近 50 行日志，完整日志同时追加到 `data/run.log`。
4. 点“停止”会终止当前子进程并结束本轮；已有采集在运行时再点“开始采集”会返回 409，不会重复跑。
5. 跑完后页面会自动刷新名单和待审队列。一次只跑一个关键词、少量内容，先测准不准再扩大。

限制：界面采集只做小批量，不做自动群发、不做自动回评论；发送仍要去待审队列人工批准，再用 `sender --one --confirm` 一条一条发。

## 第四步：看板审核

```bash
python -m app.app --port 8000
```

打开 http://127.0.0.1:8000/ ，只在本地打开，不要对外暴露。
按平台、分数筛选名单，看待审队列，点批准或跳过。批准只是改状态，不会自己发。

导出 CSV 也可以直接点页面上的导出链接，或用代码里的 `export_csv`。

## 第五步：一条一条发

先预览，不发：

```bash
python -m sender.sender --one --queue-id 1 --dry-run
```

确认要发，再跑（会打开浏览器、粘贴草稿，点发送前还要你再输一次 `yes`）：

```bash
python -m sender.sender --one --queue-id 1 --confirm
```

规则：一次只发一条；每天每平台上限默认 20 条，`config.yaml` 里 `sender_limits.max_per_day_per_platform` 可改；发送时段默认 9-21 点；同一条连续失败 3 次自动熔断，不再重试；随机等 60-180 秒防高频。

## 对照 MediaCrawler 补了什么，还缺什么

只参考了思路，代码全部自己重写，没有复制 MediaCrawler 的任何代码，
也没有再读它的源码。补上的加固（都在 `tools/`、`proxy/`、`collector/base.py` 里）：

**补了什么**
- CDP 真实浏览器模式：`browser.cdp_mode` 默认开，先连本机已打开的真实 Chrome/Edge（端口 9222），连不上退回 Playwright 的 `launch_persistent_context`，每个平台独立 `data/browser/<平台>`，窗口 1920x1080。
- UA 轮换：`tools/ua.py` 自己维护 6 个桌面 Chrome UA，每次建上下文随机换一个，并记日志（不记 cookie）。
- 最小 stealth 脚本：自己写的几行初始化脚本，只藏 `webdriver` 标志、补 `languages`/`plugins`，不伪造指纹、不抄任何 `stealth.min.js`。
- 代理接入点：`proxy/pool.py` 只支持静态代理，`proxy.enable_ip_proxy` 默认关，`static_proxy_url` 为空时不走代理；代理条目带过期时间，过期后重新加载；验证只做一次轻量 GET，超时 5 秒、重试 3 次。没开代理时看板显示红色横幅，提醒用住宅/手机流量，不要用共享 VPN/服务器 IP。
- 登录健康检查 pong：采集前先打开首页，登录态缺失或页面出现风控词、明确提示“请登录/扫码登录”就停，提示重新跑 `collector.login`，绝不绕验证码/滑块。
- 重试加退避：`tools/retry.py` 只对瞬时错误重试 3 次（等 1、2、4 秒），401/403/429、验证码、滑块、登录过期、IP 被封一律不重试。
- 风控即停：`tools/risk.py` 检测验证码、滑块、登录过期、IP 被封、操作频繁、私信受限等词和 401/403/429 状态码，一旦命中，采集和发送立刻停止整轮，不继续下一个关键词/平台；连续失败 3 次也熔断。
- 人味节奏：采集等待改成基础 2 秒加随机 0-3 秒，滚动停顿随机，每条内容之间随机等 3-8 秒；配置在 `crawler.max_sleep_sec` / `jitter_sec`，并发永远是 1，界面上调高会被校验拒绝。
- 发送加固：每小时上限默认 5 条（界面最多 10 条），每天上限不变；话术有 3 个变体，随机挑一个，不和该平台上一条已发送的相同；发送前再查一次页面风控词，命中就停。

**还缺什么（老实说）**
- 没有各平台的 API 签名（比如小红书 X-S、抖音 a_bogus）：我们故意只走 Playwright 页面抓取，不逆向签名，所以速度慢、选择器一改版就失效。
- 具体到抖音，对照就更明显：MediaCrawler 的抖音客户端是一个真正的 httpx API 客户端，`__process_req_params` 会拼一整套请求参数——`device_platform=webapp`、`aid=6383`、`channel_pc_web`、`version_code=190600`，再加浏览器/引擎/操作系统指纹参数，请求头里带 `x-tt-argus`，`uifid` cookie 从浏览器 localStorage/cookie 里取，参数要签名才发得出去。我们的抖音采集器到现在还是 Playwright 翻搜索页、用硬编码选择器抓 DOM，没有 API 签名、没有这套参数，页面一改版就失效，速度和稳定性都差一个档次。这点没实现，也不打算在这版里逆向它。
- 没有媒体下载、没有 MySQL/Mongo，只用 SQLite。
- 没有多账号轮换，只有一个账号 per 平台，封了就是零；也没有账号健康分。
- 没有付费代理商接入，只有静态代理一个口，代理质量得你自己解决。
- 选择器仍然是硬写的，平台改版要手动改；没有自动适配。
- 以上加固只能降低被封概率，不能保证不封号。真跑之前还是先只读小批量测 3 天，有一次验证码或“操作频繁”就停。

## 我自己测了什么，没测什么

**测了的（都是离线，没碰真平台）：**
- 三套离线测试全部通过，共 28 个：`test_mock` 5 个（5 平台样本覆盖、打分、存库去重、队列加导出加草稿、每日上限计数）；`test_config_ui` 5 个（配置读取、合法保存加重新读取加备份、8 组非法配置返回 400 且不覆盖原文件、采集状态初始为未运行、采集接口非法入参返回 400）；`test_hardening` 18 个（UA 20 次调用至少换 2 个、403 不重试、滑块不重试、瞬时错误重试 3 次后成功、风控词命中与正常文本不误报、代理过期与刷新、静态代理与 Playwright 参数、代理验证假 opener、抖动在 2-5 秒内、并发大于 1 与每小时上限大于 10 被拒绝、话术 3 变体不同且不重复上一条、叶子评论抽取：正文优先取子节点、容器跳过、空白归一化去重、非法 `min_score` 返回 400 而不是 500）。
- `python -m py_compile` 全过，看板启动后 `curl /` 和 `curl /api/config` 都是 200。
- 配置测试用的是临时复制的 `config.yaml`，不会改写真实配置。

**没测的（老实说）：**
- 一次真实采集都没跑过，0 次真抓。
- 这台机器上根本没装 Playwright，`import playwright` 报错，采集器和发送器在真浏览器里的表现完全没验证过。
- 5 个平台的选择器都是按公开页面结构写的起点，没对着真页面测过，平台改版随时可能失效；叶子评论的修法只在假元素上测过，真页面上的容器结构可能不一样。
- 看板只在本地 curl 测过 200，没在真浏览器里点过。

所以第一次真跑必须只读小批量：1 个平台、1 个关键词、3 条内容、每条 20 条评论，跑完先看抓到的评论干不干净、打分准不准，再决定要不要扩大。

## 离线测试（不用联网、不用浏览器）

```bash
python -m tests.test_mock
python -m tests.test_config_ui
python -m tests.test_hardening
```

## 常见问题

- 选择器失效、抓到 0 条：平台改版了，先看日志里是哪一步没找到元素，再按新页面结构改对应平台文件里的选择器，不要改成绕验证的做法。
- 登录态过期：重新跑 `collector.login`。
- 私信入口找不到：sender 会停下来让你人工在浏览器里点开，不要硬点；没找到输入框或发送按钮时记为失败，不会误发。
- 想换产品：只改 `config.yaml` 的 `product_name`、`product_intro`、`keywords`、`intent_keywords`，不用改代码。

## 还需要用户做的事

- 填 `config.yaml` 的产品名、介绍、3-5 个关键词
- 每个平台人工扫码登录一次
- 在看板里人工审核名单和草稿，再一条一条发
- 小批量先测回复率，再决定要不要扩大关键词和数量
