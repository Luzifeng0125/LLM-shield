# 隐盾应用

应用只有这一份实现。入口为仓库根目录的“启动隐盾.cmd”，端口 8787。代码与本机 GLiNER 权重都在本目录内；密钥从 .env 读取。

对话、预览、单次运行共用 processing.py 和 material_processing.py；GLiNER 单例加载，批量处理材料窗口。格式标识符由正则与校验规则识别，语义类别由 GLiNER 与词典补充。动作模型 feature v3 与其权重配套，不兼容的候选不能直接替换。

Campus NER 已移除。eval/reviewed_ner.py 仅由离线 BERT 比较脚本显式使用，在线识别管线没有该模型开关。模型清单见 models/ACTIVE_MODELS.json；安装和验证命令见根目录 README。

config、web、tests 分别保存配置、前端与回归；data/uploads、outputs、.env 和本机大权重被 Git 忽略。/api/health 用于就绪检查，/api/metrics 返回有界的阶段耗时统计。
