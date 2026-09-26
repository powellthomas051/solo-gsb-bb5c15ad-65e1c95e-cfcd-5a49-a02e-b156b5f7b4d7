# 古籍残页转写拼接 API

- **`POST /api/align`**：提交两段含 `?`（未辨认字）的转写文本，将**左段后缀与右段前缀**做最优重叠对齐，
返回最高分对齐的原文区间、逐列对齐和拼接文本。
- **`POST /api/assemble`**：提交按阅读顺序排列的 **2～5 段**转写（每段最长 500 字、总长最长 800 字），
逐段复用上述后缀-前缀对齐完成拼接，返回最终文本与**逐字来源列表**。
- **`POST /api/collate`**：沿用 `/api/assemble` 的 `segments` 限制与续接门槛，复用其拼接文本和逐字来源，
逐位置回查各原始段原字、以**原始段为投票单位**汇总异文，供校勘人员复核（只给建议，不改写文本）。
- **`POST /api/order`**：提交 **2～4 段未排序**转写（每段不超过 100 字、总长不超过 240 字），
**穷举全部排列**，每一步把当前拼接文本与下一原段交给现有对齐逻辑、沿用同一续接门槛，**累计各步对齐得分**
选出累计分最高的完整顺序，返回**原输入下标顺序**、拼接文本与按原输入下标标记的逐字来源；最高分并列返回
**409**（含全部并列顺序），无完整顺序返回 **422**。
- **`POST /api/revise`**：提交与 `/api/assemble` 相同的有序 `segments` 及人工校订 `edits`
（每项含原始段序号 `segment`、原文下标 `pos`、替换字 `char`，`char` 为单个非 `?` 字符），
先复用拼接得到文本与逐字来源，再沿逐字来源把每项校订定位到拼接文本位置落实改字；
重叠段指向同一位置的相同改字**合并**，不同改字返回 **409**（列出冲突位置与校订项），
段序号/下标越界或坐标无法唯一定位返回 **422**；返回修订后文本、沿用的逐字来源与逐位置 `changes`。
- **`POST /api/locate-quote`**：提交与 `/api/assemble` 相同的有序 `segments` 及 1～80 字引文 `quote`，
在拼接文本中以逐字编辑代价（相同字或任一侧 `?` 代价 **0**，替换/插入/删除各代价 **1**）查找引文位置；
最小代价不超过 **2** 且区间唯一时返回**左闭右开区间**、原文片段、代价与该区间逐字 `sources`，
多个不同区间并列返回 **409**（列出全部并列区间），无合格区间返回 **422**；只定位、不改写拼接文本。
- **`POST /api/locate-quotes`**：提交与 `/api/assemble` 相同的有序 `segments` 及 **2～4 段按原文顺序
排列**的引文 `quotes`（各 1～80 字），为每段引文枚举编辑代价不超过 **2** 的全部非空区间，再选出区间
按序且**互不重叠**、总代价最低的**完整定位链**（即使某段单独最低代价的候选无法接入完整链，也会考虑
该段其余合格候选）；唯一最优链返回各引文区间、片段、代价与 `sources`，多个不同最优链并列返回 **409**
（给出两条不同最优链），无完整链返回 **422**。
- **`POST /api/find-repetition`**：提交与 `/api/assemble` 相同的有序 `segments`，先复用其拼接文本与
逐字来源，再在同一拼接文本中寻找两个**互不重叠的等长连续区间**：逐字相同或任一字为 `?` 即兼容，
区间长度至少 **6** 且至少 **4** 个位置两侧已知字相同；按长度最长、同长度已知相同位更多、再按两起点
升序取首对，返回两个左闭右开区间及各自原文与逐字 `sources`；无合格重复时 `repeat` 为 `null`。
- **`POST /api/audit-omission`**：提交与 `/api/assemble` 相同的有序 `segments` 及一段独立参照转写
`reference`（最长 **840** 字，须比拼接稿恰好多 **1～40** 字），复用拼接文本与逐字来源，只在
**段间接缝**（左字含某原始段、右字不含该段而含更晚原始段的相邻位置）枚举补入参照稿连续缺文后两稿
逐位对齐（相同字或任一侧 `?` 记 **0**、已知异字记 **1**，整稿异字数最多 **2**）的方案；唯一方案返回
插入位置、缺文字串、异字数及接缝两侧 `sources`，不同缺文位置并列返回 **409**，无合格方案返回 **422**；
结果仅供人工复核，**不改写拼接稿**。
- **`POST /api/compare-editions`**：提交 `left_segments`、`right_segments` 两组各 **2～5 段**转写，各自
沿用 `/api/assemble` 的段数、长度限制与续接门槛**分别拼接**；返回的**版本文本**沿用其逐字来源，但
**保留前段被同侧后段已知字续接覆盖的 `?`**（不改写为补字），再对两份保留 `?` 的版本文本做
**全局逐字最小编辑对齐**（相同字或任一侧 `?` 代价 **0**，替换/插入/删除各代价 **1**）；同分路径按
**对角 → 删除左字 → 插入右字**固定择优，`ambiguous` 标记是否存在多条最优路径；把**连续非零代价列**
合并为差异块，返回两侧左闭右开区间、原文与逐字 `sources`、`total_cost` 及 `ambiguous`；两份稿子
完全一致（或仅差 `?`）时差异块为空。
- **`POST /api/trace-reading`**：提交与 `/api/assemble` 相同的有序 `segments` 及拼接稿上一个**左闭右开**
区间 `start`、`end`，复用其拼接文本和逐字 `sources`，为区间逐字选一个原始段来源作为证据：
**原字等于输出字或为 `?` 才可作该字证据**；**同段连续取字的原文下标必须逐次加一**；**换段仅可发生在
交界两侧至少一字同时携带换前段、换后段来源处**。为整个区间求证据路径，依次**最小化换段次数**与
**所选 `?` 数**，同分按**段序号、原文下标序列字典序取首**，并以 `ambiguous` 标记是否还有其他同分路径；
返回区间文本、每段路径的拼接稿及原文左闭右开区间、换段位置与所选 `?` 位置。区间非法或无完整路径
返回 **422**。
- **`POST /api/audit-transposition`**：提交与 `/api/assemble` 相同的有序 `segments` 及一段独立参照转写
`reference`（两稿须**等长**且均不超过 **120** 字，且两稿间须存在**已知字冲突**），复用拼接文本与逐字
来源，诊断**一段连续的 2～12 字被移到另一位置**的情形：枚举原稿左闭右开区间，剪下后按**剩余文本的
插入下标**放回（排除原位及重排后未改变文本的操作），逐字与参照稿比较（相同字或任一侧 `?` 算吻合，
移位片段至少 **2** 个两侧已知且相同的字），按**移位长度最短**取解；唯一解返回原区间、剪下后的插入
下标、移位文本及原区间逐字 `sources`，同长度多解返回 **409**（两种操作），无解返回 **422**；
只提示，不改写拼接稿。

## 快速开始

单条命令启动（依赖已纳入镜像构建）：

```bash
docker compose up --build
```

- **接口地址**：http://localhost:8000
- **端口**：8000
- **交互式接口文档（Swagger UI）**：http://localhost:8000/docs
- **健康检查**：http://localhost:8000/health

## 接口说明

### `POST /api/align`

请求体：

```json
{
  "left": "学而?习之",
  "right": "时习之不亦"
}
```

- `left`、`right`：必填，非空字符串（单段最长 500 字），未辨认字以 `?` 表示。

响应示例：

```json
{
  "score": 4,
  "aligned_pairs": 3,
  "left_interval": { "start": 2, "end": 5, "text": "?习之" },
  "right_interval": { "start": 0, "end": 3, "text": "时习之" },
  "left_free_prefix": "学而",
  "right_free_suffix": "不亦",
  "aligned_left": "?习之",
  "aligned_right": "时习之",
  "columns": [
    { "left_pos": 2, "left_char": "?", "right_pos": 0, "right_char": "时", "type": "wildcard", "score": 0 },
    { "left_pos": 3, "left_char": "习", "right_pos": 1, "right_char": "习", "type": "match", "score": 2 },
    { "left_pos": 4, "left_char": "之", "right_pos": 2, "right_char": "之", "type": "match", "score": 2 }
  ],
  "merged": "学而时习之不亦",
  "conflicts": [],
  "resolved_wildcards": [
    { "segment": "left", "pos": 2, "resolved_char": "时" }
  ]
}
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `score` | 最高对齐得分 |
| `aligned_pairs` | 对齐字符对数 |
| `left_interval` / `right_interval` | 左/右段参与对齐的原文区间（下标从 0 开始，左闭右开） |
| `left_free_prefix` / `right_free_suffix` | 未参与对齐、不计分的左段前缀 / 右段后缀 |
| `aligned_left` / `aligned_right` | 对齐串（空缺以 `-` 表示） |
| `columns` | 逐列对齐：`type` 为 `match`（相同字）/ `wildcard`（含 `?`）/ `mismatch`（异字）/ `gap_left`（左段空缺）/ `gap_right`（右段空缺），`score` 为本列得分 |
| `merged` | 拼接文本 |
| `conflicts` | 异字冲突列表：保留左段字，并列出双方原文位置及字形 |
| `resolved_wildcards` | `?` 补字列表：以对方已知字替换 |

调用示例：

```bash
curl -X POST http://localhost:8000/api/align \
  -H "Content-Type: application/json" \
  -d '{"left": "学而?习之", "right": "时习之不亦"}'
