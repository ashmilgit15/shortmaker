import React from 'react';
import { UserButton } from '@clerk/react';
import styles from './Sidebar.module.css';

interface NavItem {
  id: string;
  label: string;
  icon: string;
}

const NAV_ITEMS: NavItem[] = [
  { id: 'process', label: 'Create',  icon: 'add_circle' },
  { id: 'history', label: 'History', icon: 'history' },
  { id: 'trends',  label: 'Trends',  icon: 'trending_up' },
  { id: 'settings', label: 'Settings', icon: 'settings' },
];

interface SidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  hasAdmin: boolean;
}

export default function Sidebar({ activeTab, setActiveTab, hasAdmin }: SidebarProps) {
  // Only admin features are restricted; Settings is now accessible to all
  const items = NAV_ITEMS;

  return (
    <nav className={styles.sidebar} aria-label="Main navigation">
      <div className={styles.logo}>
        <div className={styles.logoIcon}>
          <span className={`material-symbols-outlined ${styles.logoMIcon}`}>movie_edit</span>
        </div>
        <span className={styles.logoText}>ShortMaker</span>
      </div>

      <ul className={styles.navList} role="list">
        {items.map((item) => (
          <li key={item.id}>
            <button
              className={`${styles.navBtn} ${activeTab === item.id ? styles.navBtnActive : ''}`}
              onClick={() => setActiveTab(item.id)}
              aria-current={activeTab === item.id ? 'page' : undefined}
            >
              <span className={`material-symbols-outlined ${styles.navIcon}`}>{item.icon}</span>
              <span className={styles.navLabel}>{item.label}</span>
              {activeTab === item.id && <span className={styles.activeBar} aria-hidden="true" />}
            </button>
          </li>
        ))}
      </ul>

      <div className={styles.footer}>
        <UserButton showName />
      </div>
    </nav>
  );
}
