/**
 * X2 用户界面（电脑操控 + 浏览器代理）挂载点说明 —— 供集成负责人（integration owner）参考。
 *
 * 现有确认卡片的挂载范式（照抄即可）：
 *   审批/提问卡片在 frontend/src/renderer/components/timeline.ts 的 buildTimeline() 里按事件类型
 *   生成时间线项（case 'approval.required' → { kind: 'approval' }），由
 *   frontend/src/renderer/components/ConversationActivity.tsx 的 TimelineRow 渲染
 *   （MessageThread 虚拟列表复用同一个 TimelineRow）。X2 的确认卡走同一条路。
 *
 * 建议挂载位置：
 *   1. ForegroundConfirmCard   timeline.ts 新增 case 'computer.foreground_required'，TimelineRow 渲染本卡；
 *                              props 取 event.data.reason / event.data.target，runId 用 event.runId。
 *   2. ComputerEdgeBar         App.tsx 会话区顶部固定条：当活动 run 出现 computer.foreground_required 且
 *                              尚未收到 computer.foreground_resumed 时渲染（覆盖在内容上方，fixed/top-0）。
 *   3. ComputerReplayPanel     Inspector 的「活动」标签页或设置页；runId 传要回放的电脑操控任务。
 *   4. BrowserHandoffCard      timeline.ts 新增 case 'browser.handoff_required'，TimelineRow 渲染本卡；
 *                              onOpenPanel 里把 event.data.url 交给 App.tsx 现有的浏览器面板状态（BrowserPanel）。
 *   5. BrowserRecorderPanel    浏览器面板（shell/panels/BrowserPanel.tsx）底部或侧栏；events 传活动 run 的
 *                              run.events（缺省时组件自己订阅全局事件流）。
 *   6. BrowserSettingsSection  pages/SettingsPage.tsx，参照 IntegrationPanel / DependencyCheckPanel 的挂法。
 *   7. ComputerStatusSection   pages/SettingsPage.tsx，参照 LspStatusSection（App.tsx 里的高级设置区）。
 *
 * 事件接线已就绪：services/runtimeEvents.ts 已认识 computer.foreground_required / computer.foreground_resumed /
 * computer.step / browser.handoff_required / browser.handoff_resolved / browser.panel.sync / browser.step，
 * 会随 run.events 正常流入；API 客户端见 services/x2Api.ts。
 */

export { default as ForegroundConfirmCard } from './ForegroundConfirmCard';
export { default as ComputerEdgeBar } from './ComputerEdgeBar';
export { default as ComputerReplayPanel, ComputerStepList } from './ComputerReplayPanel';
export { default as BrowserHandoffCard } from './BrowserHandoffCard';
export { default as BrowserRecorderPanel, SkillForm, SkillPreview, browserStepsFromEvents } from './BrowserRecorderPanel';
export { default as BrowserSettingsSection, BROWSER_MODES, VaultManager } from './BrowserSettingsSection';
export { default as ComputerStatusSection, ComputerDiagnostics } from './ComputerStatusSection';
