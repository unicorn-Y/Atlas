import { useState } from 'react';
import {
  AudioLines, Download, Film, ImageIcon, LoaderCircle, Phone, Sparkles, Wand2,
} from 'lucide-react';
import { api } from '../services/api';

interface CreatePageProps {
  onDraft: (text: string) => void;
  onVoice: () => void;
  apiBaseUrl: string;
  connected: boolean;
  onToast: (text: string) => void;
}

type Tab = 'image' | 'video' | 'voice';
interface Shot { url?: string; b64?: string }

const STYLES = ['写实摄影', '电影质感', '日系插画', '3D 渲染', '国风水墨', '赛博朋克', '极简扁平', '梦幻唯美'];
const RATIOS: { id: string; label: string; size: string; box: string }[] = [
  { id: 'square', label: '方形', size: '1024x1024', box: '1 / 1' },
  { id: 'wide', label: '横向', size: '1536x1024', box: '3 / 2' },
  { id: 'tall', label: '纵向', size: '1024x1536', box: '2 / 3' },
];
const COUNTS = [1, 2, 4];
const IMAGE_MODEL = 'gpt-image-1';

const shotSrc = (shot: Shot) => shot.url ?? (shot.b64 ? `data:image/png;base64,${shot.b64}` : '');

export default function CreatePage({ onDraft, onVoice, apiBaseUrl, connected, onToast }: CreatePageProps) {
  const [tab, setTab] = useState<Tab>('image');

  // Image studio state
  const [prompt, setPrompt] = useState('');
  const [style, setStyle] = useState('');
  const [ratio, setRatio] = useState(RATIOS[0]);
  const [count, setCount] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [shots, setShots] = useState<Shot[]>([]);

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
        </div>

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
