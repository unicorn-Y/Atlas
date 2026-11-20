import { createRoot } from 'react-dom/client';
import ShortcutsPanel from '../../frontend/src/renderer/pages/ShortcutsPanel';

const root = document.getElementById('root');
if (!root) throw new Error('missing #root');
createRoot(root).render(<ShortcutsPanel apiBaseUrl={window.location.origin} />);