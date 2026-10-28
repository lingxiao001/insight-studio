# 跨领域公开分析示例

这些示例用真实的历史观测数据回答日常问题：哪类酒店预订需要提前确认、信用卡逾期能说明什么、临床随访为什么容易被误读、片库里有多少电影以及一部电影通常有多长。每个案例先给结论，再给证据、解释边界和下一步核验问题。

六个案例来自四份 Kaggle 数据集。酒店按原有酒店分为两个完整子群，Netflix 同一片库分别回答构成和片长问题；它们不应被计为六份独立数据。公开内容是预先计算的聚合报告，浏览和下载不创建分析任务，也不调用付费模型。仓库不附原始 CSV、逐人记录、演员名单或剧情文本。

## 来源、版本与校验

下载使用 Kaggle 官方公开接口并固定版本。文件 SHA-256 校验的是解压后的原始 CSV；只有字节匹配时才继续预处理。案例范围和清洗方法写入每份示例的来源说明。

| 数据集 | Kaggle 固定版本 | 原始文件 | 原始行 × 列 | 许可与署名 |
| --- | --- | --- | --- | --- |
| [Hotel booking demand](https://www.kaggle.com/datasets/jessemostipak/hotel-booking-demand) | 1 | `hotel_bookings.csv` | 119,390 × 32 | CC BY 4.0；Nuno Antonio、Ana de Almeida、Luis Nunes；Kaggle 整理由 Jesse Mostipak 发布 |
| [Default of Credit Card Clients](https://www.kaggle.com/datasets/uciml/default-of-credit-card-clients-dataset) | 1 | `UCI_Credit_Card.csv` | 30,000 × 25 | Kaggle 标注 CC0；原始 UCI 现标注 CC BY 4.0，保留 I-Cheng Yeh 与原研究署名 |
| [Heart Failure Prediction](https://www.kaggle.com/datasets/andrewmvd/heart-failure-clinical-data) | 1 | `heart_failure_clinical_records_dataset.csv` | 299 × 13 | CC BY 4.0；Kaggle 发布者 Larxel / `andrewmvd`，研究整理者 Davide Chicco、Giuseppe Jurman，并保留原始临床数据研究署名 |
| [Netflix Movies and TV Shows](https://www.kaggle.com/datasets/shivamb/netflix-shows) | 5 | `netflix_titles.csv` | 8,807 × 12 | Kaggle 标注 CC0；发布者 Shivam Bansal |

```text
hotel_bookings.csv
7c2ae42a7353905ea136e5c2287f17c92c5435826598bfbb8491c6f0c7b1fc06

UCI_Credit_Card.csv
a0f0ab49d6326671d6cd83be5c88dcf18007025fe9a53ecd699119c871176ca1

heart_failure_clinical_records_dataset.csv
9c73cea7468ff5d517801ec050fe9993da5912fce4b56f296f8df3b38dd75912

netflix_titles.csv
df1f4ad2027a5a14c3a33932ef0d4054565ff88adf92b7f263601b70fdc6f3f3
```

数据许可与本项目 AGPL-3.0-only 软件许可分别适用，来源署名与修改说明见 [第三方声明](../THIRD_PARTY_NOTICES.md)。金融数据的 Kaggle 和原始 UCI 许可标签不同，项目同时披露并保留原始署名，不声称 Kaggle 标签能消除上游义务。

## 案例与预处理

| 案例 ID | 面向读者的问题 | 分析范围与处理 |
| --- | --- | --- |
| `hotel-city-cancellations` | 哪类城市酒店预订值得提前确认？ | 完整 City Hotel 子群 79,330 行；保留取消目标和预订背景，移除代理/公司标识及事后状态等不适合解释候选的字段 |
| `hotel-resort-cancellations` | 度假酒店是否也有同样的取消模式？ | 完整 Resort Hotel 子群 40,060 行；采用相同规则。两子群合计覆盖原始 119,390 行，没有截取前 10 万行 |
| `credit-card-default` | 最近的还款延迟与下月违约怎样联系？ | 保留全部 30,000 行；移除 `ID`，类别编码按类别解释，不填补或删除真实客户 |
| `heart-failure-followup` | 随访中发生死亡的患者有哪些样本差异？ | 保留全部 299 行；将 `time` 明确为随访期，排除其作为入组时解释因素，不能靠随访时长得出“保护作用” |
| `netflix-catalog` | 这个历史片库里，电影和剧集各占多少？ | 全部 8,807 条目录记录；移除名称、人物名单和剧情等逐行文本；区分内容类型和内容分级 |
| `netflix-movie-length` | 一部电影通常有多长，不同发行年代有什么差异？ | 完整 6,131 条 Movie 子群；只从 `duration` 的“数字 min”解析 `movie_minutes`，6,128 个有效值，3 个缺失保持缺失，不混入剧集季数 |

Netflix 原始 `rating` 中有三条误放的片长值（`74 min`、`84 min`、`66 min`）。预处理把这些无效分级置为缺失，并记录修改；不把它们搬回 `duration`，也不猜测缺失分级。片长的有效样本始终是 6,128 条。分级缺失不能作为影片评价好坏的证据。

示例保留各自完整范围中的目标记录。不能因为信用卡移除 ID 后有 35 条特征相同记录就去重：不同 ID 仍代表不同客户。酒店中 `agent`、`company` 的 NULL 在原论文中表示“不适用”，移除这两个标识字段后也不应再把它们描述为业务数据大量缺失。

## 可直接复核的数字

下表是从固定原始数据独立汇总的核对点，便于检查案例是否跑偏。比例均使用表中的分母，不表示因果关系或经过外部验证的预测效果。

| 范围 | 核对点 |
| --- | --- |
| 城市酒店 | 取消 33,102 / 79,330，约 41.73%；取消预订的提前天数中位数为 115 天，未取消为 50 天 |
| 度假酒店 | 取消 11,122 / 40,060，约 27.76%；对应提前天数中位数为 109 天和 38 天 |
| 信用卡 | 下月违约 6,636 / 30,000，22.12%；`PAY_0=1` 组违约 1,252 / 3,688，约 33.95%；`PAY_0=2` 组 1,844 / 2,667，约 69.14% |
| 心衰随访 | 随访中记录死亡 96 / 299，约 32.11%；死亡组/未记录死亡组的射血分数中位数分别为 30% / 38%，血清肌酐分别为 1.3 / 1.0 mg/dL |
| Netflix 目录 | Movie 6,131 条、TV Show 2,676 条，合计 8,807 条 |
| Netflix 电影片长 | 6,128 个有效分钟值；中位数 98 分钟，第一/第三四分位数为 87 / 114 分钟 |

## 解读边界

### 商业：取消比例不等于一个政策的效果

酒店来自葡萄牙的两家酒店，计划到店时间覆盖 2015 年 7 月至 2017 年 8 月。不同月份覆盖的年份次数不同，不能拿月份原始总量直接断言旺季。ADR 是平均每日房价指标，取消数量也不能直接换算成实际损失收入。[原始论文](https://doi.org/10.1016/j.dib.2018.11.126)

`reservation_status` 和 `reservation_status_date` 包含结果信息，不能拿来解释取消发生前的风险。部分其他字段来自临近到店前的记录，并非预订创建时就已知。订金类型是从付款交易形成的类别，不是随机分配的政策实验；即使某类取消比例很高，也不能得出“收订金导致取消”或“取消订金就能改善”的结论。

### 金融：历史风险线索不能代替实际授信判断

该数据反映台湾地区 2005 年信用卡客户的还款历史，金额单位是新台币。`PAY_0` 是 9 月记录，`PAY_2` 至 `PAY_6` 对应 8 月至 4 月；不是六个连续、同间隔的数字变量。原始说明没有完整解释 `-2`、`0` 的含义，项目保留原编码，不把所有非正编码统称“正常还款”。`SEX`、`EDUCATION`、`MARRIAGE` 是类别，不能按编码大小解释为升降关系。[UCI 原始说明](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients)

样本中的组间差异不证明原因，不代表今天所有客户的风险，也不应变成依据性别、教育等属性分配授信的建议。较低额度与较多违约同时出现，不说明提高额度会降低违约。

### 医疗：随访时间会随着观察结果而变化

这是一组来自巴基斯坦 Faisalabad 两家机构的历史心衰患者记录，具有特定临床入组范围。随访期为 4 至 285 天，96 / 299 是随访期间观察到的死亡比例，不能说成统一 30 天、一年死亡风险或普通人群患病率。[原始数据与字段说明](https://archive.ics.uci.edu/dataset/519/heart+failure+clinical+records)

死亡可能结束一名患者的随访，因此 `time` 与结局的关联不意味着“随访越久越安全”。简单的二分类比例不是处理删失的生存模型。公开示例用于解释这种统计边界，不给诊断、治疗或个人预后建议；弱相关也不证明吸烟等因素对健康没有影响。[研究与数据背景](https://doi.org/10.1186/s12911-020-1023-5)

### 娱乐：目录记录不能回答用户爱看什么

Netflix 数据是截至 2021 年的历史片库快照，上架日期最晚为 2021-09-25；2021 年并非完整年，且快照可能不含此前已下架的作品。`release_year` 是作品发行年份，不是上架年份。`rating` 是内容/年龄分级，不是观众评分。`country` 是制作来源，不是观看地区；多国或多类型标签需要按多标签统计，不能把组合字符串当成一个国家。[数据发布说明](https://www.kaggle.com/datasets/shivamb/netflix-shows)

剧集时长字段以季数记录，电影以分钟记录，二者不应合并求平均。片库没有播放量、评分、订阅收入或个人偏好，所以案例只解释目录和片长，不能宣称发现观众需求、平台盈利策略或当前可观看内容。

## 本地复现

先按 [开发文档](development.md) 安装后端依赖，然后在仓库根目录执行：

```bash
PYTHONPATH=backend python scripts/build-cross-domain-examples.py --data-dir .local/cross-domain --download
```

构建脚本从固定 Kaggle 版本下载源文件，校验上面的 SHA-256，在本地预处理并调用项目分析流程，最后输出仅含聚合信息的公开快照。已有文件同样需要校验；源文件不匹配时应停止，不能用另一版本悄悄替代。脚本不需要模型密钥，也不调用在线模型。

每例均先经过文件读取、质量检查、完整 EDA 和解释生成。中间报告与生成清单保存在本地；公开快照单独允许分箱计数、分组汇总和解释进入，避免把原始散点或逐行预览带到公开页。来源说明中的事件编码、字段口径和事后字段排除由核验过的元数据提供；系统不会为任意上传文件猜测这些业务含义。

选定少量字段后，不同业务记录可能具有完全相同的值；这不证明原始来源有重复记录。因此新公开快照不提供`duplicate_rows`、`quality_score`，以`source.quality_scope='selected_fields'`说明范围；下载报告不根据这种投影给原始数据打质量分。记录未因同值而删除。

`.local/` 中保存原始下载与本地资料，并由 Git 忽略；公开的 `backend/app/example_data/` 仅保留聚合快照。发布前应核对预览为空、图表数据为聚合值、来源许可和预处理说明齐全，并检查源码、提交和图片中没有部署入口或私人凭据。
