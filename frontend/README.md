# 中文交易后台

当前界面版本为 `3.2.1-nfi-ui.4`。

本目录基于 [FreqUI 3.2.1](https://github.com/freqtrade/frequi/tree/3.2.1)，提交
`4e1717ad1eaaf98447ebe2bdf4c00c8d755d2191`，保留原项目的 [GPL-3.0 许可证](LICENSE)。
对应已验证的 Freqtrade 版本为 `2026.10`。

## 使用

默认显示简体中文。登录前后的顶部导航栏和“设置”页面均可切换中文、English，偏好保存在当前浏览器中。
支持登录、导航、交易列表、持仓详情、交易确认、钱包余额、收益统计、币对列表、日志控制、回测及分析等页面。
切换语言会重新创建当前页面，尚未提交的表单会重置，已保存的登录信息和机器人连接配置保留。

策略名称、交易对、订单参数、用户自定义标签及服务器原始日志保留原文；未收录的服务器消息显示原文。

## 账户与安全

从侧栏、账户菜单或“设置”进入“账户与安全”，可验证当前密码后修改密码、退出所有设备，或退出当前浏览器。
密码支持 12–128 个字符（包括中文），禁止控制字符；表单提供显示／隐藏密码按钮。
改密或退出所有设备会撤销访问令牌、刷新令牌并关闭浏览器 WebSocket，交易循环继续运行。
登录失效后会自动返回登录页。旧版机器人没有账户接口时，页面会提示升级。

后端扩展位于 `../webserver_extensions/nfi_account/`，随自定义 Docker 镜像安装；单独替换网页不能启用改密。
持久化、初始化配置和管理员恢复方法见 [部署说明](../docs/installation/chinese-ui.md#账户与密码)。

## 看板与工作台

- 桌面侧栏、手机底部导航，支持深浅主题及键盘操作；图标随应用打包，可离线显示。
- 账户总览展示净值、较初始资金变化、已实现及持仓交易盈亏，并提供 24 小时、7 天、30 天及全部记录范围。
- 每日钱包估值来自 `/historic_balance`。`capture_start_ts` 之前的重建记录使用虚线，不推断历史浮盈亏。
- 实时净值采用 `/balance` 的 `total_bot`（旧版本回退到 `total`），**不再次加上持仓盈亏**。
  页面打开且自动刷新启用时每分钟采集一次，以 5 分钟粒度存入当前浏览器，保留最长 31 天；超过 10 分钟未采集会断线。
  账户地址、机器人、币种、模拟／实盘模式、初始资金和机器人启动时间共同区分观测记录。
- 资金变化包含出入金，不等同于扣除出入金后的策略收益率。图表下方提供数据表，历史与观测可逐条核对。
- 交易页提供有文字的控制按钮、持仓／历史表格、订单详情与蜡烛图；日志支持搜索与级别筛选。

## 回测与策略库

模拟盘侧栏提供“回测”“策略库”和“策略配方”。回测默认选择最近 3 个完整月份、10,000 USDT，
通过独立的 Compose `backtesting` 服务执行，沿用当前后台登录。该服务不向主机开放端口。
主服务仅转发列入允许清单的研究接口；策略选择只影响回测，不切换模拟盘策略。

先下载历史行情，再开始回测。系统按时间周期分别补齐 900 根预热 K 线，下载和回测在离开页面后继续。
结果提供逐月净收益、基于月初已实现资金的收益率、交易数、胜率、柱状图和 CSV。
零交易月份显示零，首尾不足整月会标记；资金口径不包含月末持仓浮盈亏。
回测结果存放于 `user_data/research/backtest_results/`，重启后可从历史结果加载。

默认配方为 Binance 现货 40 个固定回测币对、6 个持仓、单边手续费 0.1%。
“策略配方”可调整持仓数、资金比例、动态筛选条件、手续费、入场滑点容忍度及固定回测币池。
保存后供下一次研究任务使用；单独“应用到模拟盘”会重载配置，保留交易数据库和初始资金。
配方值优先于同名环境变量，固定 5m 和必要退出设置，不支持实盘应用。
默认值见 `webserver_extensions/nfi_research/recipe_defaults.json`，运行时版本持久化于 `user_data/recipes/`。
参数范围、作用范围与验证结果见 [策略配方说明](../docs/installation/chinese-ui.md#策略配方)。
这是固定币对测试，与模拟盘动态选币的表现不同；不能据此承诺未来月收益。
新增策略时，在 Compose 回测服务中挂载对应 `.py` 文件，再重新创建服务。

## 本地开发

使用 Node.js 26 和 `package.json` 指定的 pnpm 12.14.0：

```bash
cd frontend
pnpm install --frozen-lockfile
NFI_API_PROXY_TARGET=http://127.0.0.1:18080 pnpm dev
```

打开终端显示的本机地址（默认端口 3000）。开发服务器将 API 和 WebSocket 请求转发给指定机器人。
在登录表单中使用开发页面自身的地址即可通过代理连接。

```bash
pnpm i18n:check
pnpm lint-ci
pnpm typecheck
pnpm test:unit
pnpm build
pnpm exec playwright install chromium
pnpm test:e2e
```

浏览器测试使用模拟接口，包含中文登录、语言持久化、确认框取消、订单参数、资金图表、失败恢复、日志筛选、账户管理、配方保存／应用与手机布局。
如需使用本机 Chromium，可设置 `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium`。

后端回归测试使用真实 Freqtrade 认证依赖和临时账户目录，在仓库根目录运行：

```bash
docker run --rm --network none -w /extensions \
  -e PYTHONPATH=/extensions:/freqtrade -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PWD/webserver_extensions:/extensions:ro" \
  -v "$PWD/tests/account:/account-tests:ro" \
  --entrypoint python nfi-paper:local \
  -m unittest discover -s /account-tests -v
```

## 维护翻译

界面显示文字使用 `src/i18n/index.ts` 的 `tr()`，英文原文作为键，中文译文集中在 `src/i18n/zh-CN.json`。
动态内容使用命名或数字占位符，例如 `tr('Orders {0}', { 0: tradeId })`。
`pnpm i18n:check` 检查翻译缺失和占位符是否一致。API 字段、枚举值、路由和用户输入不能作为翻译对象。

上游升级时应对比此固定版本，合并源代码后运行上述检查，并同时验证目标 Freqtrade 版本。
Docker 构建会编译本目录并替换镜像中的 FreqUI；镜像内直接运行 `freqtrade install-ui` 会覆盖中文版本。
