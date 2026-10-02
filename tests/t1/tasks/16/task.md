# checkpoint 后撤回旧方案

读取 `plan.json`，先建立明确 checkpoint。随后实际执行方案 A 并留下 `choice_a.txt`；按我要求 rewind 回 checkpoint，确认 A 已撤回，再换成方案 B。最终只保留方案 B 的结果和痕迹，不能留下 A 的文件或内容。
