import React from 'react';
import { Job } from '../types';
import JobCard from './JobCard';
import styles from './HistoryView.module.css';

interface HistoryViewProps {
  jobs: Job[];
  apiBase: string;
  youtubeConnected?: boolean;
  canManageYouTube?: boolean;
  onYouTubeUpload?: (job: Job) => Promise<void>;
  onOpenClip?: (filename: string, mode?: 'open' | 'download') => Promise<void>;
}

const TERMINAL = new Set(['complete', 'failed', 'error']);

export default function HistoryView({ jobs, apiBase, youtubeConnected, canManageYouTube, onYouTubeUpload, onOpenClip }: HistoryViewProps) {
  if (jobs.length === 0) {
    return (
      <div className={`empty-state animate-in ${styles.empty}`}>
        <span className="material-symbols-outlined">movie</span>
        <h3 className={styles.emptyTitle}>No jobs yet</h3>
        <p>Your generated clips will appear here once you start processing videos.</p>
      </div>
    );
  }

  const active = jobs.filter((j) => !TERMINAL.has(j.stage));
  const done   = jobs.filter((j) => TERMINAL.has(j.stage));

  return (
    <div className={`${styles.view} animate-in`}>
      {active.length > 0 && (
        <section className={styles.section}>
          <h4 className={styles.sectionTitle}>
            <span className="status-dot" />
            In Progress
          </h4>
          <div className={styles.grid}>
            {active.map((job) => (
              <JobCard
                key={job.id}
                job={job}
                apiBase={apiBase}
                youtubeConnected={youtubeConnected}
                canManageYouTube={canManageYouTube}
                onYouTubeUpload={onYouTubeUpload}
                onOpenClip={onOpenClip}
              />
            ))}
          </div>
        </section>
      )}

      {done.length > 0 && (
        <section className={styles.section}>
          <h4 className={styles.sectionTitle}>Completed</h4>
          <div className={styles.grid}>
            {done.map((job) => (
              <JobCard
                key={job.id}
                job={job}
                apiBase={apiBase}
                youtubeConnected={youtubeConnected}
                canManageYouTube={canManageYouTube}
                onYouTubeUpload={onYouTubeUpload}
                onOpenClip={onOpenClip}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
