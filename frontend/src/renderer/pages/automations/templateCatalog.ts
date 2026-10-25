/** Versioned built-in automation templates; selected templates materialize once into normal records. */
export const AUTOMATION_TEMPLATE_CATALOG_VERSION = 1;

export interface AutomationTemplateParameter {
  key: string;
  label: string;
  defaultValue: string;
  placeholder?: string;
}

export interface AutomationTemplate {
  id: string;
  version: number;
  name: string;
  purpose: string;
  trigger: { kind: 'cron' | 'interval' | 'event' | 'webhook'; cron?: string; everyHours?: string; path?: string; glob?: string };
  parameters: AutomationTemplateParameter[];
  prompt: string;
}

export const AUTOMATION_TEMPLATES: readonly AutomationTemplate[] = [
  {
    id: 'weekday-brief', version: 1, name: '工作日简报', purpose: '每天汇总需要关注的项目变化，适合每日信息整理。',
    trigger: { kind: 'cron', cron: '0 9 * * 1-5' },
    parameters: [{ key: 'scope', label: '关注范围', defaultValue: '最近一天的项目活动' }, { key: 'format', label: '输出形式', defaultValue: '按优先级列出要点、来源和建议行动' }],
    prompt: '请检查 {{scope}}，整理成简洁的工作简报。{{format}}；没有可报告的变化时明确写“无更新”。',
  },
  {
    id: 'repo-health', version: 1, name: '仓库健康巡检', purpose: '按计划检查代码仓库的构建、测试和待处理问题。',
    trigger: { kind: 'cron', cron: '0 10 * * *' },
    parameters: [{ key: 'scope', label: '仓库或目录', defaultValue: '当前工作区' }, { key: 'checks', label: '检查项目', defaultValue: '未提交改动、失败测试、明显的依赖或构建问题' }],
    prompt: '巡检 {{scope}}。检查 {{checks}}。不要修改文件；报告发现、相关路径、复现线索和建议的下一步。',
  },
  {
    id: 'docs-watch', version: 1, name: '文档变更跟进', purpose: '文档目录有更新时检查内容并汇总需要跟进的事项。',
    trigger: { kind: 'event', path: '', glob: '*.md' },
    parameters: [{ key: 'folder', label: '监视目录', defaultValue: '', placeholder: 'C:\\Projects\\docs' }, { key: 'audience', label: '读者或关注点', defaultValue: '项目成员' }],
    prompt: '检查文档目录 {{folder}} 中发生变化的 Markdown 文件，面向 {{audience}}总结变更内容、待确认问题和后续行动。只报告真实读取到的变化。',
  },
];

export function materializeAutomationTemplate(template: AutomationTemplate, parameters: Record<string, string>): string {
  return template.prompt.replace(/\{\{([a-z][a-z0-9_]*)\}\}/gi, (placeholder, key: string) =>
    parameters[key] ?? template.parameters.find((item) => item.key === key)?.defaultValue ?? placeholder);
}
