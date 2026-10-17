import MemlibBrowser from '../components/memory/MemlibBrowser';
import KnowledgePanel from '../components/memory/KnowledgePanel';

export default function MemoryPage({
  apiBaseUrl,
  connected,
  onToast,
}: {
  apiBaseUrl: string;
  connected: boolean;
  onToast: (text: string) => void;
}) {
  return <div className="screen page"><div className="page-inner"><MemlibBrowser apiBaseUrl={apiBaseUrl} connected={connected} onToast={onToast} /><KnowledgePanel apiBaseUrl={apiBaseUrl} connected={connected} onToast={onToast} /></div></div>;
}
