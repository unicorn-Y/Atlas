import { useEffect, useState } from 'react';
import {
  AudioLines, Download, FileSpreadsheet, FileText, Film, ImageIcon, LoaderCircle, Phone, Presentation, Sparkles, Wand2,
} from 'lucide-react';
import { api } from '../services/api';

interface CreatePageProps {
  onDraft: (text: string) => void;
  onVoice: () => void;
  apiBaseUrl: string;
  connected: boolean;
  onToast: (text: string) => void;
  workspace?: string | null;
  /** A prompt handed over from the home composer's 图像 mode. */
  initialPrompt?: string;
}

type Tab = 'image' | 'video' | 'voice' | 'office';
interface Shot { url?: string; b64?: string }
type OfficeKind = 'docx' | 'xlsx' | 'pptx';
interface OfficeTemplate { id: string; name: string; description: string; structure: string[]; fields: string[] }
const OFFICE_TEMPLATES: Record<OfficeKind, OfficeTemplate[]> = {
  docx: [
    { id: 'report', name: '项目报告', description: '结论清晰、适合评审与归档', structure: ['标题与摘要', '背景与目标', '现状与关键发现', '方案与执行计划', '风险及应对', '结论与后续行动'], fields: ['报告标题', '执行摘要', '背景和目标', '发现及证据', '推荐方案', '负责人和日期', '风险、缓解措施和后续行动'] },
    { id: 'meeting', name: '会议纪要', description: '讨论、决策、负责人和期限一目了然', structure: ['会议主题、时间、参与者', '议题与讨论摘要', '决策记录', '行动项表格', '待确认问题'], fields: ['会议主题', '日期与时区', '参与者', '议题', '讨论结论', '决策', '行动事项', '负责人', '截止日期', '状态', '待确认问题'] },
    { id: 'proposal', name: '项目提案', description: '从问题、方案到成本和衡量指标', structure: ['提案摘要', '问题与机会', '目标与成功指标', '推荐方案及备选方案', '范围、里程碑与资源', '风险、成本及审批事项'], fields: ['问题和机会', '目标指标', '方案比较', '范围和排除项', '里程碑', '人员与成本', '风险和缓解', '审批人', '决策日期'] },
  ],
  xlsx: [
    { id: 'budget', name: '预算跟踪表', description: '计划、实际、差额及汇总', structure: ['预算概览', '支出明细', '口径与假设说明'], fields: ['概览：类别、预算、实际、差额、使用率', '明细：日期、类别、说明、预算、实际、负责人', '说明：币种、税费口径、来源、假设、更新时间'], },
    { id: 'tasks', name: '任务跟踪表', description: '负责人、状态、优先级和截止日期', structure: ['任务清单', '里程碑', '状态口径说明'], fields: ['任务：ID、任务、负责人、优先级、状态、开始日期、截止日期、依赖、备注', '里程碑：名称、日期、负责人、状态', '状态值与优先级定义'], },
    { id: 'analysis', name: '数据分析工作簿', description: '原始数据、指标汇总和口径说明', structure: ['原始数据表', '指标汇总表', '来源与口径说明'], fields: ['原始数据列名与数据类型', '指标、数值、单位、计算口径', '来源、筛选条件、假设、缺失值、更新时间'], },
  ],
  pptx: [
    { id: 'update', name: '项目进展汇报', description: '面向干系人的进展、风险与决策请求', structure: ['标题与汇报日期', '执行摘要', '目标与范围', '进展和成果', '计划与里程碑', '风险及应对', '需要的决策与下一步'], fields: ['项目名和汇报日期', '状态和关键指标', '已完成成果', '未完成事项和负责人', '里程碑日期', '风险、影响和应对', '决策请求与所需时间'] },
    { id: 'pitch', name: '产品方案介绍', description: '面向客户或决策者的方案叙事', structure: ['标题与一句话价值', '用户问题', '解决方案', '关键能力与使用流程', '差异化与证据', '实施计划', '价值指标与行动请求'], fields: ['目标用户', '痛点和证据', '方案价值主张', '功能与流程', '差异化依据', '实施阶段和时间', '预期指标', '行动请求'] },
    { id: 'training', name: '培训课件', description: '教学目标、讲解、练习与回顾', structure: ['课程标题和学习目标', '概念与示例', '分步操作', '练习任务', '常见问题', '总结与后续资源'], fields: ['受众和前置知识', '可验证学习目标', '术语和示例', '操作步骤', '练习说明和参考答案', '常见错误', '延伸资源'] },
  ],
};

