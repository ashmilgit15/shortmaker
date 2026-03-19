import React, { useState } from 'react';
import { Job } from '../types';
import styles from './JobCard.module.css';

interface JobCardProps {
  job: Job;
  apiBase: string;
  youtubeConnected?: boolean;
  canManageYouTube?: boolean;
  onYouTubeUpload?: (job: Job) => Promise<void>;
  onOpenClip?: (filename: string, mode?: 'open' | 'download') => Promise<void>;
}

const STAGE_LABELS: Record<string, string> = {
  queued:      'Queued',
  downloading: 'Downloading',
  transcribing:'Transcribing',
  analyzing:   'Analyzing',
  highlighting:'Highlighting',
  reframing:   'Reframing',
  generating:  'Generating',
  processing:  'Processing',
  starting:    'Starting',
  complete:    'Complete',
  failed:      'Failed',
  error:       'Error',
};

const STAGE_ICONS: Record<string, string> = {
  queued:      'schedule',
  downloading: 'download',
  transcribing:'record_voice_over',
  analyzing:   'auto_awesome',
  highlighting:'auto_awesome',
  reframing:   'crop',
  generating:  'movie',
  processing:  'autorenew',
  starting:    'autorenew',
  complete:    'check_circle',
  failed:      'error',
  error:       'error',
};

function safeHostname(url?: string): string {
  if (!url) return 'New Job';
  try { return new URL(url).hostname.replace('www.', ''); } catch { return url.slice(0, 40); }
}

