# 跨 Agent 共享资料库 Asset Library 设计归档

日期：2026-07-03

状态：设计归档 / 待独立 Agent 接管

当前来源对话：Agent06 资料库功能开发与发布验收

## 1. 核心结论

当前在 Agent06 内完成的资料库能力，只是 V0 级原型：

- 保存问答结果
- 查看资料列表和详情
- 导出 Word / PPT
- 删除资料
- 明确不自动进入知识库

但这个能力不应该长期依附在 Agent06 下。它的真实边界应升级为整个 Agent 系统共享的资料资产层：

```text
Shared Agent Asset Library
```

它应作为跨 Agent 的统一资料库，集中管理 Agent02、Agent03、Agent05、Agent06 等工作流生成的报告、处置单、问答结果、PPT、导出文档、附件和后续可复用素材。

## 2. 第一性原理

资料库要解决的问题不是“把文件存起来”，而是：

1. Agent 生成的有价值结果不能只停留在一次性页面输出。
2. 用户需要在未来重新找到、复用、导出、删除或整理这些结果。
3. 资料可以长期保存，但不等于应该自动进入 RAG 知识库。
4. 不同 Agent 的输出类型不同，但都需要统一资产登记、检索和治理。
5. 资料库必须防止演变成不可搜索、不可管理、不可审计的历史垃圾堆。

因此需要区分三层：

```text
Asset Library      保存、管理、检索、导出、删除资料资产
Knowledge Base     经用户确认后进入 RAG / 语义检索
Workflow Ledger    记录某次 Agent 工作流产生了什么资产
```

## 3. 与知识库的硬边界

资料库不是知识库。

资料库负责：

- 本地持久化
- 统一 manifest
- 资产列表
- 详情查看
- 标签、分类、收藏、归档
- 全文搜索
- 文件导出
- 删除和审计
- 资产跨 Agent 管理

知识库负责：

- 被模型检索和引用
- RAG 索引
- 向量化
- 引用证据链
- 可回答性约束

任何资产进入知识库必须显式触发，不允许因为“保存到资料库”而自动进入知识库。

建议状态字段：

```text
knowledge_status:
  - not_indexed
  - candidate
  - indexed
  - rejected
  - removed
```

## 4. 需要覆盖的 Agent 场景

### Agent02

当前问题：

- 合资 / 外资分析报告多数是一次性生成。
- 输出结果没有统一保存。
- 后续复盘、对比、周报复用不方便。

应保存的资产：

- 外资合资分析报告
- 周期性市场分析
- 品牌 / 车型专题报告
- 导出的 Word / PPT / PDF
- 生成报告所用的关键输入摘要

示例类型：

```text
asset_type: agent02_market_report
agent_id: agent02
workflow_id: foreign_jv_china_watch
```

### Agent03

当前问题：

- 馒头健康控制平台的分析、处置建议、观察记录具有长期价值。
- 宠物健康资料天然需要按时间、症状、检查、处置、复诊记录管理。

应保存的资产：

- 馒头健康分析报告
- 单次问诊 / 观察记录
- 化验单解释结果
- 处置建议
- 后续追踪记录
- 图片 / PDF / 附件引用

示例类型：

```text
asset_type: agent03_mcht_case
agent_id: agent03
workflow_id: mantou_health_control
subject_id: mantou
```

### Agent06

当前 V0 已覆盖：

- 问答结果保存
- 资料列表 / 详情
- Word / PPT 导出
- 删除

未来应转为共享资料库的一个生产者，而不是资料库唯一宿主。

示例类型：

```text
asset_type: pka_answer
agent_id: agent06
workflow_id: ask
```

### Agent05

未来可接入：

- PPT 生成结果
- PPT 模板版本
- PPT 导出记录
- 来源报告和素材引用

示例类型：

```text
asset_type: ppt_deck
agent_id: agent05
workflow_id: ppt_generation
```

## 5. 统一资产 Manifest 草案

每条资产应有统一 manifest。不同 Agent 可扩展局部字段，但核心字段必须一致。

```json
{
  "asset_id": "ast_20260703_xxxxxx",
  "agent_id": "agent06",
  "workflow_id": "ask",
  "asset_type": "pka_answer",
  "title": "资料标题",
  "summary": "面向列表和搜索的短摘要",
  "created_at": "2026-07-03T20:00:00",
  "updated_at": "2026-07-03T20:00:00",
  "status": "active",
  "knowledge_status": "not_indexed",
  "source_status": "grounded",
  "tags": [],
  "collections": [],
  "favorite": false,
  "agent_context": {
    "subject_id": "",
    "project_id": "",
    "workflow_run_id": ""
  },
  "files": [
    {
      "role": "primary_markdown",
      "path": "assets/agent06/2026-07-03/ast_x/answer.md",
      "media_type": "text/markdown"
    }
  ],
  "exports": [],
  "provenance": {
    "input_refs": [],
    "source_refs": [],
    "model_route": "",
    "created_by": "agent"
  },
  "governance": {
    "delete_status": "active",
    "retention_policy": "manual",
    "sensitivity": "normal"
  }
}
```

## 6. 存储建议

V1 不应直接引入重型 DMS。建议继续采用 file-first 底座，但把索引和管理能力补齐。

建议结构：

```text
PKA_Data/
  shared_assets/
    manifests/
      2026/
        07/
          ast_*.json
    files/
      agent02/
      agent03/
      agent05/
      agent06/
    exports/
    index/
      assets.sqlite3
```

文件系统负责：

- 原始内容
- Markdown
- 导出文件
- 附件

SQLite 负责：

