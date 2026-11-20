# 隔离基准的模型认证来源：静态核对

2026-11-16。只读代码研究，未读实际配置/认证存储/密钥，未联网/模型/服务，无生产修改。供桌面Luna在安装批次后定位，不构成认证根因证明。

## 已确认标准接线

- omni_bench.py:442/472/485：复制仓库TOML进临时根，设置ATLAS_DATA_DIR/ATLAS_HOME，保留ATLAS_ROOT；未复制user-settings或credentials，未重设HOME/USERPROFILE/APPDATA；没有直接改写model/key/base_url。
- config.py:24/49/53：DATA_ROOT在导入时由ATLAS_DATA_DIR决定；user settings定位临时根data/user-settings.json，缺失返回空表。ATLAS_HOME不是该路径开关。
- models/__init__.py:124/445/613：provider key元数据索引来自settings；没有key ID就不会查询对应OS凭据account，转env/None。settings同ID模型覆盖TOML并标custom=True(:126/:662/:679)，单复制TOML可能改变model-specific key分支。
- secrets_store.py:12/99/118：named secret元数据/加密文件/key位于DATA_ROOT/data；metadata不存在就不继续查keyring；resolve_handles无法解析会抛ValueError。尚未发现当前config/ModelManager/kernel链调用其展开函数，不能把named-secret失联直接归因认证。
- kernel/model_call.py:755/810/910：complete_stream用agent._model_router，resolve(candidate, conversation)→router.stream；models/__init__.py:205创建ModelRouter。router.py:784/1085最终HTTPX，当前conversation不是文档旧称LiteLLM路径。
- router.py:229/240/266/279选择provider/model/pool/gateway key和endpoint；:166 wire_model取native或去第一个斜线前缀，:731/752构造payload，:545补chat/completions。存在转换不等于本次转换错误。

## 唯一可证的隔离差异机制（有条件）

只复制TOML→临时settings路径→若初始化时缺provider key metadata，则ModelManager无法按原key ID查询OS account→回退env/None→可能不同于桌面。这个机制证明本地来源可能变化，不证明远端authentication原因。

反证边界：config.py:352 load_config先migrate_configuration再overlay，初始化时settings未必为空，迁移实现未审；gateway另有env/TOML/凭据库路径(:219)。credential_present=True不证明是有效key，也不证明等于发送对象。agent router实际赋值/失败现场对象仍未采集。

## 后续最小诊断

由桌面Luna在既定的一次有界请求上，从同次正常解析和最终发送对象生成白名单标签+布尔比较，再scrub：credential来源/输入类型/引用解析是否成功、route与send key是否内存相等、selected/wire model、endpoint是否匹配已批准host/path、是否query/userinfo、transport、实际总attempt数。不要key/片段/hash/header/raw config/原始异常正文，不另读认证文件，不自动复制认证资料或改模型/网关/账号。

一次turn可能含MoA/标题/辅助/fallback/transport retry，单次诊断应在最终transport限制总请求次数，不能用turn=1冒充调用=1。当前根因仍未定；静态机制high，归因此次authentication low。
