# 研究卡片数据契约 v0.1

每篇文献输出一份结构化记录。后续将据此生成 JSON Schema。

## 身份与来源

- `paper_id`：内部稳定 ID
- `doi` / `external_id` / `source_url`
- `title`
- `authors`
- `year`
- `venue`
- `document_access`：`full_text`、`abstract_only` 或 `unavailable`

## 筛选信息

- `gnss_domain`：GNSS 子领域标签
- `product_relevance`：0–5
- `scientific_quality`：0–5
- `novelty`：0–5
- `screening_decision`：`include`、`exclude` 或 `review`
- `screening_reason`

## 深读信息

- `problem`
- `method`
- `data_and_experiment`
- `key_findings`
- `limitations`
- `applicable_conditions`
- `comparison_baselines`
- `technology_readiness`

## 产品分析

- `product_implications`
- `opportunities`
- `risks`
- `recommended_actions`

## 证据

每条核心发现均须包含：

- `claim`
- `evidence`
- `locator`：页码、章节、图或表编号
- `confidence`：`high`、`medium` 或 `low`

## 处理与质控

- `reader_agent_id`
- `model`
- `prompt_version`
- `processed_at`
- `verification_status`
- `quality_score`
- `failure_reason`
