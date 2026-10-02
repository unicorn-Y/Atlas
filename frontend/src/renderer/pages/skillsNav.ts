import { Puzzle } from 'lucide-react';

/** 侧栏「技能」入口的导航常量，供集成负责人接入外壳时使用。 */
export const SKILLS_NAV = {
  /** 侧栏视图 id：shell/Sidebar.tsx 的 `View` 联合类型里已经包含 'skills'。 */
  view: 'skills' as const,
  label: '技能',
  icon: Puzzle,
  page: 'SkillsMarketPage',
  /** 页面内部三个标签页（SkillsMarketPage 的 initialTab 取值）。 */
  tabs: [
    { id: 'market', label: '市场' },
    { id: 'installed', label: '已安装' },
    { id: 'updates', label: '更新' },
  ] as const,
};

/*
 * 接线说明（集成负责人）：
 * 1. 侧栏不用改：frontend/src/renderer/shell/Sidebar.tsx 顶部 NAV 数组第 20 行已有
 *    `{ view: 'skills', label: '技能', icon: Puzzle }`，`View` 类型（第 11 行）也已含 'skills'。
 * 2. App.tsx 第 998 行是唯一的挂载点：
 *      {view === 'skills' && <div className="screen"><SkillDiscoveryPage apiBaseUrl={store.apiBaseUrl} activeSkills={store.activeSkills} onApplySkill={...} /></div>}
 *    把其中的 <SkillDiscoveryPage ... /> 换成
 *      <SkillsMarketPage
 *        apiBaseUrl={store.apiBaseUrl}
 *        onToast={notify}                       // App.tsx 里现成的 toast 回调
 *        onTryInConversation={(name) => { store.applySkill(name); go('chat'); }}
 *      />
 *    外层 <div className="screen"> 保留。旧的 SkillDiscoveryPage（技能发现/安全审查）可保留为
 *    SkillsMarketPage 的一个入口或后续再合并，两者互不依赖。
 */
