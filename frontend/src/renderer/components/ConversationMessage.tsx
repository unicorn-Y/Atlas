import MarkdownContent from './MarkdownContent';
import styles from '../App.module.css';

interface ConversationMessageProps {
  role: 'user' | 'assistant';
  content: string;
  status?: string;
}

export default function ConversationMessage({ role, content, status }: ConversationMessageProps) {
  if (role === 'user') return <div className={styles.userMessage} data-message-role="user"><div className={styles.userBubble}>{content}</div><div className={styles.userAvatar}>你</div></div>;
  return <div className={styles.assistantMessage} data-message-role="assistant"><div className={styles.assistantAvatar}>A</div><div className={styles.messageBody}><div className={styles.messageMeta}><strong>Atlas</strong><span>{status}</span></div><MarkdownContent content={content} /></div></div>;
}
