# 多机器人：独立 Docker 实例，统一网页管理

一个交易容器对应一个机器人。现货和逐仓 USDT 合约分别部署，网页可连接多个实例并切换工作台。
已有的 `nfi-live` 实盘无需迁移数据库；下面的命令只创建新实例，不操作原有容器。

## 创建现货或合约实例

在仓库根目录执行（需要 Python 3 和 Docker Compose）：

```bash
# 示例：现有控制台为 http://127.0.0.1:18081，新合约实例使用 18082。
python tools/bots.py create --name okx-futures --mode futures --port 18082 \
  --console-origin http://127.0.0.1:18081
docker compose -f user_data/bots/okx-futures/compose.json build bot
docker compose -f user_data/bots/okx-futures/compose.json up -d bot
```

新现货实例使用另一个名称和空闲端口，例如 `--name okx-spot --mode spot --port 18083`。
`python tools/bots.py list` 列出生成过的实例；创建命令拒绝覆盖目录、占用端口或复用已预留端口。
网页“机器人管理 → 部署新实例”也能生成这些命令；“连接已有机器人”只添加连接，不创建容器。

打开新地址 `http://127.0.0.1:18082`，首次管理员必须在本机或 SSH 隧道中创建。
在“交易账户”填写 OKX 账户、密钥和预算，验证后保存。密钥和余额配置只保存在该实例的私有文件，
不会进入部署命令或 Compose。新实例默认保持停止；确认账户和模式后再启动。
“账户与安全”的容器启动开关独立保存，配置重载仍保持停止。

合约需要先在 OKX 启用支持合约的账户模式；本项目使用逐仓模式，不支持全仓。
网页默认 1 倍，可设置 1–5 倍并统一作用于 X8 各入场模式，实际受交易所限制。
部署时确定的现货/合约模式不能切换。有持仓或挂单时禁止改杠杆；已有交易历史也不能转换模式。
每个机器人应使用独立 OKX 子账户和资金；同一账户的两组密钥不会隔离余额或仓位。

## OKX 合约稳健基线

可参考 [`configs/recipes/okx-futures-conservative.json`](../../configs/recipes/okx-futures-conservative.json)
在“策略配方”设置：最多 6 个持仓、最多 40 个交易标的、上市至少 90 天、最近 24 小时成交额
至少 1,000 万 USDT、价差不超过 0.2%、允许入场滑点不超过 0.5%。交易账户选择逐仓、1 倍杠杆，
各 X8 入场和补仓模式使用相同杠杆；实际预算仍由管理员在“交易账户”单独配置。
这些参数是一套偏稳健的起点，并非通过收益优化得到的最优值；筛选后可能不足 40 个标的。

OKX 合约 ticker 不提供 Freqtrade 所需的 `quoteVolume`。配方自动将前后两个成交量筛选器都
改为使用 24 根已完成的 1 小时 K 线计算 USDT 成交额，每小时刷新一次；不能只调整第一个筛选器。
合约成交量按 Freqtrade 的合约面值转换处理，勿用合约张数直接作为 USDT 成交额。
OKX 合约同步和异步客户端开启限流，`rateLimit` 至少为 200 ms，避免沿用旧配置的 60 ms
导致首次行情扫描触发 `50011`。多个机器人共用出口 IP 时仍共用交易所限额，宜错开启动和下载行情。

保留 X8 的 `5m` 周期、无限制动态单笔金额、加减仓逻辑和策略退出设置：
`use_exit_signal=true`、`exit_profit_only=false`、`ignore_roi_if_entry_signal=true`。
策略止损与减仓开关开启，仍需为追加仓位和资金费保留可用资金。X8 的兜底 `stoploss=-0.99`
不代表单笔亏损被限制为 1%，实际退出依赖策略逻辑，1 倍杠杆也不等于本金保障。

研究手续费沿用保守的每边 0.1% 假设，实盘读取交易所账户费率；不要把该假设当成实际手续费。
更改后先保持机器人停止，验证最终币对、账户独立性、资金预算与回测结果，再决定是否启动。

## 连接统一控制台

在新版本网页的“机器人管理 → 连接已有机器人”输入各实例的浏览器可达地址和各自管理员账号。
卡片显示在线状态、交易模式和持仓数；账户、配方、回测操作针对当前选中的机器人。

`--console-origin` 必须填写统一控制台的完整来源，例如 `https://trade.example.com`，不包含路径。
可以重复该参数。生成文件中的 `NFI_CONSOLE_ORIGINS` 配置精确的 CORS/来源白名单，不使用通配符。
白名单允许已认证的管理请求；首次创建管理员仍仅限本机。

端口默认只绑定 `127.0.0.1`。远程部署通过 SSH 隧道或 HTTPS 反向代理访问；HTTPS 控制台连接的
实例也应使用 HTTPS，避免浏览器阻止混合内容。旧实例需要更新镜像并配置来源白名单后，才能接受
其他来源的管理请求；这些新实例命令不会升级或重启旧实盘。

为原有 `docker-compose.live.yml` 实例应用新界面，可在安排好重启后执行：

```bash
docker compose -f docker-compose.live.yml -f docker-compose.multi-console.yml \
  -p nfi-live up -d --no-build --pull never freqtrade-live
```

此命令需要已经构建好的 `nfi-paper:multi` 镜像，只重建原现货容器，保留挂载的账户和数据库。
若通过域名统一管理，将 `NFI_SHARED_CONSOLE_ORIGINS` 设置为精确来源的 JSON 列表，
并在新实例的 Compose 中同样允许该控制台来源。升级后启动状态遵循其原有网页启动设置；
需要保持停止时，先在旧网页关闭自动启动并停止机器人，再安排升级。

## 独立回测与数据

只在需要回测时启动该实例自己的研究容器：

```bash
docker compose -f user_data/bots/okx-futures/compose.json --profile research up -d
```

每个实例最多两个容器：交易管理和可选研究。研究服务不公开端口，也不挂载实盘密钥，
只读取已应用配方、预算、杠杆与同一份策略快照。回测采用配方中的固定币种集，
与实盘动态筛币结果可能不同；手续费为研究假设，不是实时账户费率。
合约使用 `BTC/USDT:USDT` 格式、独立行情和资金费数据；缺少标记价格/资金费历史时拒绝开始回测。
先在网页下载完整历史数据，再运行回测。切换模式不匹配的研究服务会报错，不展示另一模式的结果。

数据保存在 `user_data/bots/<名称>/live/` 和 `research/`：数据库、管理员、启动偏好、
Bark、代理、策略草稿与回测结果分别隔离。内部研究认证文件为随机生成的私有文件。
目录需要由容器用户 UID 1000 可读写；备份整套实例目录，勿提交到 Git。
使用 root 创建时脚本自动设置新实例目录所有权；其他 UID 的宿主机用户需自行授予 UID 1000 权限。
各实例单独占用资源；下载和回测时尤其需要额外内存，不适合在 1 GB 主机上并行运行。

```bash
docker compose -f user_data/bots/okx-futures/compose.json ps
docker compose -f user_data/bots/okx-futures/compose.json logs --tail 100 bot
# 仅停止这个实例，保留数据；不使用 down -v。
docker compose -f user_data/bots/okx-futures/compose.json --profile research stop
```
