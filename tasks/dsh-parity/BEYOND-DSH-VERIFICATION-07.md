# 模型重试文本混合：离线生产函数复现

2026-11-16。独立只读诊断；原桌面Luna正在X30，本文供后续MAP-03增量，不打断当前实施。无生产/测试文件修改，无网络/模型/服务/实际配置认证/data读取。不是修复通过。

## 实际复现

将当前生产model_call.py直接compile/exec到内存模块，保留原repair.py/error_classifier.py/fallback_cooldown.py，共享重试/合并算法未改写。stub配置读取、token估算、诊断存储及模型路由。fake attempt1输出OLD后ConnectionError，attempt2输出NEW并成功。

三例：无tool delta、失败attempt完整tool参数、失败attempt截断tool参数。均返回ModelCallResult.text=OLDNEW，attempts=2；on_text=[OLD,NEW]；on_attempt=[失败connection重试,成功]；诊断stub结束状态[error,ok]且requestId分别配对；两fake流均关闭。最终tool_calls只含成功attempt的new/value=NEW，失败参数虽流回调可见但未混入最终返回。本证据不支持“失败参数会被执行”的扩大判断。

子进程自然exit0、工具外层30秒/子27秒上限；源码前后字节相同，audit hook无被禁止的网络/写入/进程操作。以随机未创建路径隔离HOME/USERPROFILE/APPDATA/ATLAS_DATA_DIR/ATLAS_HOME；-I -S -B，纯内存模块阻止未stub Atlas导入。stderr非空且白名单类型标记未命中，来源未定，不能称零stderr。

## 数据流

- model_call.py:769 combined_text在候选/attempt循环外；:851每次重建attempt_text/attempt_tools。
- :970合并attempt文本到combined_text；_overlap_merge:146无重叠即拼接；:1075成功返回combined_text。
- 工具最终解析来自当前attempt_tools；:1256失败回调含错误与重试信息，不含失败文本payload。
- loop.py:2872/:2963有response.text到assistant持久化路径，仅静态核对，本次未跑真实kernel/UI/DB。

## 后续验收

由原桌面Luna在X30后实现成功attempt文本提交、失败attempt独立审计及流式撤回/替换语义。仅改最终返回而仍显示OLDNEW不能算完整解决。保留现有跨fallback总预算、取消、错误分类。真实kernel/fake-provider验证不同答案、相同前缀、工具delta、取消及持久化；桌面新事件按三真源同步。

置信度high：当前生产函数文本隔离缺口确定性复现；真实审计落盘/工具执行/UI未验，不扩为完整系统结论。
