# 隐盾后续执行计划

更新：2026-10-17。当前任务已完成本机与 GitHub 的实际融合。唯一维护根目录为本文件所在的 LLM-shield；源码只在 delivery/app。以 README、docs/执行状态.json 和 models/ACTIVE_MODELS.json 为当前入口，历史 BERT 实验记录不是在线配置。

## 已确定的架构

默认 GLiNER 开启，格式校验与语义检测分工，动作模型 feature v3，生成使用本机 DeepSeek 配置。对话、预览和单次处理共用 processing/material_processing。Campus NER 与预训练路径已移除；BERT 适配器只供离线比较，不能重新变成默认启动依赖。

本机 .env、上传资料、GLiNER 大权重和 local 私有文档不得推入 Git。D:/project-backups 保存合并前原目录和退役底座；不是另一份维护中的源码。不要从备份直接覆盖当前应用。

## 后续顺序

1. 用独立合成及经授权人工核对的材料测量 GLiNER 的地点、宿舍、机构和姓名边界，区分历史开发集与盲测。
2. 记录冷启动、稳定态 P50/P95 和大文件资源占用；只根据可复现瓶颈调整批量窗口和并发上限。
3. 在新增模型候选独立改善前，保持当前模型与特征版本匹配；禁止平均不同特征空间的动作权重。
4. 扩展表格统计时实现明确的本机查询和范围说明，不能把检索片段交给生成模型推断全表。
5. 用固定公开输入验证真实模型文案和边界；不会把用户原始名单拿去做联网调试。
6. 冻结后同步 Word/PPT，执行另一台机器的 Python、CUDA、权重恢复与启动验收。

运行软件检查使用 delivery/运行验证.cmd；实际 GLiNER 与真实对话的验证脚本为 delivery/app/scripts/verify_merged_runtime.py。当前检查结果见 docs/执行状态.json。
