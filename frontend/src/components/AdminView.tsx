import React from 'react';
import { AdminConfig } from '../types';
import styles from './AdminView.module.css';

interface AdminViewProps {
  config: AdminConfig;
}

interface StatusItem {
  label: string;
  icon: string;
  value: string;
  active?: boolean;
}

export default function AdminView({ config }: AdminViewProps) {
  const items: StatusItem[] = [
    {
      label: 'AI Engine',
      icon: 'psychology',
      value: config.model,
    },
    {
      label: 'AI Status',
      icon: config.ai_enabled ? 'check_circle' : 'cancel',
      value: config.ai_enabled ? 'Active' : 'Disabled',
      active: config.ai_enabled,
    },
    {
      label: 'API Key',
      icon: config.has_api_key ? 'lock' : 'lock_open',
      value: config.has_api_key ? 'Configured' : 'Not set',
      active: config.has_api_key,
    },
    {
      label: 'Auth Mode',
      icon: 'verified_user',
      value: 'Production',
      active: true,
    },
  ];

  return (
    <div className={`${styles.view} animate-in`}>
      <div className={`card ${styles.card}`}>
        <div className={styles.header}>
          <div className={styles.headerIcon}>
            <span className={`material-symbols-outlined ${styles.headerMIcon}`}>admin_panel_settings</span>
          </div>
          <div>
            <h3 className={styles.title}>System Core</h3>
            <p className={styles.desc}>AI engine configuration and runtime status</p>
          </div>
        </div>

        <div className={styles.grid}>
          {items.map((item) => (
            <div key={item.label} className={styles.item}>
              <span className={styles.itemLabel}>{item.label}</span>
              <div className={`${styles.itemValue} ${item.active === true ? styles.valueOn : item.active === false ? styles.valueOff : ''}`}>
                <span className={`material-symbols-outlined ${styles.itemIcon}`}>{item.icon}</span>
                {item.value}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
