/** 自动追新（Self-Evolution / X5-E7）的侧栏导航项定义。
 * 页面组件：frontend/src/renderer/pages/EvolutionPage.tsx（props: apiBaseUrl, onToast）。
 *
 * 接入点（shell wiring point）——需要修改以下两个【现有文件】，本文件不拥有它们：
 * 1. frontend/src/renderer/shell/Sidebar.tsx
 *    - `export type View`（第 11 行）联合类型追加 `'evolution'`；
 *    - `export const NAV`（第 13-21 行）追加 `{ view: 'evolution', label: '自动追新', icon: Sparkles }`
 *      （icon 从 lucide-react 引入）。
 * 2. frontend/src/renderer/App.tsx 主内容视图开关（第 992-998 行，`{view === 'board' && …}` 所在区块），
 *    在 `{view === 'skills' && …}` 之后并列追加：
 *      {view === 'evolution' && <EvolutionPage apiBaseUrl={store.apiBaseUrl} onToast={notify} />}
 *    并在文件头部 import EvolutionPage from './pages/EvolutionPage'。
 */
export const EVOLUTION_NAV: ReadonlyArray<{ id: 'evolution'; view: 'evolution'; label: string }> = [
  { id: 'evolution', view: 'evolution', label: '自动追新' },
];