```

### `POST /api/assemble`

按阅读顺序逐段拼接 2～5 段转写。每一步把**当前拼接文本作为左段、下一段原始转写作为右段**，
复用 `/api/align` 的后缀-前缀对齐合并。

**续接门槛**：每一步仅在最高对齐得分 **大于 0**、且至少有 **2 对相同已知字**（`match` 列）时继续；
任一步不满足即返回 **422**，响应中给出失败段序号 `failed_segment`（从 0 开始）。整个请求为一次
纯内存计算，失败时不产生任何部分结果。

**逐字来源**：响应的 `sources` 与最终文本 `text` 等长，逐字对应；每个字保留贡献它的所有
原始段序号与原文下标（均从 0 开始）：

- 相同字：对齐双方来源都保留（多段重叠时可累积超过 2 个来源）；
- `?` 补字：`?` 一方与补字一方的来源都保留；双方皆为 `?` 时保留 `?`；
- 异字冲突：拼接保留左段字形，但冲突双方来源都保留；
- 空缺列：仅未空缺一方贡献来源。

请求体：

```json
{
  "segments": ["学而?习之", "时习之不", "之不亦乐乎"]
}
```

- `segments`：必填，2～5 个非空字符串；单段最长 500 字，各段总长最长 800 字。

响应示例：

```json
{
  "text": "学而时习之不亦乐乎",
  "sources": [
    [{ "segment": 0, "pos": 0 }],
    [{ "segment": 0, "pos": 1 }],
    [{ "segment": 0, "pos": 2 }, { "segment": 1, "pos": 0 }],
    [{ "segment": 0, "pos": 3 }, { "segment": 1, "pos": 1 }],
    [{ "segment": 0, "pos": 4 }, { "segment": 1, "pos": 2 }, { "segment": 2, "pos": 0 }],
    [{ "segment": 1, "pos": 3 }, { "segment": 2, "pos": 1 }],
    [{ "segment": 2, "pos": 2 }],
    [{ "segment": 2, "pos": 3 }],
    [{ "segment": 2, "pos": 4 }]
  ]
}
```

上例中：`时` 由第 1 段的 `?`（补字）与第 2 段的 `时` 共同贡献；`之` 由三段共同贡献。

续接失败示例（第 3 段无法与前文可靠拼接，`failed_segment` 为段序号，从 0 开始）：

```bash
curl -X POST http://localhost:8000/api/assemble \
  -H "Content-Type: application/json" \
  -d '{"segments": ["孔子曰未知", "未知生焉", "完全无关文本"]}'
```

```json
{
  "detail": {
    "message": "第 3 段（段序号 2）无法与前文可靠拼接：需要最高对齐得分 > 0 且至少 2 对相同已知字",
    "failed_segment": 2
  }
}
```

### `POST /api/collate`

供古籍校勘人员复核多份残页转写。请求体与 `/api/assemble` 完全相同（沿用其 `segments` 限制：
2～5 个非空字符串，单段最长 500 字、总长最长 800 字；续接门槛与 422 规则也一致），内部复用
`/api/assemble` 的拼接文本与逐字来源，再逐字回查所有来源原字。

**投票规则**（以**原始段为投票单位**，段序号均从 0 开始）：

- 对拼接文本的每个输出位置，经逐字来源回查各原始段在该位置的**原字**；
- 同一原始段在该位置有多个来源标记时（同段重复来源）**只计一次**；
- 原字为 `?`（未辨认字）的来源**不投票**；
- **仅保留至少有两种不同已知字的位置**（异文位置）。只有一种已知字的位置属于补字而非异文，
  不列入（例如某位置由一段的 `?` 与另一段的已知字补字而成，无候选分歧）。

**建议字**：各候选字按得票数排列，**唯一最高票**的候选作为 `suggestion`；**最高票并列**时
`suggestion` 为 `null`。接口**不自动改写**拼接文本，`text` 与 `/api/assemble` 的结果一致。

请求体：

```json
{
  "segments": ["甲乙丙丁戊己", "甲乙丙艮戊己", "甲乙丙丁戊己庚辛", "戊己康辛", "戊己康辛"]
}
```

响应示例：

```json
{
  "text": "甲乙丙丁戊己庚辛",
  "variants": [
    {
      "pos": 3,
      "current": "丁",
      "candidates": [
        { "char": "丁", "segments": [0, 2] },
        { "char": "艮", "segments": [1] }
      ],
      "suggestion": "丁"
    },
    {
      "pos": 6,
      "current": "庚",
      "candidates": [
        { "char": "康", "segments": [3, 4] },
        { "char": "庚", "segments": [2] }
      ],
      "suggestion": "康"
    }
  ]
}
```

上例中：

- 第 4 字（`pos` 3）拼接保留先出的 `丁`，段 0、2 作 `丁`（2 票）、段 1 作 `艮`（1 票），建议 `丁`；
- 第 7 字（`pos` 6）拼接文本仍是 `庚`，但后并入的段 3、4 作 `康`（2 票）压过段 2 的 `庚`（1 票），
  故**建议 `康` 而当前字为 `庚`**——是否采纳由校勘人员决定，文本不会被自动改写；
- 其余各字各段原字一致（或仅由 `?` 补字），不构成异文，不列入。

字段说明：

| 字段 | 含义 |
| --- | --- |
| `text` | 拼接文本（与 `/api/assemble` 一致，不被改写） |
| `variants[].pos` | 异文位置在拼接文本中的下标（从 0 开始） |
| `variants[].current` | 当前拼接文本在该位置的字 |
| `variants[].candidates[].char` | 候选原字（已知字） |
| `variants[].candidates[].segments` | 支持该候选字的原始段序号（升序、去重；同段重复来源只计一次，`?` 不投票） |
| `variants[].suggestion` | 建议字：唯一最高票候选；最高票并列时为 `null` |

候选按得票数降序排列；得票相同时按最小支持段序号升序排列。

并列最高票示例（`丁`、`艮` 各 1 票，建议为 `null`）：

```bash
curl -X POST http://localhost:8000/api/collate \
  -H "Content-Type: application/json" \
  -d '{"segments": ["甲乙丙丁戊己", "甲乙丙艮戊己"]}'
```

```json
{
  "text": "甲乙丙丁戊己",
  "variants": [
    {
      "pos": 3,
      "current": "丁",
      "candidates": [
        { "char": "丁", "segments": [0] },
        { "char": "艮", "segments": [1] }
      ],
      "suggestion": null
    }
  ]
}
```

补字无异文时（`?` 由已知字补入，候选不产生分歧）`variants` 为空数组：

```bash
curl -X POST http://localhost:8000/api/collate \
  -H "Content-Type: application/json" \
  -d '{"segments": ["学而?习之", "时习之"]}'
```

```json
{ "text": "学而时习之", "variants": [] }
```

续接失败时与 `/api/assemble` 一样返回 **422** 并给出 `failed_segment`（从 0 开始）。

### `POST /api/revise`

在拼接文本上落实**人工校订**。请求的 `segments` 与 `/api/assemble` 完全相同（沿用其限制与续接门槛，
失败同样返回 **422** 并给出 `failed_segment`），另附校订列表 `edits`。接口先复用 `/api/assemble`
得到拼接文本与逐字来源，再**沿逐字来源**把每项校订定位到最终文本位置落实改字：

- **定位**：每项校订给出原始段序号 `segment`、原文下标 `pos`（均从 0 开始）与替换字 `char`
  （**单个非 `?` 字符**）；接口在逐字来源中查找该坐标对应的输出位置；
- **合并**：重叠段指向**同一输出位置**且改字相同的多项校订合并为一处修改，关联校订项全部保留；
- **冲突（409）**：同一输出位置被指向**不同改字**时返回 **409**，`detail.conflicts` 列出全部
  冲突位置与校订项；
- **无法定位（422）**：段序号或原文下标越界、校订坐标未映射或映射到多个输出位置，均返回 **422**；
- **不产生部分修订**：任一环节失败即不返回任何结果；**不重新对齐**，未涉及位置保持原字，
  `sources` 沿用拼接结果不变。

请求体：

```json
{
  "segments": ["学而?习之", "时习之不", "之不亦乐乎"],
  "edits": [
    { "segment": 0, "pos": 4, "char": "知" },
    { "segment": 2, "pos": 0, "char": "知" }
  ]
}
```

- `segments`：必填，2～5 个非空字符串；单段最长 500 字，各段总长最长 800 字（同 `/api/assemble`）。
- `edits`：必填（可为空数组），每项含 `segment`、`pos`、`char` 三个字段。

调用示例：

```bash
curl -X POST http://localhost:8000/api/revise \
  -H "Content-Type: application/json" \
  -d '{"segments": ["学而?习之", "时习之不", "之不亦乐乎"], "edits": [{"segment": 0, "pos": 4, "char": "知"}, {"segment": 2, "pos": 0, "char": "知"}]}'
```

响应示例（拼接文本位置 4 的 `之` 由段 0、1、2 重叠贡献，两项校订改字相同，合并为一处修改）：

```json
{
  "text": "学而时习知不亦乐乎",
  "sources": [
    [{ "segment": 0, "pos": 0 }],
    [{ "segment": 0, "pos": 1 }],
    [{ "segment": 0, "pos": 2 }, { "segment": 1, "pos": 0 }],
    [{ "segment": 0, "pos": 3 }, { "segment": 1, "pos": 1 }],
    [{ "segment": 0, "pos": 4 }, { "segment": 1, "pos": 2 }, { "segment": 2, "pos": 0 }],
    [{ "segment": 1, "pos": 3 }, { "segment": 2, "pos": 1 }],
    [{ "segment": 2, "pos": 2 }],
    [{ "segment": 2, "pos": 3 }],
    [{ "segment": 2, "pos": 4 }]
  ],
  "changes": [
    {
      "pos": 4,
      "from_char": "之",
      "to_char": "知",
      "edits": [
        { "index": 0, "segment": 0, "pos": 4, "char": "知" },
        { "index": 1, "segment": 2, "pos": 0, "char": "知" }
      ]
    }
  ]
}
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `text` | 修订后的文本（未涉及位置保持原字） |
| `sources` | 逐字来源列表，沿用 `/api/assemble` 的拼接结果，不重新对齐 |
| `changes[].pos` | 修订位置在拼接文本中的下标（从 0 开始），按位置升序 |
| `changes[].from_char` | 原字（修订前拼接文本在该位置的字） |
| `changes[].to_char` | 新字（校订落实后的字） |
| `changes[].edits[]` | 关联校订项：`index` 为该校订在请求 `edits` 中的下标（从 0 开始），其余字段原样回显 |

**改字冲突（409）**示例——段 0 的 `之`（下标 4）与段 1 的 `之`（下标 2）经重叠对齐指向同一
输出位置，两项校订改字不同：

```bash
curl -X POST http://localhost:8000/api/revise \
  -H "Content-Type: application/json" \
  -d '{"segments": ["学而?习之", "时习之不", "之不亦乐乎"], "edits": [{"segment": 0, "pos": 4, "char": "甲"}, {"segment": 1, "pos": 2, "char": "乙"}]}'
```

