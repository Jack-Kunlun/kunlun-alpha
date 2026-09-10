# 行情拒绝与过滤证据

## 交付边界

本切片已通过定向离线、隔离 HTTP 验证和独立代码安全审核。现有本地 `docker` 项目
已接入独立公开卷，离线发布 14 条已有 FILTERED 证据，并通过已认证页面的列表、
组合筛选、详情和长明细分页验收；未启动行情采集或数据库迁移。
部署与剩余边界见[公开证据原位启用记录](../reviews/2026-09-05-public-quality-runtime-enablement.md)。

仅接入采集端已经记录的 `REJECTED` / `FILTERED` 证据，不反推被拒绝行情的价格，
不提供原始文件下载，不推断缺失交易日、来源价格差异或全市场完整性。
基金质量事件与日线入库概览保持各自独立的查询语义。

## 权限边界

经批准的运行方案是一个独立脱敏卷：采集端可写，API 服务只读。
API 不得挂载原始行情卷，即使只读也不允许；数据库、网络和凭据权限保持不变。
`MARKET_DATA_QUALITY_PUBLIC_ROOT` 是可选配置，未配置时保持既有采集行为，
API 必须明确返回证据不可用，不能以空列表冒充已发布快照。

离线导出仅由采集端读取质量文件与 manifest 元数据索引，不读取原始 object 内容，
不调用行情源、不写入 Bar、不做数据库迁移。原始证据保持原位，不覆盖其记录时间。

启用导出时，`MARKET_DATA_RAW_ROOT` 与 `MARKET_DATA_QUALITY_PUBLIC_ROOT` 均须为绝对路径，
不得相同或互相嵌套；路径中不得包含符号链接。命令入口为 `market-quality-export`，
强制接收 `--raw-root` 和 `--public-root`。离线命令遇到缺少 `market-quality` 目录时失败，
不会擅自把缺目录解释成零条；运行采集器显式启用后，会先初始化自己的可信质量目录，
在成功采集周期结束时发布零条或已有记录。

仅查看参数帮助（不采集、不发布）：

```bash
uv run --package data-worker market-quality-export --help
```

真实目录的导出是一次写入脱敏卷的操作，不属于只读监控；独立审核与部署安排完成前，
不得对实际原始行情卷执行导出。

部署前提是采集进程是该卷唯一受信任的写入者，API 只有只读挂载，根目录和上级目录
不能被不可信主体交换或改写。非阻塞打开和文件身份复核是纵深防御，不能声称在任意
恶意并发目录替换下完全无竞态。现阶段不新增凭据、签名或额外读取权限来扩大这个边界。

### 不同运行用户的文件读取

以下权限修复已进入本地 worker 镜像并用于实际导出。worker 使用 UID 10001，API 使用 UID 1000；
只读挂载不会绕过 Unix 文件权限。POSIX 上新公开指针与快照在原子替换前设置为 `0644`，
新 public 根与 `snapshots/` 目录设置为 `0755`，写权限仍仅归 owner。权限设置失败会
中止发布；指针替换前失败保留旧指针。原始质量、manifest、object 的权限与内容不变。

已有 public 目录若不是 `0755`，或同摘要旧快照不是 `0644`，导出会明确失败，不在后台
放宽既有权限。排障须先核对目录归属、唯一 writer 与挂载范围，不能用递归 chmod
或给 API 挂 raw 卷绕过检查。Windows 不验证 POSIX mode，不能由离线通过推定 ACL 正确。

worker 镜像预建 UID/GID 10001 的公开目录，但新空 named volume 的初始化仍依赖首次
挂载者。必须先由 producer 初始化/导出并核对 owner、mode，再挂给 server；不能让
server 首次挂载空卷后就假设 worker 可写。不应为初始化公开卷启动真实行情采集。

已提供可选 `infra/docker/docker-compose.market-quality-evidence.yml`，静态配置、临时卷
及本地真实卷接线验收通过。维护现有环境时作为既有 Compose 项目的显式 overlay 合并，
不能新建第二套项目，也不能把它直接加入默认启动路径。下面仅为挂载边界示意：

