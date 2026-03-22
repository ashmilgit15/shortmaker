import React from 'react';
import { UserButton } from '@clerk/react';
import styles from './MobileNav.module.css';

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

interface MobileNavProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  hasAdmin: boolean;
  showUser?: boolean;
}

export default function MobileNav({ activeTab, setActiveTab, hasAdmin, showUser = true }: MobileNavProps) {
  // Only admin features are restricted; Settings is now accessible to all
  const items = NAV_ITEMS;

  return (
    <nav className={styles.nav} aria-label="Mobile navigation">
      {items.map((item) => (
        <button
          key={item.id}
          className={`${styles.tab} ${activeTab === item.id ? styles.tabActive : ''}`}
          onClick={() => setActiveTab(item.id)}
          aria-current={activeTab === item.id ? 'page' : undefined}
        >
          <span className={`material-symbols-outlined ${styles.tabIcon}`}>{item.icon}</span>
          <span className={styles.tabLabel}>{item.label}</span>
        </button>
      ))}

      {showUser && (
        <div className={styles.userTab}>
          <UserButton />
        </div>
      )}
    </nav>
  );
}