```json
{
  "detail": {
    "message": "校订冲突：输出位置 4 被多项校订指向不同改字，无法落实修订",
    "conflicts": [
      {
        "pos": 4,
        "edits": [
          { "index": 0, "segment": 0, "pos": 4, "char": "甲" },
          { "index": 1, "segment": 1, "pos": 2, "char": "乙" }
        ]
      }
    ]
  }
}
```

**坐标越界（422）**示例——段序号或原文下标超出范围（坐标未映射或映射到多个输出位置同样返回 422）：

```json
{
  "detail": {
    "message": "第 1 项校订的段序号 5 越界：共 3 段（段序号 0～2）"
  }
}
```

替换字为 `?`、替换字不是单个字符、`segment`/`pos` 为负数或缺字段等参数不合法情况同样返回 **422**。
续接失败时与 `/api/assemble` 一样返回 **422** 并给出 `failed_segment`（从 0 开始）。

### `POST /api/order`

当残页转写的**先后顺序未知**时，提交 2～4 段未排序文本，由接口穷举可行阅读顺序：

- **穷举全部排列**（至多 4! = 24 种），对每个排列逐段拼接：每一步把**当前拼接文本作为左段、下一原段作为右段**
  交给 `/api/align` 的后缀-前缀对齐，沿用 `/api/assemble` 的**续接门槛**（最高对齐得分 **> 0** 且至少
  **2 对相同已知字**）；任一步不满足即废弃该排列（不报错，继续尝试其余排列）；
- 每个完整顺序的总分 = **各步对齐得分的累计**（链式拼接的整体质量），**不是**原段两两相似度的简单排序；
- 取累计得分最高的完整顺序，返回**原输入下标顺序** `order`、累计 `score`、拼接文本 `text` 及与文本等长、
  按**原输入下标**标记的逐字来源 `sources`（拼接与来源规则与 `/api/assemble` 完全一致）；
- **最高分并列**时返回 **409**，`detail.ties` 给出全部并列顺序（按下标顺序字典序排列），各带完整
  `order` / `score` / `text` / `sources`，由人工裁定；
- **没有任何完整顺序**（所有排列都在某一步断链）时返回 **422**。

请求体：

```json
{
  "segments": ["之不亦乐乎", "学而?习之", "时习之不"]
}
```

- `segments`：必填，**2～4** 个非空字符串；单段最长 **100** 字，各段总长最长 **240** 字。

调用示例：

```bash
curl -X POST http://localhost:8000/api/order \
  -H "Content-Type: application/json" \
  -d '{"segments": ["之不亦乐乎", "学而?习之", "时习之不"]}'
```

响应示例（原下标顺序 `[1, 2, 0]`，即第 2 段 → 第 3 段 → 第 1 段；累计得分 8 = 4 + 4）：

```json
{
  "order": [1, 2, 0],
  "score": 8,
  "text": "学而时习之不亦乐乎",
  "sources": [
    [{ "segment": 1, "pos": 0 }],
    [{ "segment": 1, "pos": 1 }],
    [{ "segment": 1, "pos": 2 }, { "segment": 2, "pos": 0 }],
    [{ "segment": 1, "pos": 3 }, { "segment": 2, "pos": 1 }],
    [{ "segment": 0, "pos": 0 }, { "segment": 1, "pos": 4 }, { "segment": 2, "pos": 2 }],
    [{ "segment": 0, "pos": 1 }, { "segment": 2, "pos": 3 }],
    [{ "segment": 0, "pos": 2 }],
    [{ "segment": 0, "pos": 3 }],
    [{ "segment": 0, "pos": 4 }]
  ]
}
```

注意 `sources` 中的 `segment` 始终是**原输入下标**（而非阅读次序中的位次）：上例拼接首段其实是
输入的第 2 段，故首字来源标记为 `{"segment": 1, ...}`。

**最高分并列（409）**示例——两段转写完全相同时，先并哪一段累计分相同，接口不擅自选择：

```bash
curl -X POST http://localhost:8000/api/order \
  -H "Content-Type: application/json" \
  -d '{"segments": ["甲乙丙丁", "丙丁戊", "丙丁戊"]}'
```

```json
{
  "detail": {
    "message": "最高累计得分 10 的完整顺序有 2 个并列，无法唯一确定阅读顺序",
    "score": 10,
    "ties": [
      { "order": [0, 1, 2], "score": 10, "text": "甲乙丙丁戊", "sources": [ "…" ] },
      { "order": [0, 2, 1], "score": 10, "text": "甲乙丙丁戊", "sources": [ "…" ] }
    ]
  }
}
```

**无完整顺序（422）**示例——任意排列都无法在每一步同时满足得分 > 0 与至少 2 对相同已知字：

```bash
curl -X POST http://localhost:8000/api/order \
  -H "Content-Type: application/json" \
  -d '{"segments": ["孔子曰未知", "完全无关文本甲", "另一无关内容乙"]}'
```

```json
{
  "detail": {
    "message": "没有任何排列能通过续接门槛（每步最高对齐得分 > 0 且至少 2 对相同已知字），无法确定完整阅读顺序"
  }
}
```

请求参数不合法（段数不在 2～4、单段超 100 字、总长超 240 字、含空段、缺字段）同样返回 **422**。

### `POST /api/locate-quote`

在拼接文本中**定位一段引文**。请求的 `segments` 与 `/api/assemble` 完全相同（沿用 2～5 段、单段最长
500 字、总长最长 800 字的限制与续接门槛，续接失败同样返回 **422** 并给出 `failed_segment`），另附
**1～80 字**的引文 `quote`（未辨认字也以 `?` 表示）。接口先复用 `/api/assemble` 得到拼接文本与逐字
来源，再把引文与拼接文本的**任意非空连续区间**比较，按逐字编辑代价寻找最接近的区间：

- 两字**相同**代价 **0**；**任一侧为 `?`**（未辨认字）的字符对代价也是 **0**；
- **替换**（双方均为已知字且不同）、**插入**（区间比引文多字）、**删除**（区间比引文少字）各代价 **1**；
- 区间起点、终点都自由（区间之前的拼接文本前缀、引文消耗完之后的区间后缀不产生删除/插入代价），
  但引文必须**完全消耗**、区间至少包含一个拼接字符；
- **仅接受最小代价不超过 2 的区间**。最小代价由多个**不同区间**并列取得时返回 **409**，
  `detail.ties` 按 `(start, end)` 升序列出全部并列区间（各带原文片段 `fragment`、`cost` 与该区间
  逐字 `sources`）；最小代价大于 2、无合格区间时返回 **422**。
- 接口**只做定位，不改写拼接文本**；唯一命中时返回左闭右开区间 `[start, end)`、原文片段 `fragment`、
  代价 `cost` 与该区间的逐字 `sources`（与 `fragment` 等长，规则同 `/api/assemble`），并回显
  完整拼接文本 `text` 与原文 `quote`。

请求体：

```json
{
  "segments": ["学而?习之", "时习之不", "之不亦乐乎"],
  "quote": "时习之"
}
```

- `segments`：必填，2～5 个非空字符串；单段最长 500 字，各段总长最长 800 字（同 `/api/assemble`）。
- `quote`：必填，**1～80** 字的非空字符串。

调用示例：

```bash
curl -X POST http://localhost:8000/api/locate-quote \
  -H "Content-Type: application/json" \
  -d '{"segments": ["学而?习之", "时习之不", "之不亦乐乎"], "quote": "时习之"}'
```

响应示例（拼接文本 `学而时习之不亦乐乎` 中，引文 `时习之` 代价 0 唯一命中区间 `[2, 5)`）：

```json
{
  "text": "学而时习之不亦乐乎",
  "quote": "时习之",
  "start": 2,
  "end": 5,
  "fragment": "时习之",
  "cost": 0,
  "sources": [
    [{ "segment": 0, "pos": 2 }, { "segment": 1, "pos": 0 }],
    [{ "segment": 0, "pos": 3 }, { "segment": 1, "pos": 1 }],
    [{ "segment": 0, "pos": 4 }, { "segment": 1, "pos": 2 }, { "segment": 2, "pos": 0 }]
  ]
}
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `text` | 拼接文本（与 `/api/assemble` 一致，不被改写） |
| `quote` | 原样回显的引文 |
| `start` / `end` | 命中区间在拼接文本中的下标（从 0 开始，**左闭右开** `[start, end)`） |
| `fragment` | 区间原文片段，即 `text[start:end]` |
| `cost` | 引文与该区间对齐的最小代价（相同字/任一侧 `?` 为 0；替换、插入、删除各 1） |
| `sources` | 该区间的逐字来源列表，与 `fragment` 等长，规则与 `/api/assemble` 一致 |

引文或拼接文本任一侧含 `?` 均免代价（下例引文 `时?之` 与片段 `时习之` 代价 0）：

```bash
curl -X POST http://localhost:8000/api/locate-quote \
  -H "Content-Type: application/json" \
  -d '{"segments": ["学而?习之", "时习之不", "之不亦乐乎"], "quote": "时?之"}'
```

允许最多 2 处差异——下例引文末字 `悦` 与拼接文本 `乎` 不同（替换 1 次），区间 `[0, 9)` 唯一命中：

```json
{
  "text": "学而时习之不亦乐乎",
  "quote": "学而时习之不亦悦乎",
  "start": 0,
  "end": 9,
  "fragment": "学而时习之不亦乐乎",
  "cost": 1,
  "sources": [ "…" ]
}
```

**多个不同区间并列（409）**示例——拼接文本 `甲子丙丁卯甲庚` 中有两个 `甲`，引文 `甲` 对两个区间
代价同为 0，接口不擅自选择：

```bash
curl -X POST http://localhost:8000/api/locate-quote \
  -H "Content-Type: application/json" \
  -d '{"segments": ["甲子丙丁卯", "丁卯甲庚"], "quote": "甲"}'
```

```json
{
  "detail": {
    "message": "引文在拼接文本中有 2 个不同区间以最小代价 0 并列，无法唯一定位",
    "cost": 0,
    "ties": [
      { "start": 0, "end": 1, "fragment": "甲", "cost": 0, "sources": [[{ "segment": 0, "pos": 0 }]] },
      { "start": 5, "end": 6, "fragment": "甲", "cost": 0, "sources": [[{ "segment": 1, "pos": 2 }]] }
    ]
  }
}
```

注意：即使区间长度不同也可能并列——例如引文 `时习知` 对片段 `时习之`（末字替换，代价 1）与对片段
`时习`（末尾多一个引文字删除，代价 1）并列时同样返回 **409**，两个区间都会列入 `ties`。

**无合格区间（422）**示例——引文与拼接文本任何非空区间的最小代价都大于 2：

```bash
curl -X POST http://localhost:8000/api/locate-quote \
  -H "Content-Type: application/json" \
  -d '{"segments": ["学而?习之", "时习之不", "之不亦乐乎"], "quote": "朋朋朋朋"}'
