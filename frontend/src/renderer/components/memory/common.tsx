/** 记忆页面各视图共用的两步确认按钮：点一下变成「确认…」，3 秒内再点才执行。 */

import { useEffect, useState } from 'react';

export function ConfirmButton({
  label,
  confirm,
  disabled = false,
  onConfirm,
}: {
  label: string;
  confirm: string;
  disabled?: boolean;
  onConfirm: () => void;
}) {
  const [asked, setAsked] = useState(false);
  useEffect(() => {
    if (!asked) return;
    const timer = window.setTimeout(() => setAsked(false), 3000);
    return () => window.clearTimeout(timer);
  }, [asked]);
  return <button
    className={`btn ${asked ? 'danger' : 'ghost'}`}
    disabled={disabled}
    onClick={() => {
      if (asked) {
        setAsked(false);
        onConfirm();
      } else {
        setAsked(true);
      }
    }}
  >
    {asked ? confirm : label}
  </button>;
}

