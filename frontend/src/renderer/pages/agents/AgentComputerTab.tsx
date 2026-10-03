import { Monitor, RefreshCw } from 'lucide-react';
import TakeoverSection from '../devices/TakeoverSection';
import { useAtlasStore } from '../../store/useAtlasStore';
import { Button } from '../../ui/Button';

/** Agent 详情「电脑」tab：这台机器的控制权状态 + 交接卡片（交给谁一目了然）。 */
export default function AgentComputerTab({ agent, onToast }: {
  agent: { id: string; name: string }; onToast: (text: string) => void;
}) {
  const selfDeviceId = useAtlasStore((state) => state.selfDeviceId);
  const devices = useAtlasStore((state) => state.devices);
  const loadDevices = useAtlasStore((state) => state.loadDevices);
  const self = devices.find((device) => device.id === selfDeviceId);
  return <div className="grid max-w-[680px] gap-4">
    <p className="m-0 text-[12.5px] leading-[1.6] text-fg-3">
      {agent.name} 干需要屏幕和键鼠的活时，就在这台电脑上操作；你想插手就「我接管」，它会让出键鼠并停下来等你。
    </p>
    <TakeoverSection selfDeviceId={selfDeviceId} agentId={agent.id} onToast={onToast} compact />
    <div className="flex items-center gap-2 px-1 text-[12px] text-fg-3">
      <Monitor size={13} />
      {self ? `本机：${self.display_name}${self.online ? '（在线）' : ''}` : '本机设备信息还没有读到。'}
      <Button size="sm" variant="ghost" onClick={() => void loadDevices()} aria-label="刷新设备"><RefreshCw size={13} />刷新设备</Button>
    </div>
  </div>;
}