```

```json
{
  "detail": {
    "message": "引文（4 字）在拼接文本中最接近区间的代价为 4，超过 2，无合格区间"
  }
}
```

`quote` 为空、超过 80 字、缺字段，或 segments 不满足 `/api/assemble` 的段数/长度限制、续接失败，
同样返回 **422**（续接失败时给出 `failed_segment`，从 0 开始）。

### `POST /api/locate-quotes`

在拼接文本中**按原文顺序同时定位 2～4 段引文**。请求的 `segments` 与 `/api/assemble` 完全相同
（沿用 2～5 段、单段最长 500 字、总长最长 800 字的限制与续接门槛，续接失败同样返回 **422** 并给出
`failed_segment`），另附 **2～4 段按原文顺序排列**的引文 `quotes`（每段 **1～80** 字，未辨认字也以
`?` 表示）。接口先复用 `/api/assemble` 得到拼接文本与逐字来源，然后：

- **枚举候选**：对每段引文枚举与拼接文本的任意非空连续区间、逐字编辑代价不超过 **2** 的**全部**区间
  （代价规则同 `/api/locate-quote`：相同字或任一侧 `?` 代价 **0**，替换/插入/删除各代价 **1**，
  区间两端自由、引文完全消耗）；
- **选完整定位链**：从各段候选中选出区间按引文顺序排列、**两两不重叠**（前段 `end` ≤ 后段 `start`，
  相邻可贴合，不共享字即不算重叠）且**各段代价之和最低**的完整链；
- **不放弃次优候选**：即使某段引文单独最低代价的候选无法接入完整链（例如与前一段区间重叠），也会
  继续考虑该段其余代价不超过 2 的合格候选；
- **唯一最优链**时返回 `total_cost` 与 `hits`（与 `quotes` 等长、等序，每项含该段引文的区间、
  原文片段 `fragment`、本段代价 `cost` 与该区间逐字 `sources`）；
- **多个不同最优链并列**时返回 **409**，`detail.ties` 给出**两条不同的最优链**（按区间坐标字典序
  取最小的两条；同一组区间即使存在多种内部对齐方式也只算一条链）；
- **无完整链**（某段引文没有代价 ≤ 2 的区间，或所有合格区间都无法按序组成互不重叠的链）时返回
  **422**。接口**只做定位，不改写拼接文本**。

请求体：

```json
{
  "segments": ["学而?习之", "时习之不", "之不亦乐乎"],
  "quotes": ["学而", "时习之", "不亦乐乎"]
}
```

- `segments`：必填，2～5 个非空字符串；单段最长 500 字，各段总长最长 800 字（同 `/api/assemble`）。
- `quotes`：必填，**2～4** 个非空字符串；每段 **1～80** 字，按引文在原文中的先后顺序排列。

调用示例：

```bash
curl -X POST http://localhost:8000/api/locate-quotes \
  -H "Content-Type: application/json" \
  -d '{"segments": ["学而?习之", "时习之不", "之不亦乐乎"], "quotes": ["学而", "时习之", "不亦乐乎"]}'
```

响应示例（三段引文在拼接文本 `学而时习之不亦乐乎` 中代价均为 0，区间 `[0,2)`、`[2,5)`、`[5,9)`
按序贴合，总代价 0）：

```json
{
  "text": "学而时习之不亦乐乎",
  "quotes": ["学而", "时习之", "不亦乐乎"],
  "total_cost": 0,
  "hits": [
    {
      "start": 0,
      "end": 2,
      "fragment": "学而",
      "cost": 0,
      "sources": [
        [{ "segment": 0, "pos": 0 }],
        [{ "segment": 0, "pos": 1 }]
      ]
    },
    {
      "start": 2,
      "end": 5,
      "fragment": "时习之",
      "cost": 0,
      "sources": [
        [{ "segment": 0, "pos": 2 }, { "segment": 1, "pos": 0 }],
        [{ "segment": 0, "pos": 3 }, { "segment": 1, "pos": 1 }],
        [{ "segment": 0, "pos": 4 }, { "segment": 1, "pos": 2 }, { "segment": 2, "pos": 0 }]
      ]
    },
    {
      "start": 5,
      "end": 9,
      "fragment": "不亦乐乎",
      "cost": 0,
      "sources": [
        [{ "segment": 1, "pos": 3 }, { "segment": 2, "pos": 1 }],
        [{ "segment": 2, "pos": 2 }],
        [{ "segment": 2, "pos": 3 }],
        [{ "segment": 2, "pos": 4 }]
      ]
    }
  ]
}
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `text` | 拼接文本（与 `/api/assemble` 一致，不被改写） |
| `quotes` | 原样回显的引文列表（2～4 段，按原文顺序排列） |
| `total_cost` | 完整定位链上各段引文代价之和 |
| `hits[]` | 各引文的定位结果，与 `quotes` 等长、等序；字段同 `/api/locate-quote`（`start`/`end`/`fragment`/`cost`/`sources`），相邻区间满足前段 `end` ≤ 后段 `start` |

**次优候选成链**示例——两段引文都是单字 `甲` 时，第二段单独的代价 0 区间 `[0,1)` 与第一段重叠、
无法接入完整链；接口改取该段代价 1 的区间 `[1,2)`（片段 `乙`，替换 1 次），总代价 1：

```bash
curl -X POST http://localhost:8000/api/locate-quotes \
  -H "Content-Type: application/json" \
  -d '{"segments": ["甲乙", "甲乙"], "quotes": ["甲", "甲"]}'
```

```json
{
  "text": "甲乙",
  "quotes": ["甲", "甲"],
  "total_cost": 1,
  "hits": [
    { "start": 0, "end": 1, "fragment": "甲", "cost": 0, "sources": [[{ "segment": 0, "pos": 0 }]] },
    { "start": 1, "end": 2, "fragment": "乙", "cost": 1, "sources": [[{ "segment": 0, "pos": 1 }, { "segment": 1, "pos": 1 }]] }
  ]
}
```

**多个最优链并列（409）**示例——拼接文本 `甲丙甲丙` 中，引文 `甲`、`丙` 各有两个代价 0 位置，
`甲[0,1) → 丙[1,2)` 与 `甲[0,1) → 丙[3,4)` 总代价同为 0，接口不擅自选择，返回两条不同最优链：

```bash
curl -X POST http://localhost:8000/api/locate-quotes \
  -H "Content-Type: application/json" \
  -d '{"segments": ["甲丙甲丙", "甲丙甲丙"], "quotes": ["甲", "丙"]}'
```

```json
{
  "detail": {
    "message": "2 段引文在拼接文本中有多个不同定位链以最低总代价 0 并列，无法唯一确定",
    "cost": 0,
    "ties": [
      [
        { "start": 0, "end": 1, "fragment": "甲", "cost": 0, "sources": [[{ "segment": 0, "pos": 0 }]] },
        { "start": 1, "end": 2, "fragment": "丙", "cost": 0, "sources": [[{ "segment": 0, "pos": 1 }]] }
      ],
      [
        { "start": 0, "end": 1, "fragment": "甲", "cost": 0, "sources": [[{ "segment": 0, "pos": 0 }]] },
        { "start": 3, "end": 4, "fragment": "丙", "cost": 0, "sources": [[{ "segment": 0, "pos": 3 }]] }
      ]
    ]
  }
}
```

**无完整链（422）**示例——两段引文各自都有代价不超过 2 的区间，但可行区间的先后顺序与引文顺序
相反，无法选出互不重叠的完整链（某段引文本身无合格区间时同样返回 422，并指出是第几段引文）：

```bash
curl -X POST http://localhost:8000/api/locate-quotes \
  -H "Content-Type: application/json" \
  -d '{"segments": ["甲甲乙乙", "甲甲乙乙"], "quotes": ["乙乙XX", "甲甲XX"]}'
```

```json
{
  "detail": {
    "message": "各段引文虽有代价不超过 2 的区间，但无法按原文顺序选出互不重叠的完整定位链"
  }
}
```

`quotes` 段数不在 2～4、某段为空或超过 80 字、缺字段，或 segments 不满足 `/api/assemble` 的
段数/长度限制、续接失败，同样返回 **422**（续接失败时给出 `failed_segment`，从 0 开始）。

### `POST /api/find-repetition`

供校勘人员发现同一拼接稿中**可能的重复抄写**。请求的 `segments` 与 `/api/assemble` 完全相同（沿用
2～5 段、单段最长 500 字、总长最长 800 字的限制与续接门槛，续接失败同样返回 **422** 并给出
`failed_segment`）。接口先复用 `/api/assemble` 得到拼接文本与逐字来源，再在**同一份拼接文本**中寻找
两个**互不重叠的等长连续区间**：

- **逐字兼容**：对应位置的两个字**相同**，或**任一字为 `?`**（未辨认字）即视为兼容；
- **长度门槛**：区间长度至少 **6**；
- **已知相同位门槛**：区间内至少 **4** 个位置是两侧皆为**已知字且相同**（`?` 与他字的兼容配对
  不计入已知相同位，避免全 `?` 区间造成误报）；
- **互不重叠**：两区间不共享字，允许贴合（前段 `end` ≤ 后段 `start`）。

**择优规则**：先取**长度最长**的区间对；长度相同时取**已知相同位更多**者；再相同则按
**两起点升序** `(first.start, second.start)` 取首对，结果确定、不返回并列冲突。两个区间按起点升序记为
`repeat.first`、`repeat.second`，各自给出左闭右开区间 `[start, end)`、原文片段 `fragment` 与该区间
逐字 `sources`（与 `fragment` 等长，规则同 `/api/assemble`）。接口**只做发现，不改写拼接文本**；
不存在合格重复时 `repeat` 为 **`null`**。

请求体：

```json
{
  "segments": ["学而时习之不亦朱雀", "朱雀玄武白虎腾蛇青龙学而时习之不亦"]
}
```

- `segments`：必填，2～5 个非空字符串；单段最长 500 字，各段总长最长 800 字（同 `/api/assemble`）。

