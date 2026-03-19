import React, { useEffect, useState } from 'react';
import styles from './Notice.module.css';

interface NoticeProps {
  type: 'success' | 'error' | 'info';
  message: string;
  onClear: () => void;
}

const ICONS = { success: 'check_circle', error: 'error', info: 'info' } as const;

export default function Notice({ type, message, onClear }: NoticeProps) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const id = requestAnimationFrame(() => setVisible(true));
    return () => cancelAnimationFrame(id);
  }, []);

  const handleClose = () => {
    setVisible(false);
    setTimeout(onClear, 320);
  };

  const typeClass = type === 'success' ? styles.noticeSuccess
    : type === 'error' ? styles.noticeError
    : styles.noticeInfo;

  return (
    <div
      className={`${styles.notice} ${typeClass} ${visible ? styles.visible : ''}`}
      role="alert"
      aria-live="polite"
    >
      <span className={`material-symbols-outlined ${styles.icon}`}>{ICONS[type]}</span>
      <p className={styles.message}>{message}</p>
      <button className={styles.closeBtn} onClick={handleClose} aria-label="Dismiss notification">
        <span className="material-symbols-outlined">close</span>
      </button>
    </div>
  );
}
