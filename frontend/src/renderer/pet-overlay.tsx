import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { api } from './services/api';

type Pet = { id: string; name: string; emoji: string; color: string; avatar_url?: string };
type Catalog = { pets: Pet[]; active_id: string };
const labels = { idle: '陪伴中', running: '正在帮忙', waiting: '等你处理' } as const;

function PetOverlay() {
  const [catalog, setCatalog] = useState<Catalog>({ pets: [], active_id: 'atlas-companion' });
  const [state, setState] = useState<'running' | 'waiting' | 'idle'>('idle');
  useEffect(() => {
    const desktop = window.atlasDesktop;
    const unsubscribe = desktop?.onPetOverlayStateChange?.(setState);
    void api<Catalog>(desktop?.apiBaseUrl ?? 'http://127.0.0.1:8765', '/api/pets').then(setCatalog).catch(() => undefined);
    return () => unsubscribe?.();
  }, []);
  const pet = catalog.pets.find((item) => item.id === catalog.active_id) ?? catalog.pets[0];
  return <main className={`pet pet-${state}`} style={{ '--pet-color': pet?.color ?? '#8277f4' } as React.CSSProperties} aria-label={`Atlas 桌宠：${labels[state]}`}>
    <div className="bubble">{labels[state]}</div>
    <div className="avatar" aria-label={pet?.name ?? 'Atlas 小伙伴'}>{pet?.avatar_url ? <img src={`${window.atlasDesktop?.apiBaseUrl ?? 'http://127.0.0.1:8765'}${pet.avatar_url}`} /> : pet?.emoji ?? '🐈'}</div>
    <span className="name">{pet?.name ?? 'Atlas 小伙伴'}</span>
    <button className="close" aria-label="隐藏桌宠" onClick={() => void window.atlasDesktop?.togglePetOverlay?.()}>×</button>
    <style>{`
      *{box-sizing:border-box}html,body,#root{margin:0;width:100%;height:100%;overflow:hidden;background:transparent;font-family:system-ui,sans-serif}.pet{--pet-color:#8277f4;width:100%;height:100%;display:flex;align-items:center;justify-content:center;flex-direction:column;position:relative;user-select:none}.avatar{width:112px;height:112px;display:grid;place-items:center;border-radius:42% 48% 44% 48%;font-size:68px;background:radial-gradient(circle at 36% 28%,#fff 0 12%,color-mix(in srgb,var(--pet-color) 15%,white) 60%,color-mix(in srgb,var(--pet-color) 30%,white));box-shadow:0 12px 35px #0002;animation:bob 2.5s ease-in-out infinite;transition:transform .3s}.avatar img{width:100%;height:100%;object-fit:cover;border-radius:inherit}.bubble{position:absolute;top:4px;padding:5px 11px;border-radius:999px;background:#fff;color:#34323b;font-size:11px;box-shadow:0 3px 14px #0002}.name{margin-top:4px;padding:2px 8px;border-radius:9px;background:#ffffffd9;color:#393744;font-size:10px}.close{position:absolute;right:4px;top:4px;width:22px;height:22px;border:0;border-radius:50%;background:#fff9;color:#484653;opacity:0;cursor:pointer}.pet:hover .close{opacity:1}.pet-running .avatar{animation:bob .65s ease-in-out infinite;transform:scale(1.03)}.pet-waiting .avatar{animation:tilt 1.3s ease-in-out infinite}.pet-running .bubble{background:var(--pet-color);color:white}.pet-waiting .bubble{background:#f2b84b;color:#392b0c}@keyframes bob{0%,100%{translate:0 0}50%{translate:0 -7px}}@keyframes tilt{0%,100%{rotate:0}35%{rotate:-7deg}70%{rotate:7deg}}@media(prefers-reduced-motion:reduce){.avatar{animation:none!important;transition:none}}
    `}</style>
  </main>;
}

createRoot(document.getElementById('root')!).render(<PetOverlay />);
