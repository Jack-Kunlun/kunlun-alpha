# 研究数据集

P5-N05 的研究数据集由 `feature-core.datasets.DatasetExporter` 生成。该目录只保留
说明文件；实际 Parquet、manifest 和命令文件属于可重建产物，不进入 Git。

每个数据集固定包含：

- `dataset-manifest.json`：数据集版本、创建时间、TRAIN/EVALUATION 分区、完整
  point-in-time 查询、来源 lineage、语义哈希、Parquet 文件哈希、schema 指纹和
  argv 形式的重建命令；
- `rebuild-command.json`：跨平台 argv 与便于人工阅读的命令文本，不得包含凭据；
- `partitions/train/*.parquet` 与 `partitions/evaluation/*.parquet`：角色写入文件
  metadata 和每一行；每行同时保存该来源查询的 `decision_time` cutoff，消费端不得
  仅按目录名推断角色，也不得把 `event_time` 当作决策时点。

## 生成与重建

调用方构造 `DatasetExportRequest`，为每个分区提供一个或多个
`DatasetSourceSpec`。导出器通过 P5-N04 `FeatureHistoryRepository.query_as_of`
读取数据。`as_of` 的契约含义是该来源所有样本的 `decision_time`，导出器会再次
验证 `available_time <= as_of` 且 `processing_time <= as_of`，并把 cutoff 写入每
一行。事件时点实验必须按真实决策时点拆分 source，不得用事后统一快照冒充历史
可见数据。同一特征和实体的训练、评测时间窗有
交集时，请求在写文件前失败。TRAIN 与 EVALUATION 还执行更严格的样本级隔离：
只要实体与事件时间窗重叠，即使特征版本或 fingerprint 不同，也拒绝导出。

```python
manifest = exporter.export(request, output_root)
rebuilt = exporter.rebuild(manifest, clean_output_root)
exporter.verify(rebuilt, clean_output_root / request.dataset_name / request.dataset_version)
```

重建必须使用清空的新输出根目录。`rebuild` 会重新执行 manifest 中的来源查询，
并要求 manifest checksum 和每个 Parquet 文件 checksum 完全一致；来源发生修订
时不会覆盖旧数据集，而是失败并要求创建新的数据集版本。

命令行入口为 `research/datasets/rebuild.py`。manifest 只接受固定的结构化 argv：
`uv run --package feature-core python research/datasets/rebuild.py --manifest
dataset-manifest.json --output <relative-path> --repository-profile
<profile>`。manifest 仅保存不可执行的 profile 标识。执行机器通过
`KUNLUN_DATASET_REPOSITORY_PROFILES` JSON 对象把 profile allowlist 映射到
`module.path:function`；factory 无参数并返回 `FeatureHistoryRepository`，负责从
环境或密钥存储建立数据连接。factory 路径、DSN 和凭据没有 argv 字段，不得进入
manifest。`rebuild-command.json` 必须由 manifest
精确派生，验证时会拒绝缺失、篡改、额外文件和符号链接。

PyArrow 固定为 `25.0.1`。写入参数、UTC 微秒时间戳、Zstandard 压缩、行排序和
schema 均固定。当前证据只保证同一平台和 writer 版本下文件哈希可复现；尚未建立
跨 OS 工件对比门禁，因此不承诺 Windows、macOS 和 Linux 的 Parquet 文件哈希或
规范化语义哈希相同。

## 禁止项

- 不提交生成的 Parquet 或私有原始数据；
- 不在 manifest 或重建命令中保存 DSN、token、cookie、密码或账户信息；
- 不把 EVALUATION 行并入 TRAIN，也不复用交叉的来源时间窗；
- 不因来源修订而改写旧 manifest 或文件。