调用示例：

```bash
curl -X POST http://localhost:8000/api/find-repetition \
  -H "Content-Type: application/json" \
  -d '{"segments": ["学而时习之不亦朱雀", "朱雀玄武白虎腾蛇青龙学而时习之不亦"]}'
```

响应示例（拼接文本 `学而时习之不亦朱雀玄武白虎腾蛇青龙学而时习之不亦` 中，`学而时习之不亦` 出现
两次：区间 `[0,7)` 与 `[17,24)` 等长 7 字、7 个已知相同位、互不重叠）：

```json
{
  "text": "学而时习之不亦朱雀玄武白虎腾蛇青龙学而时习之不亦",
  "repeat": {
    "first": {
      "start": 0,
      "end": 7,
      "fragment": "学而时习之不亦",
      "sources": [
        [{ "segment": 0, "pos": 0 }],
        [{ "segment": 0, "pos": 1 }],
        [{ "segment": 0, "pos": 2 }],
        [{ "segment": 0, "pos": 3 }],
        [{ "segment": 0, "pos": 4 }],
        [{ "segment": 0, "pos": 5 }],
        [{ "segment": 0, "pos": 6 }]
      ]
    },
    "second": {
      "start": 17,
      "end": 24,
      "fragment": "学而时习之不亦",
      "sources": [
        [{ "segment": 1, "pos": 10 }],
        [{ "segment": 1, "pos": 11 }],
        [{ "segment": 1, "pos": 12 }],
        [{ "segment": 1, "pos": 13 }],
        [{ "segment": 1, "pos": 14 }],
        [{ "segment": 1, "pos": 15 }],
        [{ "segment": 1, "pos": 16 }]
      ]
    }
  }
}
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `text` | 拼接文本（与 `/api/assemble` 一致，不被改写） |
| `repeat` | 最优重复区间对；无合格重复时为 `null` |
| `repeat.first` / `repeat.second` | 起点较小 / 较大的区间，二者等长且互不重叠（`first.end ≤ second.start`） |
| `start` / `end` | 区间在拼接文本中的下标（从 0 开始，**左闭右开** `[start, end)`） |
| `fragment` | 区间原文片段，即 `text[start:end]` |
| `sources` | 该区间的逐字来源列表，与 `fragment` 等长，规则与 `/api/assemble` 一致 |

任一侧含 `?` 仍可配对——例如两处抄写为 `甲乙丙丁戊己` 与 `甲?丙丁戊?` 时，逐字兼容、长度 6、
已知相同位 4（≥4），同样会被发现；但若兼容位全部来自 `?`（已知相同位不足 4），或两区间只能以
重叠方式取得（如短周期文本 `甲乙丙甲乙丙…` 中互不重叠窗口不足 6 字），则不构成合格重复。

续接失败、段数/长度不合法、缺字段时同样返回 **422**（续接失败时给出 `failed_segment`，从 0 开始）。

### `POST /api/audit-omission`

供校勘人员以一份**独立参照转写**（如后世刻本）复核拼接稿在**段与段接缝处是否漏抄了连续文字**。
请求的 `segments` 与 `/api/assemble` 完全相同（沿用 2～5 段、单段最长 500 字、总长最长 800 字的
限制与续接门槛，续接失败同样返回 **422** 并给出 `failed_segment`），另附参照转写 `reference`
（**1～840** 字，未辨认字也以 `?` 表示）。接口先复用 `/api/assemble` 得到拼接文本与逐字来源，再：

- **只检查段间接缝**：枚举拼接文本相邻两字 `text[pos-1]` 与 `text[pos]` 之间，左字的逐字来源中含某
  原始段 `k`、而右字来源不含 `k` 且含**更晚的原始段**（序号 > `k`）的位置（由较早段跨入更晚段的
  接缝）；首尾位置不是接缝；
- **长度前提**：参照稿须比拼接稿**恰好多 1～40 字**（`gap = len(reference) - len(text)`），等长、更短
  或多逾 40 字均返回 **422**；
- **枚举补字方案**：对每条接缝，把参照稿中占据补入位置的连续片段 `reference[pos:pos+gap]` 补入该接缝，
  两稿即等长并**逐位对齐**：相同字、或任一侧为 `?` 记 **0**，双方皆为已知且异字记 **1**（补入片段与
  参照稿同位文字逐字相同，不产生异字；异字只来自接缝前、后的逐位比较）；
- **合格与择优**：仅接受整稿异字数不超过 **2** 的方案，取异字数最少者；
- **不同缺文位置并列（409）**：多条不同接缝以同一最少异字数命中时返回 **409**，`detail.ties` 按插入
  位置升序列出全部并列方案（各含 `pos`、`missing`、`diff` 及接缝两侧 `left`/`right`）；
- **无合格方案（422）**：拼接文本中没有段间接缝、或所有接缝补入后异字数均超过 2 时返回 **422**。

接口**只做审计提示，不改写拼接文本**；唯一方案返回的字段：

| 字段 | 含义 |
| --- | --- |
| `text` | 拼接文本（与 `/api/assemble` 一致，不被改写） |
| `reference` | 原样回显的独立参照转写 |
| `pos` | 缺文插入位置（拼接文本下标，从 0 开始）：补在 `text[pos-1]` 与 `text[pos]` 之间 |
| `missing` | 建议补入的参照稿连续缺文字串 `reference[pos:pos+gap]`（1～40 字） |
| `diff` | 补入后两稿逐位对齐的异字数（0～2） |
| `left` | 接缝左侧相邻字 `text[pos-1]` 及其逐字 `sources`（含 `char` 与 `sources`） |
| `right` | 接缝右侧相邻字 `text[pos]` 及其逐字 `sources`（含 `char` 与 `sources`） |

请求体：

```json
{
  "segments": ["甲乙丙丁戊己", "戊己庚辛"],
  "reference": "甲乙丙丁戊己X庚辛"
}
```

- `segments`：必填，2～5 个非空字符串；单段最长 500 字，各段总长最长 800 字（同 `/api/assemble`）。
- `reference`：必填，**1～840** 字的独立参照转写，须比拼接文本恰好多 1～40 字。

调用示例：

```bash
curl -X POST http://localhost:8000/api/audit-omission \
  -H "Content-Type: application/json" \
  -d '{"segments": ["甲乙丙丁戊己", "戊己庚辛"], "reference": "甲乙丙丁戊己X庚辛"}'
```

响应示例（拼接文本 `甲乙丙丁戊己庚辛` 共 8 字、参照 9 字；接缝位于 `己`(pos 5) 与 `庚`(pos 6) 之间，
即段 0 跨入段 1 处，补入 `X` 后两稿逐位全同，`diff` 为 0）：

```json
{
  "text": "甲乙丙丁戊己庚辛",
  "reference": "甲乙丙丁戊己X庚辛",
  "pos": 6,
  "missing": "X",
  "diff": 0,
  "left": {
    "char": "己",
    "sources": [
      { "segment": 0, "pos": 5 },
      { "segment": 1, "pos": 1 }
    ]
  },
  "right": {
    "char": "庚",
    "sources": [
      { "segment": 1, "pos": 2 }
    ]
  }
}
```

任一侧含 `?` 的字符对不记异字；接缝前后逐位比较中最多允许 2 处双方皆已知的异字。缺文多于 1 字时
`missing` 为参照稿在该位置的连续片段，例如参照 `甲乙丙丁戊己XYZ庚辛`（多 3 字）时 `missing` 为 `XYZ`。

**多个不同缺文位置并列（409）**示例——拼接文本 `AXCD`（segments `["AX", "AXC", "XCD"]`，接缝位于
`X|C` 的 pos 2 与 `C|D` 的 pos 3），参照 `AXCCD` 中多出的 `C` 补在任一接缝都逐位相同，接口不擅自选择：

```bash
curl -X POST http://localhost:8000/api/audit-omission \
  -H "Content-Type: application/json" \
  -d '{"segments": ["AX", "AXC", "XCD"], "reference": "AXCCD"}'
```

```json
{
  "detail": {
    "message": "参照稿的连续缺文可补入 2 个不同接缝且最少异字数同为 0，无法唯一确定缺文位置",
    "diff": 0,
    "ties": [
      {
        "pos": 2,
        "missing": "C",
        "diff": 0,
        "left": { "char": "X", "sources": [ { "segment": 0, "pos": 1 }, { "segment": 1, "pos": 1 }, { "segment": 2, "pos": 0 } ] },
        "right": { "char": "C", "sources": [ { "segment": 1, "pos": 2 }, { "segment": 2, "pos": 1 } ] }
      },
      {
        "pos": 3,
        "missing": "C",
        "diff": 0,
        "left": { "char": "C", "sources": [ { "segment": 1, "pos": 2 }, { "segment": 2, "pos": 1 } ] },
        "right": { "char": "D", "sources": [ { "segment": 2, "pos": 2 } ] }
      }
    ]
  }
}
```

**无合格方案（422）**示例——参照与拼接稿在所有接缝补入后逐位异字都超过 2：

```json
{
  "detail": {
    "message": "全部 2 个段间接缝补入参照稿连续缺文后，整稿异字数均超过 2，无合格脱漏方案"
  }
}
```

拼接文本没有段间接缝（如两段完全重叠）、参照与拼接稿长度差不在 1～40 字、参照为空或超过 840 字、
缺字段，或 segments 不满足 `/api/assemble` 的段数/长度限制、续接失败，同样返回 **422**
（续接失败时给出 `failed_segment`，从 0 开始）。

### `POST /api/compare-editions`

供校勘人员**对勘两份稿子**。请求含两组各 **2～5 段**转写 `left_segments`、`right_segments`，两组各自
沿用 `/api/assemble` 的段数/长度限制（单段最长 500 字、**每组各段总长**最长 800 字）与续接门槛，
**分别独立拼接**为左、右两份稿子（各自的逐字来源相互独立、互不影响）。返回的**版本文本**沿用拼接的
逐字来源，但逐位置取**最早段**的原始字形：**前段的 `?`（未辨认字）被同侧后段已知字续接覆盖时保留该
`?`**，不改写为后段的补字——版本文本因此忠实反映各版本前段的未辨认字位置（`/api/assemble` 的补字
行为不受影响）。随后对两份保留 `?` 的版本文本做**全局逐字最小编辑对齐**：

- **两端固定**（不允许自由端）：两份稿子必须从头至尾全部参与对齐；
- 两字**相同**代价 **0**；**任一侧为 `?`**（未辨认字）的字符对代价也是 **0**；
- **替换**（双方均为已知字且不同）、**删除左字**、**插入右字**各代价 **1**；
- **固定择优**：同一动态规划格有多条同代价入边时，回溯所用对齐按 **对角 → 删除左字 → 插入右字**
  的固定次序选择，故输出确定、可复现；
- **歧义标记**：`ambiguous` 表示取得最小 `total_cost` 的最优对齐路径是否存在**多条**（不影响返回的
  那一条固定择优对齐，仅提示校勘人员差异边界可能有别的等价解释）。

**差异块**：把逐字对齐中**连续的非零代价列**合并为一个差异块，零代价列用于分块（相邻的替换、删除、
插入列会合并在同一块内）。每个 `blocks[]` 给出：

- `left` / `right`：两侧在**各自版本文本**上的**左闭右开区间** `[start, end)`、区间原文 `fragment`
  与该区间的逐字 `sources`（规则同 `/api/assemble`）；某一侧在块内无字（纯插入/纯删除）时该侧
  `start == end`、`fragment` 为空串、`sources` 为空列表。

两份稿子**完全一致**（或仅有 `?` 与已知字的免代价配对）时 `blocks` 为空数组、`total_cost` 为 0、
`ambiguous` 为 `false`。接口**只做对勘，不改写任何一份拼接稿**。

请求体：

```json
{
  "left_segments": ["学而?习之", "时习之不亦"],
  "right_segments": ["学而?习之", "时习之不", "之不亦乐乎"]
}
```

- `left_segments` / `right_segments`：必填，各 **2～5** 个非空字符串；单段最长 500 字，**每一侧**
  各段总长最长 800 字（两组限制各自独立判定）。

调用示例：

```bash
curl -X POST http://localhost:8000/api/compare-editions \
  -H "Content-Type: application/json" \
  -d '{"left_segments": ["甲乙丙丁戊己", "戊己庚辛"], "right_segments": ["甲乙丙X戊己", "戊己庚辛"]}'
