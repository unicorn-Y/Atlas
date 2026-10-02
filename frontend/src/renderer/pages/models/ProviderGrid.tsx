import type { ProviderState } from '@atlas/backend-adapter';
import { cn } from '../../ui/cn';

interface ProviderGridProps {
  providers: ProviderState[];
  selectedId: string;
  onSelect: (id: string) => void;
}

/** The supported model services; pick one to edit its endpoint, keys and model below. */
export default function ProviderGrid({ providers, selectedId, onSelect }: ProviderGridProps) {
  return <div role="listbox" aria-label="服务商列表" className="grid grid-cols-2 gap-2 sm:grid-cols-3">
    {providers.map((provider) => <button key={provider.id} type="button" role="option" aria-selected={provider.id === selectedId}
      onClick={() => onSelect(provider.id)}
      className={cn('flex flex-col gap-1 rounded-xl px-3 py-2.5 text-left text-[13px] transition-colors',
        provider.id === selectedId ? 'bg-selected text-fg shadow-[inset_0_0_0_1px_var(--brand)]' : 'bg-sunken text-fg-2 hover:bg-hover hover:text-fg')}>
      <span className="flex items-center justify-between gap-2 font-medium">
        <span className="truncate">{provider.label}</span>
        {provider.configured && <span className="shrink-0 rounded-full bg-ok-soft px-1.5 py-0.5 text-[10.5px] font-normal text-ok">已配置</span>}
      </span>
      <span className="text-[11.5px] text-fg-3">{provider.configured ? `${provider.key_count} 把密钥` : '还没有密钥'}</span>
    </button>)}
    {!providers.length && <p className="col-span-full m-0 text-[12.5px] text-fg-3">还没读到服务商目录。连上 Atlas 后端后，这里会列出支持的服务商。</p>}
  </div>;
}
