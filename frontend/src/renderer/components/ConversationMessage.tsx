import ReactMarkdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import remarkGfm from 'remark-gfm';
import 'highlight.js/styles/github-dark.css';
import styles from '../App.module.css';

interface ConversationMessageProps {
  role: 'user' | 'assistant';
  content: string;
  username?: string;
  status?: string;
}

export default function ConversationMessage({ role, content, username = 'User', status }: ConversationMessageProps) {
  const avatar = Array.from(username.trim())[0]?.toLocaleUpperCase() ?? 'U';
  if (role === 'user') return <div className={styles.userMessage} data-message-role="user"><div className={styles.userBubble}>{content}</div><div className={styles.userAvatar}>{avatar}</div></div>;
  return <div className={styles.assistantMessage} data-message-role="assistant"><div className={styles.assistantAvatar}>A</div><div className={styles.messageBody}><div className={styles.messageMeta}><strong>Atlas</strong><span>{status}</span></div><div className={styles.markdownContent}><ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>{content}</ReactMarkdown></div></div></div>;
}