```

响应示例（左稿 `甲乙丙丁戊己庚辛`、右稿 `甲乙丙X戊己庚辛`，一个替换块，总代价 1，对齐唯一）：

```json
{
  "left_text": "甲乙丙丁戊己庚辛",
  "right_text": "甲乙丙X戊己庚辛",
  "total_cost": 1,
  "ambiguous": false,
  "blocks": [
    {
      "left": {
        "start": 3,
        "end": 4,
        "fragment": "丁",
        "sources": [[{ "segment": 0, "pos": 3 }]]
      },
      "right": {
        "start": 3,
        "end": 4,
        "fragment": "X",
        "sources": [[{ "segment": 0, "pos": 3 }]]
      }
    }
  ]
}
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `left_text` / `right_text` | 左 / 右版本文本：沿用 `/api/assemble` 的拼接与逐字来源，但保留前段被同侧后段已知字续接覆盖的 `?`（不改写为补字） |
| `total_cost` | 全局逐字最小编辑对齐的总代价（相同字/任一侧 `?` 为 0；替换、插入、删除各 1） |
| `ambiguous` | 取得该总代价的最优对齐路径是否存在多条 |
| `blocks[].left` / `blocks[].right` | 差异块在左 / 右版本文本上的区间 `[start, end)`（左闭右开）、`fragment` 原文与逐字 `sources`；该侧无字时为空区间 |

前段 `?` 保留示例——左组段 0 的 `?` 被同组段 1 的“时”续接覆盖：版本文本保留 `?`，与右稿已知字
配对代价 0（若改写成补字“时”，版本文本即失真）；逐字来源仍沿用拼接结果（`?` 一方与补字一方都在）：

```bash
curl -X POST http://localhost:8000/api/compare-editions \
  -H "Content-Type: application/json" \
  -d '{"left_segments": ["学而?习之", "时习之"], "right_segments": ["学而时习之", "时习之"]}'
```

```json
{
  "left_text": "学而?习之",
  "right_text": "学而时习之",
  "total_cost": 0,
  "ambiguous": false,
  "blocks": []
}
```

纯删除/插入块示例——右稿比左稿多一个 `丁`（下标 3），该块 `left` 为空区间：

```bash
curl -X POST http://localhost:8000/api/compare-editions \
  -H "Content-Type: application/json" \
  -d '{"left_segments": ["甲乙丙戊己", "戊己庚辛"], "right_segments": ["甲乙丙丁戊己", "戊己庚辛"]}'
```

```json
{
  "left_text": "甲乙丙戊己庚辛",
  "right_text": "甲乙丙丁戊己庚辛",
  "total_cost": 1,
  "ambiguous": false,
  "blocks": [
    {
      "left": { "start": 3, "end": 3, "fragment": "", "sources": [] },
      "right": {
        "start": 3,
        "end": 4,
        "fragment": "丁",
        "sources": [[{ "segment": 0, "pos": 3 }]]
      }
    }
  ]
}
```

歧义示例——左稿 `甲乙…`、右稿 `乙甲…`：`甲乙→乙甲` 的替换对齐与删除/插入对齐总代价同为 2，
存在多条最优路径，`ambiguous` 为 `true`（返回的对齐固定按对角优先，差异块两侧各为 `甲乙`/`乙甲`）：

```bash
curl -X POST http://localhost:8000/api/compare-editions \
  -H "Content-Type: application/json" \
  -d '{"left_segments": ["甲乙戊己", "戊己"], "right_segments": ["乙甲戊己", "戊己"]}'
```

```json
{
  "left_text": "甲乙戊己",
  "right_text": "乙甲戊己",
  "total_cost": 2,
  "ambiguous": true,
  "blocks": [
    {
      "left": { "start": 0, "end": 2, "fragment": "甲乙", "sources": [ "…" ] },
      "right": { "start": 0, "end": 2, "fragment": "乙甲", "sources": [ "…" ] }
    }
  ]
}
```

`left_segments` 或 `right_segments` 段数不在 2～5、单段超 500 字、该侧总长超 800 字、含空段或缺字段，
返回 **422**；某一侧拼接未通过续接门槛时同样返回 **422**，`detail` 中给出 `side`（`left` / `right`）
与 `failed_segment`（从 0 开始）。

### `POST /api/trace-reading`

供校勘人员回答“拼接稿这一段文字，分别能由哪几段原始转写的哪些连续原文逐字对上”。请求的
`segments` 与 `/api/assemble` 完全相同（沿用 2～5 段、单段最长 500 字、总长最长 800 字的限制与续接
门槛，续接失败同样返回 **422** 并给出 `failed_segment`），另附拼接稿上一个**左闭右开**区间
`start`、`end`（均为拼接文本下标，从 0 开始，须满足 `0 <= start < end <= len(text)`）。接口先复用
`/api/assemble` 得到拼接文本与逐字来源，再为区间内**每个输出字选恰好一个来源**（某原始段的某原文
下标）作为该字证据：

- **证据资格**：该来源的**原字等于该输出字**、或原字为 `?`（未辨认字）才可作为该字证据；异字来源
  （拼接时保留左段字而来源中仍保留的右段异字）不可用，故某个字可能没有任何合格证据；
- **同段连续**：路径中连续两个字选了**同一段**时，所取原文下标必须**严格逐次加一**（后字下标 =
  前字下标 + 1），即一次同段取字必须覆盖该段一串连续原文，不能跳字；
- **换段约束**：相邻两字从段 `a` 换到段 `b`（`a != b`，不要求 `b > a`）时，**交界两侧至少各有一个字
  同时携带 `a`、`b` 两段的来源**——区间内交界**换前侧**（交界之前的部分）存在某个字，其来源中既有
  `a` 又有 `b`；交界**换后侧**（交界及之后的部分）同样存在某个字同时含 `a`、`b`。这两个见证字**不必
  紧贴交界**；该约束的含义是换段只能发生在两段来源共同覆盖区域的内部，不能贴着共同覆盖区的边界
  “跳进/跳出”。

在上述约束下为**整个区间**求一条覆盖全部输出字的完整证据路径，目标依次为：

1. **换段次数最少**（尽量少地在原始段之间切换）；
2. 换段次数相同时，所选证据里**原字为 `?` 的字数最少**；
3. 仍相同时，按所选 **`(段序号序列, 原文下标序列)` 的字典序取首条**（先比段序号序列，再比原文
   下标序列），输出确定；
4. `ambiguous` 标记取得该最少换段次数与最少 `?` 数的完整路径是否**还存在其他路径**（取首只决定
   返回哪一条，不影响该标记）。

请求体：

```json
{
  "segments": ["学而?习之", "时习之不", "之不亦乐乎"],
  "start": 0,
  "end": 9
}
```

- `segments`：必填，2～5 个非空字符串；单段最长 500 字，各段总长最长 800 字（同 `/api/assemble`）。
- `start` / `end`：必填，非负整数；左闭右开区间 `[start, end)`，要求 `start < end` 且 `end` 不超出
  拼接文本长度，否则返回 **422**。

调用示例：

```bash
curl -X POST http://localhost:8000/api/trace-reading \
  -H "Content-Type: application/json" \
  -d '{"segments": ["学而?习之", "时习之不", "之不亦乐乎"], "start": 0, "end": 9}'
```

响应示例（区间 `[0,9)` 覆盖全文 `学而时习之不亦乐乎`；最优为 2 次换段、所选 `?` 1 个；交界 4
（`习|之`）、交界 5（`之|不`）的换前、换后侧都能在 0/1、1/2 的共同覆盖区找到见证字；段 0 的 `?`
（原文下标 2）被选为输出字“时”的证据；另有一条在交界 5 才从段 0 换到段 1 的同分路径，故
`ambiguous` 为 `true`）：

