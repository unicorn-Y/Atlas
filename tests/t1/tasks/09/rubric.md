# 评分要点

- 明确说明配置值优先解析；未配置时先询问 small-model 插件。
- 正确处理 Azure 无可选模型特例和各 provider 的 family 优先级。
- 候选按 release date、model id 降序；说明 Bedrock 跨区域候选顺序和区域过滤。
- 事实逐项给出 pinned 源码路径和行号，结构化表达且无臆造。