const STYLES = ['写实摄影', '电影质感', '日系插画', '3D 渲染', '国风水墨', '赛博朋克', '极简扁平', '梦幻唯美'];
const RATIOS: { id: string; label: string; size: string; box: string }[] = [
  { id: 'square', label: '方形', size: '1024x1024', box: '1 / 1' },
  { id: 'wide', label: '横向', size: '1536x1024', box: '3 / 2' },
  { id: 'tall', label: '纵向', size: '1024x1536', box: '2 / 3' },
];
const COUNTS = [1, 2, 4];
const IMAGE_MODEL = 'gpt-image-1';

const shotSrc = (shot: Shot) => shot.url ?? (shot.b64 ? `data:image/png;base64,${shot.b64}` : '');

export default function CreatePage({ onDraft, onVoice, apiBaseUrl, connected, onToast, initialPrompt, workspace }: CreatePageProps) {
  const [tab, setTab] = useState<Tab>('image');
  useEffect(() => {
    if (!initialPrompt) return;
    setTab('image');
    setPrompt(initialPrompt);
  }, [initialPrompt]);

  // Image studio state
  const [prompt, setPrompt] = useState('');
  const [style, setStyle] = useState('');
  const [ratio, setRatio] = useState(RATIOS[0]);
  const [count, setCount] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [shots, setShots] = useState<Shot[]>([]);
  const [officeKind, setOfficeKind] = useState<OfficeKind>('docx');
  const [officeTemplate, setOfficeTemplate] = useState('report');
  const [officeSubject, setOfficeSubject] = useState('');
  const [officePath, setOfficePath] = useState('deliverables/project-report.docx');
  const templates = OFFICE_TEMPLATES[officeKind];
  const template = templates.find((item) => item.id === officeTemplate) ?? templates[0];
  const selectOfficeKind = (kind: OfficeKind) => {
    setOfficeKind(kind);
    setOfficeTemplate(OFFICE_TEMPLATES[kind][0].id);
    setOfficePath((current) => current.replace(/\.(docx|xlsx|pptx)$/i, `.${kind}`));
  };
  const startOfficeDraft = () => {
    const targetPath = officePath.trim().replace(/\\/g, '/');
    const subject = officeSubject.trim() || '请根据当前对话和项目工作区确定主题，并在必要时先询问我';
    const tool = officeKind === 'docx' ? 'create_document' : officeKind === 'xlsx' ? 'create_spreadsheet' : 'create_presentation';
    const prompt = [
      `请使用现有 ${tool} 工具创建一个 ${officeKind.toUpperCase()} 文件，完成后核实文件可以读取。`,
      `主题：${subject}`,
      `目标路径：${targetPath}（相对于当前工作区根目录；工作区：${workspace || '当前会话工作区'}）`,
      `所选模板：${template.name}。模板说明：${template.description}。`,
      `必须按以下结构逐项起稿：\n${template.structure.map((item, index) => `${index + 1}. ${item}`).join('\n')}`,
      `必须体现以下字段：\n${template.fields.map((item, index) => `${index + 1}. ${item}`).join('\n')}`,
      '根据主题补全具体内容，不要保留空白占位符。缺少可靠事实时标注待确认；表格应包含清楚的列名。将结构和字段转换为工具要求的 blocks、sheets 或 slides 参数，并把目标路径原样传给工具。',
    ].join('\n\n');
    onDraft(prompt);
  };

  const generate = async () => {
    const text = prompt.trim();
    if (!text) return;
    const full = style ? `${text}，${style}风格` : text;
    setBusy(true);
    setError('');
    try {
      const body = await api<{ images: Shot[] }>(apiBaseUrl, '/api/images/generate', {
        method: 'POST',
        json: { prompt: full, model: IMAGE_MODEL, size: ratio.size, n: count },
      });
      setShots(body.images ?? []);
      if (!body.images?.length) setError('网关没有返回图像。');
      else onToast(`生成了 ${body.images.length} 张图`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const download = (shot: Shot, index: number) => {
    const src = shotSrc(shot);
    if (!src) return;
    const a = document.createElement('a');
    a.href = src;
    a.download = `atlas-${Date.now()}-${index + 1}.png`;
    a.click();
  };

  return (
    <div className="screen page">
      <div className="page-inner">
        <header className="page-head">
          <div>
            <h1>创作</h1>
            <p>图像、视频、实时语音，集中在一处。描述你想要的，Atlas 帮你把它变出来。</p>
          </div>
        </header>

        <div className="seg" role="tablist" style={{ marginBottom: 20 }}>
          <button role="tab" aria-pressed={tab === 'image'} onClick={() => setTab('image')}>
            <ImageIcon size={15} style={{ marginRight: 6, verticalAlign: '-2px' }} />图像
          </button>
          <button role="tab" aria-pressed={tab === 'video'} onClick={() => setTab('video')}>
            <Film size={15} style={{ marginRight: 6, verticalAlign: '-2px' }} />视频
          </button>
          <button role="tab" aria-pressed={tab === 'voice'} onClick={() => setTab('voice')}>
            <AudioLines size={15} style={{ marginRight: 6, verticalAlign: '-2px' }} />语音
          </button>
          <button role="tab" aria-pressed={tab === 'office'} onClick={() => setTab('office')}>
            <FileText size={15} style={{ marginRight: 6, verticalAlign: '-2px' }} />Office 起稿
          </button>
        </div>

        {tab === 'office' && (
          <section className="glass panel grid gap-5" aria-label="Office 模板起稿">
            <div>
              <h2 className="m-0 text-[17px] font-semibold text-heading">从模板开始起稿</h2>
              <p className="mb-0 mt-1 text-[13px] text-fg-3">选产物类型和结构，Atlas 会把起稿说明放进新对话，并调用现有 Office 生成工具。</p>
            </div>
            <div className="grid gap-2">
              <span className="cap">产物类型</span>
              <div className="seg" role="group" aria-label="Office 产物类型">
                <button aria-pressed={officeKind === 'docx'} onClick={() => selectOfficeKind('docx')}><FileText size={14} className="mr-1 inline" />Word 文档</button>
                <button aria-pressed={officeKind === 'xlsx'} onClick={() => selectOfficeKind('xlsx')}><FileSpreadsheet size={14} className="mr-1 inline" />Excel 表格</button>
                <button aria-pressed={officeKind === 'pptx'} onClick={() => selectOfficeKind('pptx')}><Presentation size={14} className="mr-1 inline" />PowerPoint</button>
              </div>
            </div>
            <label className="grid gap-2 text-[12px] text-fg-3">模板
              <select value={officeTemplate} onChange={(event) => setOfficeTemplate(event.target.value)} className="input">
                {templates.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.description}</option>)}
              </select>
            </label>
            {template && <div className="rounded-xl bg-sunken p-3.5" aria-label="模板结构预览">
              <div className="mb-2 text-[12px] font-medium text-fg">模板结构</div>
              <ol className="m-0 grid gap-1 pl-5 text-[12px] leading-[1.6] text-fg-2">{template.structure.map((item) => <li key={item}>{item}</li>)}</ol>
              <div className="mb-2 mt-3 text-[12px] font-medium text-fg">字段要求</div>
              <ul className="m-0 grid gap-1 pl-5 text-[12px] leading-[1.6] text-fg-2">{template.fields.map((item) => <li key={item}>{item}</li>)}</ul>
            </div>}
            <div className="grid gap-3 md:grid-cols-2">
              <label className="grid gap-2 text-[12px] text-fg-3">主题或用途
                <input value={officeSubject} onChange={(event) => setOfficeSubject(event.target.value)} className="input" placeholder="例如：Q4 产品发布复盘" />
              </label>
              <label className="grid gap-2 text-[12px] text-fg-3">工作区内目标路径
                <input value={officePath} onChange={(event) => setOfficePath(event.target.value)} className="input" placeholder={`deliverables/draft.${officeKind}`} />
              </label>
            </div>
            <p className="m-0 text-[11.5px] text-fg-3">工作区：{workspace || '新对话将使用默认工作区'}。生成工具要求文件保存在工作区内。</p>
            <div className="flex justify-end">
              <button className="btn primary" disabled={!officePath.trim()} onClick={startOfficeDraft}><Wand2 size={15} />带着模板开始写</button>
            </div>
          </section>
        )}

        {tab === 'image' && (
          <div className="studio">
            <div className="glass panel">
              <div className="composer" style={{ boxShadow: 'none', marginBottom: 16 }}>
                <textarea
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder="描述你想要的画面，例如：黄昏时分海边的灯塔，暖色调，远处有归航的船"
                  rows={2}
                  onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) generate(); }}
                />
              </div>

              <div className="cap">风格</div>
              <div className="presets">
                {STYLES.map((s) => (
                  <button key={s} aria-pressed={style === s} onClick={() => setStyle(style === s ? '' : s)}>{s}</button>
                ))}
              </div>

              <div className="studio-row">
                <div>
                  <div className="cap">画幅</div>
                  <div className="seg">
                    {RATIOS.map((r) => (
                      <button key={r.id} aria-pressed={ratio.id === r.id} onClick={() => setRatio(r)}>{r.label}</button>
                    ))}
                  </div>
                </div>
                <div>
                  <div className="cap">数量</div>
                  <div className="seg">
                    {COUNTS.map((c) => (
                      <button key={c} aria-pressed={count === c} onClick={() => setCount(c)}>{c}</button>
                    ))}
                  </div>
                </div>
                <button className="btn primary" style={{ marginLeft: 'auto', alignSelf: 'flex-end', height: 40, padding: '0 22px' }} disabled={!connected || busy || !prompt.trim()} onClick={generate}>
                  {busy ? <LoaderCircle size={16} className="spin" /> : <Sparkles size={16} />}
                  {busy ? '生成中…' : '生成'}
                </button>
              </div>
            </div>

            {error && (
              <div className="error-note">
                <span><Wand2 size={15} style={{ verticalAlign: '-2px', marginRight: 8 }} />{error}</span>
                <button className="btn ghost" onClick={() => onDraft(`帮我把这个画面想法写成一段详细的英文图像生成提示词：${prompt}`)}>让 Atlas 优化提示词</button>
              </div>
            )}

            {busy && (
              <div className="studio-grid">
                {Array.from({ length: count }).map((_, i) => (
                  <div key={i} className="shot skel" style={{ aspectRatio: ratio.box }} />
                ))}
              </div>
            )}

            {!busy && shots.length > 0 && (
              <div className="studio-grid">
                {shots.map((shot, i) => (
                  <div key={i} className="shot" style={{ aspectRatio: ratio.box }}>
                    <img src={shotSrc(shot)} alt={`生成结果 ${i + 1}`} />
                    <button className="shot-dl" title="下载" onClick={() => download(shot, i)}><Download size={15} /></button>
                  </div>
                ))}
              </div>
            )}

            {!busy && shots.length === 0 && !error && (
              <div className="studio-empty">
                <ImageIcon size={26} style={{ marginBottom: 10, opacity: 0.6 }} />
                <p style={{ margin: 0 }}>写下画面描述，选好风格与画幅，点「生成」。</p>
                <p style={{ margin: '6px 0 0', fontSize: 12.5 }}>图像走 {IMAGE_MODEL}，需网关已开通图像生成权限。</p>
              </div>
            )}
          </div>
        )}

        {tab === 'video' && (
          <div className="studio">
            <div className="glass panel studio-hero">
              <span className="ico ether"><Film size={20} /></span>
              <h3>视频生成</h3>
              <p>短片、产品演示、动态海报——从文字或图片生成。视频模型接入网关后即可在这里直接出片。</p>
              <span className="tag">尚未接入</span>
              <div className="btns" style={{ marginTop: 16 }}>
                <button className="btn primary" onClick={() => onDraft('帮我把这个视频想法写成分镜脚本，每个镜头写清画面、运镜、时长和字幕：')}>
                  <Wand2 size={15} />先写分镜脚本
                </button>
              </div>
            </div>
          </div>
        )}

        {tab === 'voice' && (
          <div className="studio">
            <div className="glass panel studio-hero">
              <span className="ico ok"><AudioLines size={20} /></span>
              <h3>实时语音通话</h3>
              <p>像打电话一样和 Atlas 说话，可随时打断。目前使用本机语音识别与朗读。</p>
              <span className="tag" style={{ color: 'var(--ok)', background: 'var(--ok-soft)' }}>可以使用</span>
              <div className="btns" style={{ marginTop: 16 }}>
                <button className="btn primary" onClick={onVoice}><Phone size={15} />开始通话</button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