```json
{
  "text": "学而时习之不亦乐乎",
  "start": 0,
  "end": 9,
  "interval_text": "学而时习之不亦乐乎",
  "legs": [
    {
      "segment": 0,
      "merged": {
        "start": 0,
        "end": 4,
        "fragment": "学而时习",
        "sources": [
          [{ "segment": 0, "pos": 0 }],
          [{ "segment": 0, "pos": 1 }],
          [{ "segment": 0, "pos": 2 }],
          [{ "segment": 0, "pos": 3 }]
        ]
      },
      "original": {
        "start": 0,
        "end": 4,
        "fragment": "学而?习",
        "sources": [
          [{ "segment": 0, "pos": 0 }],
          [{ "segment": 0, "pos": 1 }],
          [{ "segment": 0, "pos": 2 }],
          [{ "segment": 0, "pos": 3 }]
        ]
      }
    },
    {
      "segment": 1,
      "merged": {
        "start": 4,
        "end": 5,
        "fragment": "之",
        "sources": [[{ "segment": 1, "pos": 2 }]]
      },
      "original": {
        "start": 2,
        "end": 3,
        "fragment": "之",
        "sources": [[{ "segment": 1, "pos": 2 }]]
      }
    },
    {
      "segment": 2,
      "merged": {
        "start": 5,
        "end": 9,
        "fragment": "不亦乐乎",
        "sources": [
          [{ "segment": 2, "pos": 1 }],
          [{ "segment": 2, "pos": 2 }],
          [{ "segment": 2, "pos": 3 }],
          [{ "segment": 2, "pos": 4 }]
        ]
      },
      "original": {
        "start": 1,
        "end": 5,
        "fragment": "不亦乐乎",
        "sources": [
          [{ "segment": 2, "pos": 1 }],
          [{ "segment": 2, "pos": 2 }],
          [{ "segment": 2, "pos": 3 }],
          [{ "segment": 2, "pos": 4 }]
        ]
      }
    }
  ],
  "switch_positions": [
    { "pos": 4, "from_segment": 0, "to_segment": 1 },
    { "pos": 5, "from_segment": 1, "to_segment": 2 }
  ],
  "question_positions": [
    { "pos": 2, "segment": 0, "original_pos": 2, "output_char": "时" }
  ],
  "switch_count": 2,
  "question_count": 1,
  "ambiguous": true
}
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `text` | 拼接文本（与 `/api/assemble` 一致，不被改写） |
| `start` / `end` | 原样回显的区间（左闭右开） |
| `interval_text` | 区间文本，即 `text[start:end]` |
| `legs[]` | 证据路径按段切分的路径段（同段连续取字归为一条），按拼接稿位置升序；同一段若被多次进入会出现多条 `legs` |
| `legs[].segment` | 该路径段的原始段序号（从 0 开始） |
| `legs[].merged` | 该路径段在**拼接稿**上的左闭右开区间 `[start, end)`、片段 `fragment` 与逐字所选来源；各 `legs` 的 `merged` 区间首尾相接、恰好覆盖请求区间 |
| `legs[].original` | 该路径段在**该原始段文本**上的左闭右开区间、片段与逐字来源；长度与 `merged` 相同（原文下标连续逐次加一） |
| `switch_positions[]` | 换段交界，按位置升序；`pos` 表示交界位于 `text[pos-1]` 与 `text[pos]` 之间，并给出 `from_segment` / `to_segment`；交界换前侧、换后侧各至少有一个字同时携带这两段来源（见证不必紧贴交界） |
| `question_positions[]` | 所选证据原字为 `?` 的位置，按拼接文本位置升序；各带 `segment`、`original_pos` 与该位置输出字 `output_char` |
| `switch_count` | 换段次数（第一层目标，最少） |
| `question_count` | 所选 `?` 数（第二层目标，最少），等于 `len(question_positions)` |
| `ambiguous` | 取得该最少换段次数与最少 `?` 数的完整路径是否存在多条 |

单段即可覆盖的小区间没有换段：下例区间 `[2,6)` 的 `时习之不` 由段 1 原文 `[0,4)` 连续覆盖，
`switch_count` 为 0、`legs` 仅一条：

```bash
curl -X POST http://localhost:8000/api/trace-reading \
  -H "Content-Type: application/json" \
  -d '{"segments": ["学而?习之", "时习之不", "之不亦乐乎"], "start": 2, "end": 6}'
```

**无完整路径（422）**示例——`segments` 为 `["甲乙丙", "甲乙XY丙"]`，拼接文本为 `甲乙丙Y丙`：
对齐时段 1 的 `X` 落为空缺列、`Y` 插入，故 `Y`（下标 3）仅由段 1 贡献；而段 1 原文里 `Y`（下标 3）
之后是 `丙`（下标 4），与 `Y` 前的 `丙`（下标 2）不连续，无法以“同段原文下标逐次加一”把 `Y` 与
其前后的字连通；同时 0、1 两段的共同覆盖只有 `甲乙丙`（下标 0～2），在 `Y` 之后的换后侧没有任何
共同覆盖字可作换段见证，整条区间不存在完整证据路径：

```json
{
  "detail": {
    "message": "区间 [0, 5) 内第 4 字（拼接稿下标 3）无法在满足同段连续与换段约束的前提下接入证据路径"
  }
}
```

区间为空（`start == end`）、`start > end`、`end` 超出拼接文本长度、`start`/`end` 为负或缺字段，
同样返回 **422**；续接失败时给出 `failed_segment`（从 0 开始）。接口**只做证据追溯，不改写拼接文本**。

### `POST /api/audit-transposition`

供校勘人员以一份**独立参照转写**（如另一藏本）诊断拼接稿中**一段连续文字被移到另一位置**的情形。
请求的 `segments` 与 `/api/assemble` 完全相同（沿用 2～5 段、单段最长 500 字、总长最长 800 字的
限制与续接门槛，续接失败同样返回 **422** 并给出 `failed_segment`），另附参照转写 `reference`
（**1～120** 字，未辨认字也以 `?` 表示）。接口先复用 `/api/assemble` 得到拼接文本与逐字来源，再：

- **长度前提**：两稿须**等长**且均不超过 **120** 字，否则返回 **422**；
- **冲突前提**：拼接稿与参照稿之间须存在**已知字冲突**（双方皆已知且异字的位置）——两稿已逐字
  吻合（或仅差 `?`）时无移位可诊断，返回 **422**；
- **枚举移位操作**：枚举拼接稿的**左闭右开区间** `[start, end)`（长度 **2～12** 字），把该区间剪下，
  得到剩余文本 `rem = text[:start] + text[end:]`（长 `n - L`），再按剩余文本的**插入下标** `insert_at`
  （`0 ≤ insert_at ≤ n - L`）放回，重排文本为 `rem[:insert_at] + moved + rem[insert_at:]`；
  **排除原位**（`insert_at == start`，必然还原原文）及**重排后未改变文本**的操作；
- **判定**：重排文本**逐字与参照稿比较**，相同字或任一侧为 `?` 算吻合；须**全部位置吻合**，且
  **移位片段在其新位置上至少有 2 个两侧已知且相同的字**（避免全 `?` 片段造成误报），方为合格操作；
- **择优**：按**移位长度最短**取解。最短长度下操作唯一时返回该操作；最短长度存在多个不同操作时
  返回 **409**，`detail.ties` 给出**两种操作**（按区间起点、插入下标升序取前两个，`detail.moved_len`
  为并列的移位长度）；不存在合格操作时返回 **422**。

接口**只做审计提示，不改写拼接文本**；唯一解返回的字段：

| 字段 | 含义 |
| --- | --- |
| `text` | 拼接文本（与 `/api/assemble` 一致，不被改写） |
| `reference` | 原样回显的独立参照转写 |
| `start` / `end` | 被移走文字在拼接文本中的原区间（下标从 0 开始，**左闭右开** `[start, end)`） |
| `insert_at` | 剪下后在**剩余文本**中的插入下标（从 0 开始，不等于 `start`）：重排文本 = `rem[:insert_at] + moved + rem[insert_at:]` |
| `moved` | 移位文本，即 `text[start:end]`（2～12 字） |
| `sources` | 原区间逐字来源列表，与 `moved` 等长，规则与 `/api/assemble` 一致 |

请求体：

```json
{
  "segments": ["甲乙丙丁戊己", "戊己庚辛"],
  "reference": "甲乙戊己庚丙丁辛"
}
```

- `segments`：必填，2～5 个非空字符串；单段最长 500 字，各段总长最长 800 字（同 `/api/assemble`）。
- `reference`：必填，**1～120** 字的独立参照转写，须与拼接文本等长。

调用示例：

```bash
curl -X POST http://localhost:8000/api/audit-transposition \
  -H "Content-Type: application/json" \
  -d '{"segments": ["甲乙丙丁戊己", "戊己庚辛"], "reference": "甲乙戊己庚丙丁辛"}'
```

响应示例（拼接文本 `甲乙丙丁戊己庚辛` 中 `丙丁`（区间 `[2,4)`）被移到 `庚` 之后：剪下后剩余文本为
`甲乙戊己庚辛`，插入下标 5 处即还原参照稿；等价的 `戊己庚` 左移为 3 字操作，最短长度 2 唯一）：

```json
{
  "text": "甲乙丙丁戊己庚辛",
  "reference": "甲乙戊己庚丙丁辛",
  "start": 2,
  "end": 4,
  "insert_at": 5,
  "moved": "丙丁",
  "sources": [
    [{ "segment": 0, "pos": 2 }],
    [{ "segment": 0, "pos": 3 }]
  ]
}
```

任一侧含 `?` 的字符对算吻合——下例参照稿第 7 字为 `?`，2 字操作移 `丙丁` 后片段只剩 1 个两侧已知
且相同的字（`丁` 对 `?` 不计入），不足 2 字门槛，唯一解为 3 字操作（移 `戊己庚`）：

```bash
curl -X POST http://localhost:8000/api/audit-transposition \
  -H "Content-Type: application/json" \
  -d '{"segments": ["甲乙丙丁戊己", "戊己庚辛"], "reference": "甲乙戊己庚丙?辛"}'
```

```json
{
  "text": "甲乙丙丁戊己庚辛",
  "reference": "甲乙戊己庚丙?辛",
  "start": 4,
  "end": 7,
  "insert_at": 2,
  "moved": "戊己庚",
  "sources": [
    [{ "segment": 0, "pos": 4 }, { "segment": 1, "pos": 0 }],
    [{ "segment": 0, "pos": 5 }, { "segment": 1, "pos": 1 }],
    [{ "segment": 1, "pos": 2 }]
  ]
}
```

**同长度多解（409）**示例——相邻两字块 `丙丁`、`戊己` 互换位置时，"移 `丙丁` 到右"与"移 `戊己` 到左"
同为最短的 2 字操作且都还原参照稿，接口不擅自选择，返回两种操作：

```bash
curl -X POST http://localhost:8000/api/audit-transposition \
  -H "Content-Type: application/json" \
  -d '{"segments": ["甲乙丙丁戊己", "戊己庚辛"], "reference": "甲乙戊己丙丁庚辛"}'
