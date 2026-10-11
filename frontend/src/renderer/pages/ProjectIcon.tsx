import { BookOpen, Code2, FolderGit2, Sparkles, Terminal } from 'lucide-react';

export const PROJECT_ICON_OPTIONS = [
  { value: 'folder', label: '文件夹' },
  { value: 'code', label: '代码' },
  { value: 'terminal', label: '终端' },
  { value: 'book', label: '文档' },
  { value: 'sparkles', label: '灵感' },
] as const;

export function ProjectIcon({ icon, color, size = 17 }: { icon?: string; color?: string; size?: number }) {
  const Icon = icon === 'code' ? Code2
    : icon === 'terminal' ? Terminal
      : icon === 'book' ? BookOpen
        : icon === 'sparkles' ? Sparkles : FolderGit2;
  return <Icon size={size} style={color ? { color } : undefined} aria-hidden="true" />;
}