```yaml
services:
  market-data-sync:
    environment:
      MARKET_DATA_QUALITY_PUBLIC_ROOT: /workspace/var/market-quality-public
    volumes:
      - kunlun-market-quality-public:/workspace/var/market-quality-public
  server:
    environment:
      MARKET_DATA_QUALITY_PUBLIC_ROOT: /workspace/var/market-quality-public
    volumes:
      - kunlun-market-quality-public:/workspace/var/market-quality-public:ro
volumes:
  kunlun-market-quality-public:
```

## 公开契约

公开记录仅包含不透明证据 ID、受支持来源、证券、周期、请求窗口、固定状态/原因码、
计数、白名单事件摘要及时间。不得包含 capture ID、raw object ID、原始校验和、请求、
原始记录、路径、自由文本原因、事件 detail 或凭据。

原始异常记录中无法合法解析的事件证券和时间转为 `null`，保留合法事件类型。
这不等于原始记录被修复；页面不应猜测这些字段。

时间含义分开：

- `captureAvailableAt`：该采集证据的可用时间。
- `qualityRecordedAt`：质量证据首次记录时间，重放不改变。
- `publishedAt`：当前脱敏快照发布时间；回填旧证据不意味着它在旧时间已经公开。

接口不提供历史 `asOf` 查询。页面按上海时区显示时间。

## 完整快照与分页

`current.json` 的 `market-quality-current-v1` 指针指向
`snapshots/<snapshotId>.json`。快照为 `market-quality-snapshot-v1`，
`snapshotId` 是快照完整 UTF-8 字节的 SHA-256，不是原始数据摘要，也不是数字签名。

先完整落盘不可变快照，再原子替换指针；提交指针前失败时保留上一份完整指针。
如果替换指针后目录同步失败，提交的持久化状态不确定，必须报告失败并重新核验，
不能声称已经回滚。原子替换保证不会读到半个指针，不等于跨卷事务。
本切片不清理旧快照，避免正在翻页的读者失去固定版本。
快照上限为 10,000 条、8 MiB；超限时发布失败，不静默截断。
快照反映本次受限扫描可见的完整文件集合；它不是对持续写入中的整个原始目录树建立
数据库式事务快照。源文件身份与摘要绑定用于发现错配和损坏，不能防止拥有原始卷
写权限的主体伪造一组自洽数据；本切片不新增签名或凭据体系。

列表和明细响应版本为 `market-quality-evidence-v1`。列表第一页可读取 current，
后续页与明细显式携带返回的 `snapshotId`。更改筛选时重置分页和快照选择。
日期筛选针对采集请求窗口的交集，不等同于行情交易日或异常记录日期。

## 故障处理原则

- 尚无发布指针：证据不可用，不表示没有拒绝记录。
- 完整快照为零：仅表示该次完整导出没有记录，不证明采集覆盖完整。
- 筛选结果为零：仅表示当前快照没有匹配记录。
- 损坏、摘要不符、非法字段、非法路径、符号链接、非普通文件或容量超限：失败关闭，
  不回显文件内容或底层错误，不把失败转换为空成功。
- 原始质量文件保存成功、公开发布失败：保留原始证据，后续重放重试导出；
  启用导出时，`FILTERED` 发布失败必须阻止随后写入 Bar。

排障只能报告受控状态和计数，不得把原始质量 JSON、manifest、令牌或异常堆栈贴入日志。
遇到损坏或超限，不得删除文件来使发布变绿；先保留证据并核实原因。

## 运行验收与后续维护

此次独立审核后仅更新了既有 Compose 项目的 server 挂载，没有部署第二套环境。
导出器只读 raw、写 public；API 只读 public，未得到 raw/index/object 读取权限。
已有 14 条实际证据不足顶层两页；已验证固定快照下的详情分页，不据此宣称并发换页验收。
不得为验证公开证据制造或写入假行情到现有数据库。

本次不修改、启动或关闭任何纸面交易墙钟门禁，也不新增真实下单能力。

实现及验证记录见[行情拒绝证据交付记录](../reviews/2026-09-05-market-quality-evidence-implementation.md)。
