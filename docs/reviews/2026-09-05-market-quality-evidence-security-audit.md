# 行情质量公开证据独立代码安全审核

## 结论

本轮由独立 Terra Max 对 `e2254ce` 的公开证据生产、读取与查询边界进行只读审查。
在文档约定的“唯一受信任写入者、API 只读、父目录不可被不可信主体改写”前提下，
未发现代码层阻断项；独立代码安全审核这一项可关闭。

这不是运行启用批准。实际卷挂载、用户认证和真实快照请求验收未执行，功能仍未部署。
此前实现记录中的审核名额限制是历史状态，本记录追加后续审核结果，不改写历史测试证据。

## 审核范围与证据

- `services/data-worker/src/data_worker/jobs/market_data/quality_projection.py`：
  白名单构造不公开原始 capture/object ID、checksum、raw records、自由文本原因及 detail。
- 同目录 `quality_export.py`：校验根目录、普通文件与容量，绑定 manifest 元数据，
  先发布内容寻址快照，再原子更新指针。公开目录不可与原始目录重叠。
- `apps/server/src/modules/data-quality/market-quality-evidence.reader.ts` 和
  `market-quality-evidence.query.ts`：校验路径组件、文件身份、容量、digest、完整 schema 与
  语义；输入 ID 不直接成为文件路径，错误受控返回。
- `apps/server/src/modules/auth/auth.module.ts`、`auth.guard.ts` 与 `apps/server/src/app.module.ts`：
  实际应用导入全局认证守卫；内部 AllowAll authorizer 不绕过会话认证。
- `infra/docker/docker-compose.apps.yml`：现有 server 无原始行情卷挂载，未启用公开证据根。
- `services/data-worker/tests/test_market_data_collector.py`：已有故障测试覆盖 FILTERED
  公开快照发布失败阻止后续 Bar 写入。

审核执行 `git show --check e2254ce`，无补丁格式错误；进行少量本地解析兼容性探测，
未重新执行整套定向测试。主代理核对受审 producer/reader 文件没有后续未提交改动。
实现阶段的定向测试与跨语言验证仍见原实现记录，不能将此次代码审核表述为新的全套测试。

## 风险与运行前待办

1. 不是针对恶意挂载管理员或目录替换攻击者的完整 fd-relative `openat` 保证。
   运行部署必须验证受信任父目录、唯一 writer、只读 server 的前提。
2. 10,000 条扫描预算包含 manifest-index 条目。高频或分钟采集达到上限将失败关闭，
   未来可能需要单独的索引读取/保留策略设计，不能随意放宽预算或删除真实证据。
3. 启用前仍需实际核验 server 仅有公开卷只读权限、不能访问 raw/index/object，
   producer 是唯一写入者，目录所有权和父目录权限正确。
4. 按运行手册对真实发布快照执行认证列表、明细、固定快照分页及拒绝访问验收。

本次未访问凭据、真实原始数据或数据库；未部署、挂载、回填、修改运行进程或启动门禁。