```

```json
{
  "detail": {
    "message": "最短移位长度 2 字的合格操作有 2 个并列，无法唯一确定移位操作",
    "moved_len": 2,
    "ties": [
      {
        "start": 2,
        "end": 4,
        "insert_at": 4,
        "moved": "丙丁",
        "sources": [[{ "segment": 0, "pos": 2 }], [{ "segment": 0, "pos": 3 }]]
      },
      {
        "start": 4,
        "end": 6,
        "insert_at": 2,
        "moved": "戊己",
        "sources": [
          [{ "segment": 0, "pos": 4 }, { "segment": 1, "pos": 0 }],
          [{ "segment": 0, "pos": 5 }, { "segment": 1, "pos": 1 }]
        ]
      }
    ]
  }
}
```

**无解（422）**示例——参照稿含有拼接稿没有的字，任何移位都无法让该位置吻合：

```json
{
  "detail": {
    "message": "枚举全部 2～8 字连续区间的剪下重放后，没有使重排文本与参照稿逐字吻合的合格移位操作"
  }
}
```

两稿不等长、超过 120 字、无已知字冲突（完全一致或仅差 `?`）、参照为空或缺字段，或 segments 不满足
`/api/assemble` 的段数/长度限制、续接失败，同样返回 **422**（续接失败时给出 `failed_segment`，
从 0 开始）。

## 计分与并列规则

- 相同字 **+2**；`?` 与任意字配对 **0**；异字 **-2**；
- 连续空缺：首字 **-3**，其余每字 **-1**；
- 只将左段后缀与右段前缀对齐；左段未参与对齐的前缀、右段未参与对齐的后缀**不计分**；
- 对齐区**至少包含一对字符**；
- 同分并列时，取**对齐字符对数最多**者；仍并列，取**左段起点最小**者。

## 拼接规则

- `?` 以对方已知字替换（双方均为 `?` 时保留 `?`）；
- 异字保留左段字，并在 `conflicts` 中列出双方原文位置及字形；
- `/api/assemble` 在此规则上额外保留**逐字来源**：相同字、`?` 补字双方、异字冲突双方的
  原始段序号与下标均不丢失；只有满足续接门槛（得分 > 0 且至少 2 对相同已知字）才会并入下一段。
- `/api/collate` 不修改以上拼接结果，只基于拼接文本与逐字来源做段级投票：同段重复来源只计一次、
  `?` 不投票，仅列出至少两种不同已知字的异文位置；唯一最高票给建议字，并列则建议为 `null`。
- `/api/order` 对 2～4 段未排序转写穷举全部排列，逐段复用上述续接门槛（不满足即废弃该排列），
  以**各步对齐得分的累计**比较完整顺序的优劣（非原段两两相似度）；最高分唯一返回该顺序（来源按
  **原输入下标**标记），最高分并列返回 **409** 并列出全部并列顺序，无完整顺序返回 **422**。
- `/api/revise` 复用 `/api/assemble` 的拼接文本与逐字来源，把每项人工校订（段序号、原文下标、
  替换字）沿逐字来源定位到输出位置落实改字：重叠段指向同一位置的相同改字合并、不同改字返回 **409**，
  坐标越界或无法唯一定位返回 **422**；不重新对齐，未涉及位置保持原字，逐字来源沿用不变。
- `/api/locate-quote` 复用 `/api/assemble` 的拼接文本与逐字来源（沿用段数/长度限制与续接失败规则），
  把 1～80 字引文与拼接文本的任意非空连续区间比较：相同字或任一侧 `?` 代价 0，替换、插入、删除各
  代价 1，区间两端自由、引文完全消耗；最小代价不超过 2 且区间唯一时返回左闭右开区间、原文片段、
  代价与该区间逐字 sources，多个不同区间并列返回 **409**，无合格区间返回 **422**；只定位、不改写
  拼接文本。
- `/api/locate-quotes` 对 2～4 段按原文顺序排列的引文（各 1～80 字），枚举每段代价不超过 2 的全部
  非空区间（代价规则同上），再选区间按序、两两不重叠（前段 `end` ≤ 后段 `start`）且总代价最低的
  完整定位链；某段单独最优候选无法成链时仍考虑该段其余候选。唯一最优链返回各引文区间、片段、代价与
  sources，多个不同最优链并列返回 **409**（两条不同最优链），无完整链返回 **422**。
- `/api/find-repetition` 复用 `/api/assemble` 的拼接文本与逐字来源（沿用段数/长度限制与续接失败
  规则），在同一份拼接文本中找两个互不重叠（允许贴合）的等长连续区间：对应字相同或任一字为 `?`
  即兼容，长度至少 6 且至少 4 个位置两侧已知字相同；取长度最长者，同长度取已知相同位更多者，再按
  两起点升序取首对，返回两个左闭右开区间及各自原文与逐字 sources；无合格重复时 `repeat` 为 `null`。
- `/api/audit-omission` 复用 `/api/assemble` 的拼接文本与逐字来源（沿用段数/长度限制与续接失败
  规则），只检查“左字含某原始段、右字不含该段而含更晚原始段”的相邻段间接缝；参照稿（≤840 字）须比
  拼接稿恰好多 1～40 字。对每条接缝把参照稿同位连续片段补入后逐位对齐（相同字或任一侧 `?` 记 0、
  已知异字记 1，整稿最多 2），取异字数最少的接缝：唯一接缝返回插入位置、缺文、异字数与接缝两侧
  sources，不同缺文位置并列返回 **409**，无接缝或全部超 2 返回 **422**；只提示，不改写拼接稿。
- `/api/compare-editions` 对 `left_segments`、`right_segments` 两组各 2～5 段转写分别复用
  `/api/assemble`（各自沿用段数/长度限制与续接失败规则，两侧逐字来源相互独立）；返回的版本文本沿用
  其逐字来源，但**保留前段被同侧后段已知字续接覆盖的 `?`**（逐位置取最早段原始字形，不改写为补字），
  再对两份保留 `?` 的版本文本做全局逐字最小编辑对齐：两端固定，相同字或任一侧 `?` 代价 0，替换、
  删除左字、插入右字各 1；同分路径按对角 → 删除左字 → 插入右字固定择优，另以 `ambiguous` 标记最优
  路径是否多条；连续非零代价列合并为差异块，给出两侧左闭右开区间、原文与逐字 sources，完全一致
  （或仅差 `?`）时差异块为空；只对勘，不改写任何一份拼接稿。
- `/api/trace-reading` 复用 `/api/assemble` 的拼接文本与逐字来源（沿用段数/长度限制与续接失败
  规则），为指定左闭右开区间逐字选恰好一个来源作证据：来源原字等于输出字或为 `?` 才合格，异字来源
  不可用；同段连续取字原文下标严格逐次加一；换段仅可发生在区间内交界换前侧、换后侧各至少有一个字
  同时携带换前段与换后段来源处（见证字不必紧贴交界）。为整个区间求完整证据路径，依次最小化换段
  次数、所选 `?` 数，同分按段序号序列、原文下标序列字典序取首，`ambiguous` 标记是否存在其他同分
  路径；返回区间文本、每段路径的拼接稿及原文左闭右开区间（各带片段与逐字所选来源）、换段位置与
  所选 `?` 位置；区间非法或无完整路径返回 422；只追溯证据，不改写拼接文本。
- `/api/audit-transposition` 复用 `/api/assemble` 的拼接文本与逐字来源（沿用段数/长度限制与续接
  失败规则），参照稿（≤120 字）须与拼接稿等长且两稿间存在已知字冲突。枚举拼接稿 2～12 字连续区间，
  剪下后按剩余文本的插入下标放回（排除原位及重排后未改变文本的操作），重排文本逐字与参照稿比较
  （相同字或任一侧 `?` 算吻合，须全部位置吻合，且移位片段至少 2 个两侧已知且相同的字），按移位
  长度最短取解：唯一解返回原区间、剪下后的插入下标、移位文本与原区间逐字 sources，同长度多解
  返回 **409**（两种操作），无解返回 **422**；只提示，不改写拼接稿。

## 本地开发（不使用 Docker）

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## 运行测试

```bash
pip install -r requirements.txt requirements-dev.txt
pytest
```

## 项目结构

```
app/
  aligner.py    # 核心算法：后缀-前缀重叠对齐（仿射空缺罚分 DP + 回溯）
  assembler.py  # 多段顺序拼接：逐段复用对齐 + 续接门槛 + 逐字来源
  collator.py   # 异文校勘：复用拼接文本与逐字来源，段级投票回查原字
  orderer.py    # 未排序转写：穷举排列 + 累计对齐得分选序 + 并列/无完整顺序判定
  reviser.py    # 人工校订：沿逐字来源定位校订并落实改字 + 合并/冲突/定位判定
  locator.py    # 引文定位：半全局编辑代价 DP 查拼接文本区间；多引文按序不重叠最优链 + 并列/无完整链判定
  repetition.py # 重复抄写发现：对角扫描兼容 run + 滑动窗口取最长/已知相同位最多的非重叠等长区间对
  omission.py   # 脱漏审计：段间接缝枚举 + 参照稿连续缺文补入后逐位异字数（前/后缀和）择优与并列判定
  comparator.py # 双版本对勘：两份拼接稿的全局逐字最小编辑 DP（对角/删除/插入择优 + 路径歧义标记）+ 非零列合并差异块
  tracer.py     # 通读证据路径：区间逐字选合格来源（原字相等或为 ?），同段下标逐次加一、换段须两侧双覆盖的逐层 DP（最少换段→最少 ?→字典序取首 + 同分路径歧义标记）
  transposition.py # 移位审计：枚举 2～12 字连续区间剪下重放（排除原位与无变化操作），重排文本与参照稿逐字吻合判定（含 ? 免异字、片段已知相同位门槛），按移位长度最短择优与并列判定
  main.py       # FastAPI 接口与请求/响应模型（/api/align、/api/assemble、/api/collate、/api/order、/api/revise、/api/locate-quote、/api/locate-quotes、/api/find-repetition、/api/audit-omission、/api/compare-editions、/api/trace-reading、/api/audit-transposition）
tests/          # 算法与接口测试
Dockerfile      # 镜像构建（含依赖安装）
docker-compose.yml
```
