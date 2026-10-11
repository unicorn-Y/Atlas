"""Atlas 工作台：挂在主体外面的独立本地 agent（挂件）。

每个挂件是 ``<DATA_ROOT>/data/workbench/agents/<id>/`` 下的一个文件夹：

- ``agent.json``  启动方式（字段沿用 ACP 注册表的 agent.json，加了 mode/env/permission 等）
- ``workspace/``  它干活的目录
- ``home/``       它自己的配置（``isolate_config`` 打开时，Claude/Codex 等的配置目录指到这里）
- ``sessions/``   它自己的会话记录（jsonl）
- ``bin/``        从注册表装的二进制

和主体隔离：独立进程；不给 Atlas 的 MCP/记忆；子进程环境去掉 ATLAS_*/HERMES_* 等变量；
主体的设置、技能、自我进化、追新都不碰这个目录。挂件的配置只能经工作台界面「解锁编辑」后修改，
版本钉死，只有用户点「升级」才换。
"""