- 列表查询
- 标签
- 搜索索引
- agent / workflow 筛选
- 删除状态
- 统计

后续可用 SQLite FTS5 做本地全文搜索。

## 7. 控制 / 配置界面

共享资料库应有自己的控制和配置界面，不应藏在 Agent06 内。

建议在 Web 发布页形成统一入口：

```text
http://127.0.0.1:3000/assets
```

或在 Agent00 / 发布中心增加“资料中心”模块。

基础页面应支持：

- 全部资料列表
- 按 Agent 筛选
- 按 workflow 筛选
- 按类型筛选
- 搜索
- 标签筛选
- 收藏 / 归档
- 删除
- 详情查看
- 导出
- 查看来源 Agent
- 查看是否进入知识库
- 从资料库显式加入知识库

配置界面应支持：

- 存储目录
- 每类资产保留策略
- 导出历史保留数量
- 默认是否全文索引
- 是否允许某 Agent 写入资料库
- 敏感资产类型隔离策略
- 搜索索引重建

## 8. 外部产品和工具参考

这些不是硬性依赖，只是经过验证的产品模式来源。选型原则是功能适配优先。

### Obsidian

适合作为产品交互参考：

- 本地文件优先
- Markdown 可迁移
- 标签
- 双链
- 搜索
- 资料和知识之间的过渡体验

限制：

- 不是开源核心产品
- 不适合作为直接嵌入依赖

### TagSpaces

适合作为本地资料管理参考：

- 本地文件
- 标签化
- 无云依赖
- 文件可迁移

适合借鉴“本地资料库”的组织方式。

### paperless-ngx

适合作为正式文档管理系统参考：

- 文档消费目录
- OCR
- 标签
- 文档类型
- 自定义字段
- 全文搜索
- 自动分类

限制：

- 系统较重
- 不建议直接嵌入 Agent 系统
- 更适合作为 DMS 能力模型参考

### Logseq

适合作为知识组织参考：

- 本地优先
- 双链
- 图谱
- block 级组织

限制：

- 更偏知识笔记，不是文件资料治理系统

### 搜索技术候选

可进一步评估：

- SQLite FTS5
- Tantivy
- MiniSearch / Lunr
- ripgrep 式文件搜索

V1 首选 SQLite FTS5，因为当前系统已有 Python / SQLite / 本地文件基础，集成成本低。

## 9. 不建议的方向

不建议把完整 Obsidian / paperless-ngx / Mayan EDMS 直接塞进当前 Agent 系统。

原因：

- 控制权不清晰
- 部署复杂度上升
- 与现有 Agent 工作流边界不一致
- 难以统一 agent_id / workflow_id / provenance
- 后续“加入知识库”边界更难管控

更合适的方式是：

```text
借鉴成熟工具的产品模式
保留本地 file-first 可迁移存储
用轻量索引和统一 manifest 建自己的共享资料库
```

## 10. 推荐 V1 分期

### Phase 1: 共享资产契约

目标：

- 定义统一 manifest schema
- 定义 asset_id 规则
- 定义 agent_id / workflow_id / asset_type 枚举
- 定义写入 API
- 兼容 Agent06 当前 V0 数据

交付：

- 设计文档
- schema
- 单元测试
- 迁移兼容策略

### Phase 2: 共享资料库服务

目标：

- 从 Agent06 局部服务抽离为共享 Asset Library 服务
- 支持 Agent02 / Agent03 / Agent06 写入
- 支持 list / read / delete / export / update metadata

交付：

- API
- 存储层
- SQLite 索引
- 安全校验

### Phase 3: Web 发布页资料中心

目标：

- 在 3000 发布页增加统一资料中心
- 跨 Agent 浏览资料
- 按 Agent / 类型 / 标签筛选
- 删除 / 收藏 / 归档 / 导出

交付：

- Web UI
- 代理路由
- 端到端验收

### Phase 4: 搜索与复用

目标：

- 全文搜索
- 标签管理
- 资料组合
- 从资料生成报告 / PPT

交付：

- SQLite FTS5
- 搜索 UI
- 批量选择
- 复用动作

### Phase 5: 知识库桥接

目标：

- 从资料库显式加入知识库
- 提供确认卡
- 标记 knowledge_status
- 防止自动污染 RAG

交付：

- 加入知识库接口
- 审计状态
- 回滚 / 移除索引策略

## 11. 当前 Agent06 V0 的定位

当前 Agent06 V0 资料库不是废弃工作，而是共享资料库的原型验证：

- 证明了 file-first manifest 可行
- 证明了保存 / 列表 / 详情 / 删除 / 导出闭环可行
- 证明了“保存资料”与“加入知识库”必须隔离
- 证明了发布页可通过 3000 代理统一访问

后续独立 Agent 应继承这些经验，但不要把最终资料库边界锁死在 Agent06。

## 12. 给新 Agent 的启动指令建议

新对话可使用：

```text
请静默读取并完全理解当前目录下的 docs/shared-agent-asset-library-archive-20260703.md。
本对话逻辑分支锁定为：【跨 Agent 共享资料库】。
在执行任何操作前，请简要复述：
1. 当前 Agent06 V0 资料库已经完成了什么；
2. 为什么资料库应升级为跨 Agent 共享资产层；
3. 下一步应先做哪些设计决策。
等待我确认后，再开始设计或开发。
```

## 13. 最终判断

共享资料库应成为 Agent 系统的基础能力之一。

它不应该是 Agent06 的附属页面，也不应该只是保存按钮的后端目录。

它应该是：

```text
所有 Agent 产出资料的统一资产管理层
```

并通过 Web 发布页提供统一控制、配置、检索、删除、导出和知识库桥接能力。
