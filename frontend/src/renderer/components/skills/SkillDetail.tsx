import { useCallback, useEffect, useState } from 'react';
import { BookOpen, FileText, LoaderCircle, RefreshCw, User, X } from 'lucide-react';
import { getMarketSkill, type MarketSearchHit, type MarketSkillDetail } from '../../services/skillsMarketApi';
import InstallButton from './InstallButton';

const KINDS = [
  { id: 'user' as const, label: '用户目录', hint: '所有项目都能用' },
  { id: 'project' as const, label: '当前项目', hint: '只在这个项目里生效' },
];

/** 市场技能详情：元信息 + SKILL.md 预览 + 文件清单（放不下的收进 <details>）+ 安装。 */
export default function SkillDetail({ apiBaseUrl, hit, onClose, onInstalled }: {
  apiBaseUrl: string;
  hit: MarketSearchHit;
  onClose: () => void;
  onInstalled?: () => void;
}) {
  const [detail, setDetail] = useState<MarketSkillDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [scope, setScope] = useState<'user' | 'project'>('user');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setDetail(await getMarketSkill(apiBaseUrl, hit.source, hit.id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '技能详情读取失败，请稍后重试。');
      setDetail(null);
    } finally { setLoading(false); }
  }, [apiBaseUrl, hit.source, hit.id]);

  useEffect(() => { setDetail(null); void load(); }, [load]);

  return <aside aria-label="技能详情" className="card-surface flex min-h-0 flex-col gap-3 rounded-2xl p-4">
    <div className="flex items-start gap-2">
      <div className="min-w-0 flex-1">
        <h2 className="m-0 truncate text-[16px] font-semibold text-heading">{hit.name}</h2>
        <p className="m-0 mt-0.5 text-[12px] text-fg-3">来源 {hit.source} · {hit.id}</p>
      </div>
      <button type="button" aria-label="关闭详情" className="iconbtn" onClick={onClose}><X size={15} /></button>
    </div>

    {loading && <p role="status" className="m-0 flex items-center gap-2 text-[12.5px] text-fg-3"><LoaderCircle size={14} className="spin" />正在读取技能详情…</p>}
    {error && <div role="alert" className="flex flex-wrap items-center gap-2 rounded-[10px] bg-danger-soft px-3 py-2 text-[12.5px] text-danger">
      <span className="min-w-0 flex-1">{error}</span>
      <button type="button" className="btn ghost" onClick={() => void load()}><RefreshCw size={14} />重试</button>
    </div>}

    {detail && <>
      <p className="m-0 text-[13px] leading-relaxed text-fg-2">{detail.description || '作者没有写介绍。'}</p>
      <dl className="m-0 grid grid-cols-2 gap-2 text-[12.5px]">
        <div><dt className="text-fg-3">版本</dt><dd className="m-0 text-fg">{detail.version}</dd></div>
        <div><dt className="text-fg-3">作者</dt><dd className="m-0 flex items-center gap-1 text-fg">{detail.author ? <><User size={12} />{detail.author}</> : '未知'}</dd></div>
        <div><dt className="text-fg-3">文件数</dt><dd className="m-0 text-fg">{detail.files.length}</dd></div>
        <div><dt className="text-fg-3">SKILL.md</dt><dd className="m-0 text-fg">{detail.skill_md ? '有说明文档' : '没有'}</dd></div>
      </dl>

      <fieldset className="m-0 border-0 p-0" aria-label="安装位置">
        <legend className="mb-1 p-0 text-[12px] text-fg-3">装到哪里</legend>
        <div className="seg">
          {KINDS.map((item) => <button key={item.id} type="button" aria-pressed={scope === item.id}
            title={item.hint} onClick={() => setScope(item.id)}>{item.label}</button>)}
        </div>
      </fieldset>

      <div className="flex items-center gap-2">
        <InstallButton apiBaseUrl={apiBaseUrl} source={hit.source} id={hit.id} scope={scope} onInstalled={() => onInstalled?.()} />
      </div>

      {detail.skill_md && <details open className="min-h-0">
        <summary className="flex cursor-pointer select-none items-center gap-1.5 text-[12.5px] text-fg-2 hover:text-fg"><BookOpen size={14} />SKILL.md 预览</summary>
        <pre className="mt-2 max-h-[280px] overflow-auto whitespace-pre-wrap break-words rounded-[10px] bg-sunken p-3 font-mono text-[11.5px] leading-[1.6] text-fg-2">{detail.skill_md}</pre>
      </details>}
      {detail.files.length > 0 && <details>
        <summary className="flex cursor-pointer select-none items-center gap-1.5 text-[12.5px] text-fg-2 hover:text-fg"><FileText size={14} />文件清单（{detail.files.length}）</summary>
        <ul className="m-0 mt-2 max-h-[180px] list-none overflow-auto p-0">
          {detail.files.map((file) => <li key={file.path} className="truncate rounded-md px-2 py-1 font-mono text-[11.5px] text-fg-3 hover:bg-hover hover:text-fg-2">{file.path}</li>)}
        </ul>
      </details>}
    </>}
  </aside>;
}