export default function JobCard({ job, apiBase, youtubeConnected, canManageYouTube, onYouTubeUpload, onOpenClip }: JobCardProps) {
  const [uploading, setUploading] = useState(false);
  const [clipsExpanded, setClipsExpanded] = useState(false);
  const [activeClip, setActiveClip] = useState<string | null>(null);

  const isComplete = job.stage === 'complete';
  const isFailed   = job.stage === 'failed' || job.stage === 'error' || job.status === 'failed';
  const isActive   = !isComplete && !isFailed;
  const rawProgress = typeof job.progress === 'number' ? job.progress : 0;
  const progress = Math.max(0, Math.min(100, rawProgress <= 1 ? rawProgress * 100 : rawProgress));

  const clips = job.results || job.shorts || [];

  const pillClass = isComplete ? 'pill pill-success'
    : isFailed  ? 'pill pill-error'
    : job.stage === 'queued' ? 'pill pill-queued'
    : 'pill pill-processing';

  const displayName = job.video_title || job.filename || safeHostname(job.url);

  const handleUpload = async () => {
    if (!onYouTubeUpload) return;
    setUploading(true);
    try { await onYouTubeUpload(job); } finally { setUploading(false); }
  };

  const handleClipAction = async (filename: string, mode: 'open' | 'download') => {
    if (!onOpenClip) return;
    const actionKey = `${mode}:${filename}`;
    setActiveClip(actionKey);
    try {
      await onOpenClip(filename, mode);
    } finally {
      setActiveClip(null);
    }
  };

  return (
    <div className={`card animate-in ${styles.card}`}>
      <div className={styles.header}>
        <div className={styles.info}>
          <div className={styles.sourceTag}>
            <span className={`material-symbols-outlined ${styles.sourceIcon}`}>
              {job.source_type === 'upload' ? 'upload_file' : 'smart_display'}
            </span>
            {job.source_type === 'upload' ? 'Upload' : 'YouTube'}
          </div>
          <h4 className={styles.title} title={displayName}>{displayName}</h4>
          <span className={`mono ${styles.jobId}`}>#{job.id?.slice(0, 8)}</span>
        </div>
        <span className={pillClass}>
          <span className="material-symbols-outlined">{STAGE_ICONS[job.stage] || 'pending'}</span>
          {STAGE_LABELS[job.stage] || job.stage}
        </span>
      </div>

      {isActive && (
        <div className={styles.progressSection}>
          <div className={styles.progressMeta}>
            <span className={styles.progressMsg}>{job.message || 'Processing…'}</span>
            <span className={`mono ${styles.progressPct}`}>{Math.round(progress)}%</span>
          </div>
          <div className="progress-track">
            <div className="progress-fill" style={{ width: `${progress}%` }} />
          </div>
        </div>
      )}

      {isComplete && (
        <div className={styles.successSection}>
          <div className={styles.clipsInfo}>
            <span className={`material-symbols-outlined ${styles.clipsIcon}`}>theaters</span>
            <span>{clips.length} clip{clips.length !== 1 ? 's' : ''} ready</span>
            {job.has_ai_data && (
              <span className={styles.aiBadge}>
                <span className={`material-symbols-outlined ${styles.aiIcon}`}>auto_awesome</span>
                AI
              </span>
            )}
          </div>
          <div className={styles.actionRow}>
            <button
              className={`btn btn-primary ${styles.viewBtn}`}
              onClick={() => setClipsExpanded((value) => !value)}
            >
              <span className="material-symbols-outlined">{clipsExpanded ? 'expand_less' : 'video_library'}</span>
              {clipsExpanded ? 'Hide Clips' : 'View Clips'}
            </button>
            {canManageYouTube && clips.length > 0 && (
              <>
                {youtubeConnected ? (
                  <button
                    className={`btn btn-secondary ${styles.ytBtn}`}
                    onClick={handleUpload}
                    disabled={uploading}
                    title="Upload all clips to YouTube"
                  >
                    {uploading ? (
                      <><span className={`material-symbols-outlined ${styles.spinning}`}>autorenew</span>Uploading…</>
                    ) : (
                      <><span className="material-symbols-outlined">smart_display</span>Upload to YouTube</>
                    )}
                  </button>
                ) : (
                  <div className={styles.ytNotConfigured}>
                    <span className="material-symbols-outlined">info</span>
                    <p className={styles.ytNotConfiguredText}>
                      YouTube not configured. <a href="#/settings">Setup credentials</a> to enable uploads.
                    </p>
                  </div>
                )}
              </>
            )}
          </div>

          {clipsExpanded && clips.length > 0 && (
            <div className={styles.clipList}>
              {clips.map((filename, index) => {
                const clipAction = `open:${filename}`;
                const downloadAction = `download:${filename}`;
                const clipTitle = job.ai_highlights?.[index]?.title || `Clip ${index + 1}`;

                return (
                  <div key={filename} className={styles.clipRow}>
                    <div className={styles.clipMeta}>
                      <span className={`material-symbols-outlined ${styles.clipIcon}`}>movie</span>
                      <div className={styles.clipText}>
                        <strong className={styles.clipTitle}>{clipTitle}</strong>
                        <span className={`mono ${styles.clipFilename}`}>{filename}</span>
                      </div>
                    </div>
                    <div className={styles.clipActions}>
                      <button
                        className={`btn btn-ghost ${styles.clipBtn}`}
                        onClick={() => handleClipAction(filename, 'open')}
                        disabled={!onOpenClip || activeClip !== null}
                      >
                        {activeClip === clipAction ? (
                          <><span className={`material-symbols-outlined ${styles.spinning}`}>autorenew</span>Opening…</>
                        ) : (
                          <><span className="material-symbols-outlined">open_in_new</span>Open</>
                        )}
                      </button>
                      <button
                        className={`btn btn-secondary ${styles.clipBtn}`}
                        onClick={() => handleClipAction(filename, 'download')}
                        disabled={!onOpenClip || activeClip !== null}
                      >
                        {activeClip === downloadAction ? (
                          <><span className={`material-symbols-outlined ${styles.spinning}`}>autorenew</span>Downloading…</>
                        ) : (
                          <><span className="material-symbols-outlined">download</span>Download</>
                        )}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {isFailed && (
        <div className={styles.errorRow}>
          <span className={`material-symbols-outlined ${styles.errorIcon}`}>warning</span>
          <p className={styles.errorMsg}>{job.error || job.message || 'Pipeline interrupted'}</p>
        </div>
      )}
    </div>
  );
}
