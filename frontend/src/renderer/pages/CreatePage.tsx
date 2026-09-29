import { AudioLines, Film, ImageIcon } from 'lucide-react';

interface CreatePageProps {
  onDraft: (text: string) => void;
  onVoice: () => void;
}

export default function CreatePage({ onDraft, onVoice }: CreatePageProps) {
  return <div className="screen page"><div className="page-inner">
    <header className="page-head">
      <div><h1>创作</h1><p>图像、视频和实时语音会集中在这里。生成模型接入之前，可以先让 Atlas 帮你把想法写成能直接用的描述。</p></div>
    </header>
    <div className="soon">
      <div className="glass">
        <span className="ico brass"><ImageIcon size={18} /></span>
        <h3>图像生成</h3>
        <p>海报、插画、配图、头像。接入图像模型后，在对话里直接说「画一张…」就能出图。</p>
        <span className="tag">尚未接入</span>
        <div className="btns" style={{ marginTop: 14 }}><button className="btn" onClick={() => onDraft('帮我把这个画面想法写成一段详细的图像生成提示词：')}>先写画面描述</button></div>
      </div>
      <div className="glass">
        <span className="ico ether"><Film size={18} /></span>
        <h3>视频生成</h3>
        <p>短片、产品演示、动态海报。接入视频模型后支持从文字或图片生成。</p>
        <span className="tag">尚未接入</span>
        <div className="btns" style={{ marginTop: 14 }}><button className="btn" onClick={() => onDraft('帮我把这个视频想法写成分镜脚本，每个镜头写清画面、运镜和时长：')}>先写分镜脚本</button></div>
      </div>
      <div className="glass">
        <span className="ico ok"><AudioLines size={18} /></span>
        <h3>实时语音通话</h3>
        <p>像打电话一样和 Atlas 说话，可以随时打断。目前用本机的语音识别和朗读。</p>
        <span className="tag" style={{ color: 'var(--ok)', background: 'var(--ok-soft)' }}>可以使用</span>
        <div className="btns" style={{ marginTop: 14 }}><button className="btn primary" onClick={onVoice}>开始通话</button></div>
      </div>
    </div>
  </div></div>;
}
