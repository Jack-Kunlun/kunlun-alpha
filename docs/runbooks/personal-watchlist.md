# 服务端个人自选与日线

个人自选属于当前登录账号，保存在 PostgreSQL；浏览器旧清单仅用于一次性迁移和保留备份。迁移或导入返回完整列表并确认代码后才显示成功。服务端已存在的同代码名称保留不变。个人截图、导入文本与运行数据不得提交 Git。

## 接口

既有认证、Cookie 和 CSRF 规则适用，客户端不能指定所有者。

- `GET /api/v1/personal-watchlist`：读取本账号列表及各标的采集状态。
- `POST /api/v1/personal-watchlist/import`：追加合并，最多 2000 项；`clientRequestId` 为 UUID。相同请求安全重试，复用请求编号但改变内容返回 409；校验或事务失败不保存部分列表。

```json
{
  "schemaVersion": "personal-watchlist-import-v1",
  "clientRequestId": "00000000-0000-4000-8000-000000000001",
  "items": [{ "code": "600000.SH", "name": "示例股票" }]
}
```

新接口为兼容性增量，Schema 使用 `personal-watchlist-import-v1` / `personal-watchlist-response-v1`。价格继续使用既有点时日线接口；状态任务时间不冒充行情日期。页面按 20 项分页，仅查询当前页的真实日线。

## 启动与更新

先执行 server migration 012，再使用与应用相同版本的 `kunlun-data-worker:local` 镜像：

```text
docker compose -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.apps.yml -f infra/docker/docker-compose.v1.yml --env-file infra/docker/.env --profile real-market-data up -d watchlist-market-data-sync
```

任务读取服务端已保存代码，每 60 秒发现新增项；上海时间每日 09:00 后更新既有项。沿用 AKShare 1.18.94、不可变 raw、Decimal 标准化、ClickHouse 日线与持久检查点。个人自选的采集状态和检查点独立于原有样本概览。默认回溯 730 天；空响应明确标记 `EMPTY`。同代码通过数据库锁隔离并发；失败逐项隔离，每天最多尝试三次且间隔至少一小时。重启复用检查点，失败保留最近成功时间和已入库历史。

进程使用既有 PostgreSQL/ClickHouse 环境配置和 raw volume，密钥只由环境注入，不输出个人代码、名称或账号。数据库不可用时记录脱敏错误并等待下次检查；单项来源、验证或存储失败按对应错误码显示。健康排查先看容器是否运行、最近聚合进度、数据库状态与实际 bars 查询，不将容器存活等同于行情成功。

## 支持边界

沪深北股票、指数、ETF 和 LOF 使用未复权日线，供研究参考；LOF 使用独立 `lof-v1` 标准化版本，暂不开放分钟行情。港股、新三板和上金所引用保存在服务端并明确标为未接入，不转换成 A 股标识，不产生订单。行情缺失、停牌、陈旧日期和源错误须如实展示；已有行情不代表主数据生命周期或所有研究字段均已覆盖。

停止只需停止 `watchlist-market-data-sync`；不删除自选和日线。迁移为新增表，备份当前数据库后执行；重复执行跳过已应用版本。回退应用时保留这些表及 raw 数据，避免丢失已导入自选，不通过删表回退。
