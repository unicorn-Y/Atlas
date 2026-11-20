# X30 SSH authority 首批：有界独立审查

2026-11-16。原桌面GPT-6 Luna高负责生产实施。只读审查 ssh.py / test_ssh_execution_world.py 及安装版 asyncssh2.24.1相关源码；合成配置及连接替身纯内存复现，无文件写入/网络/服务/实际认证。不把首seam当全X30完成，也不重复MAP-02其余既定后续。

## 当前施工截点三项 major

1. **解析事实与连接目标不一致**：ssh.py:130 读 `config.get('HostName')`，AsyncSSH config.py:659内部键为 `Hostname`，get():510直接dict.get区分大小写；实际connect options在connection.py:7456读取Hostname。合成 Host review / HostName192.0.2.10，authority.hostname=review而实际parser=192.0.2.10。主控真实测试另已失败见VERIFICATION-06。需实际有效options同源构建authority与连接；不能只修显示字段后保留双解析。
2. **Include信任/身份变更复用旧池项**：ssh.py:156 digest只覆盖顶层文件，authority缺GlobalKnownHostsFile/IdentitiesOnly等有效策略。纯内存两例分别只改Include中上述一项，authority unchanged=True、reused=True、connect calls=1，独立于HostName错误。需有效Include和实际信任/身份策略变化触发新identity/失效。离线参数化回归避免用户.ssh或外网。
3. **Include-only精确alias入口回归**：ssh.py:117使用只手解析顶层的hosts()作为强制准入。顶层仅Include、子文件精确Host review时，AsyncSSH可解析192.0.2.30，manager却ValueError。准入需识别有效Include声明，保留拒绝未配置目标，不以放开全部host替代。

额外 Match final 语义边界已提示实施端：初次config pass并不必然等于connect最终配置（合成final Port2222，初次22）；应由同源最终有效配置提供事实及实际连接，后续回归验证。AsyncSSH2.24.1公开connect(options=...)仍construct克隆options，且可能canonical/final重载，不能把“传入同一个对象”当保证；验收应确认最终有效配置等价及配置不漂移，具体适配须尊重公开API实际语义。主控先前“同对象”的过强措辞已反馈更正。

以上均已通过原会话界面反馈Luna，待修复和独立复验。不把未证实的并发/资源清理问题额外列为缺陷。所有行号为此施工截点，后续可移动。

## 公开接口方案补充（设计建议，未算实施通过）

安装版AsyncSSH2.24.1公开 `SSHClientConnectionOptions.construct` 可用initial→必要的final→freeze生成配置快照；final对象直接传connect会继承reload=True并可能丢值，freeze应重置reload/final/canonical且config=None。公开connect仍克隆，测试应比有效字段与不重复读路径，不比对象is。DNS canonicalization另有异步解析/重载阶段，未实现时应显式拒绝并保留待补，不静默关掉冒充等价。

配置冻结不等于身份与trust材料冻结：construct可能重新load_keypairs，known_hosts可延迟读。严格同源需要连接消费同一次已解析身份/信任材料，且保留None/空集/默认值区别，known_hosts=None禁止作为省事方案。不得序列化options/私钥/完整配置/代理命令。

公开Options没有精确alias枚举接口；需要有限Include声明索引或版本约束解析观察层。AsyncSSH该版本相对Include以~/.ssh为基准，不能擅自按父配置目录解释。同步构造可能阻塞；construct走executor，取消await也不自动停止实际工作，因此prepare阶段不占池锁，准备完成后才决定入池。

依据仅安装包connection.py:479/:3558/:7395/:8243/:8401/:9297及config.py:86/:154/:395/:481；纯内存探针，无网络/真实认证。不是生产实现或新增独立缺陷。

## 原三项修复状态（当前稳定首批）

限定静态复核ssh.py及对应测试后，三项均已修：authority.host来自最终options并用于connect；有效config整体入digest且known_hosts含全局路径列表；Include精确声明递归发现并保留未知alias拒绝。主控联合11项通过及真实错误host-key拒绝另见VERIFICATION-06。

运行覆盖仍有限：IdentitiesOnly用例同时恢复known_hosts内容，不能由该段单独证明“仅该策略变化”引发新身份；GlobalKnownHostsFile暂无独立运行fixture。代码修复证据成立，这两点留作限定验证边界，不把原major保持未修。prepare→connect材料竞争、canonicalization及后续process/LSP/PTY/sandbox仍pending，不据此宣称全X30完成。
