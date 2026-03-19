import React, { useState, useRef, DragEvent } from 'react';
import { Capabilities } from '../types';
import styles from './ProcessView.module.css';

interface ProcessViewProps {
  onProcess: (url: string, numClips: number) => Promise<void>;
  onUpload: (file: File, numClips: number) => Promise<void>;
  processing: boolean;
  capabilities: Capabilities | null;
}

type Mode = 'url' | 'upload';
const CLIP_OPTIONS = [1, 3, 5, 10];
const FEATURES = [
  { icon: 'auto_awesome',   label: 'AI Highlight Scoring' },
  { icon: 'crop_free',      label: 'Auto 9:16 Reframe' },
  { icon: 'closed_caption', label: 'Caption Burn-in' },
];

export default function ProcessView({ onProcess, onUpload, processing, capabilities }: ProcessViewProps) {
  const [mode, setMode]         = useState<Mode>('url');
  const [url, setUrl]           = useState('');
  const [numClips, setNumClips] = useState(5);
  const [file, setFile]         = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileRef                 = useRef<HTMLInputElement>(null);

  const supportsUpload = capabilities?.supports_uploads !== false;

  const handleUrlSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url || processing) return;
    await onProcess(url, numClips);
    setUrl('');
  };

  const handleFileSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file || processing) return;
    await onUpload(file, numClips);
    setFile(null);
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) setFile(dropped);
  };

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => { e.preventDefault(); setDragging(true); };
  const handleDragLeave = () => setDragging(false);

  return (
    <div className={`${styles.view} animate-in`}>
      <div className={`card ${styles.card}`}>

        {/* ── Header ── */}
        <div className={styles.cardTop}>
          <div className={styles.cardIcon}>
            <span className={`material-symbols-outlined ${styles.cardMIcon}`}>movie_edit</span>
          </div>
          <div className={styles.cardInfo}>
            <h3 className={styles.cardTitle}>Shorts Extraction</h3>
            <p className={styles.cardDesc}>
              Paste a YouTube URL or upload a local video — AI extracts the best 9:16 clips.
            </p>
          </div>
        </div>

        {/* ── Mode toggle ── */}
        {supportsUpload && (
          <div className={styles.modeToggle}>
            <button
              className={`${styles.modeBtn} ${mode === 'url' ? styles.modeBtnActive : ''}`}
              onClick={() => setMode('url')}
              type="button"
            >
              <span className={`material-symbols-outlined ${styles.modeBtnIcon}`}>link</span>
              YouTube URL
            </button>
            <button
              className={`${styles.modeBtn} ${mode === 'upload' ? styles.modeBtnActive : ''}`}
              onClick={() => setMode('upload')}
              type="button"
            >
              <span className={`material-symbols-outlined ${styles.modeBtnIcon}`}>upload_file</span>
              Upload Video
            </button>
          </div>
        )}

        {/* ── URL Mode ── */}
        {mode === 'url' && (
          <form onSubmit={handleUrlSubmit} className={styles.form}>
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel} htmlFor="yt-url">
                <span className={`material-symbols-outlined ${styles.fieldLabelIcon}`}>link</span>
                YouTube URL
              </label>
              <div className={styles.inputWrap}>
                <input
                  id="yt-url"
                  type="url"
                  placeholder="https://www.youtube.com/watch?v=..."
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  required
                  disabled={processing}
                  autoComplete="off"
                  spellCheck={false}
                />
                {url && !processing && (
                  <button type="button" className={styles.clearBtn} onClick={() => setUrl('')} aria-label="Clear">
                    <span className="material-symbols-outlined">close</span>
                  </button>
                )}
              </div>
            </div>
            {ClipsAndModelRow(numClips, setNumClips, processing)}
            <button type="submit" className={`btn btn-primary ${styles.submitBtn}`} disabled={processing || !url}>
              {processing ? (
                <><span className={`material-symbols-outlined ${styles.spinning}`}>autorenew</span>Igniting Pipeline…</>
              ) : (
                <><span className="material-symbols-outlined">bolt</span>Generate Viral Shorts</>
              )}
            </button>
          </form>
        )}

        {/* ── Upload Mode ── */}
        {mode === 'upload' && (
          <form onSubmit={handleFileSubmit} className={styles.form}>
            <div
              className={`${styles.dropZone} ${dragging ? styles.dropZoneActive : ''} ${file ? styles.dropZoneHasFile : ''}`}
              onDrop={handleDrop}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onClick={() => !file && fileRef.current?.click()}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => e.key === 'Enter' && fileRef.current?.click()}
              aria-label="Drop video file or click to browse"
            >
              {file ? (
                <div className={styles.fileInfo}>
                  <span className={`material-symbols-outlined ${styles.fileIcon}`}>videocam</span>
                  <div className={styles.fileMeta}>
                    <span className={styles.fileName}>{file.name}</span>
                    <span className={styles.fileSize}>{(file.size / 1024 / 1024).toFixed(1)} MB</span>
                  </div>
                  <button
                    type="button"
                    className={styles.fileRemove}
                    onClick={(e) => { e.stopPropagation(); setFile(null); }}
                    aria-label="Remove file"
                  >
                    <span className="material-symbols-outlined">close</span>
                  </button>
                </div>
              ) : (
                <div className={styles.dropPlaceholder}>
                  <span className={`material-symbols-outlined ${styles.dropIcon}`}>cloud_upload</span>
                  <p className={styles.dropTitle}>Drop your video here</p>
                  <p className={styles.dropHint}>or <span className={styles.dropLink}>browse files</span> · MP4, MOV, MKV, WebM</p>
                </div>
              )}
              <input
                ref={fileRef}
                type="file"
                accept=".mp4,.mov,.mkv,.avi,.webm,.mpg,.mpeg,.flv,.wmv"
                className={styles.fileInput}
                onChange={(e) => e.target.files?.[0] && setFile(e.target.files[0])}
                tabIndex={-1}
              />
            </div>

            {ClipsAndModelRow(numClips, setNumClips, processing)}

            <button type="submit" className={`btn btn-primary ${styles.submitBtn}`} disabled={processing || !file}>
              {processing ? (
                <><span className={`material-symbols-outlined ${styles.spinning}`}>autorenew</span>Uploading & Processing…</>
              ) : (
                <><span className="material-symbols-outlined">cloud_upload</span>Upload & Generate Shorts</>
              )}
            </button>
          </form>
        )}

        {/* ── Feature pills ── */}
        <div className={styles.featurePills}>
          {FEATURES.map((f) => (
            <div key={f.label} className={styles.featurePill}>
              <span className={`material-symbols-outlined ${styles.pillIcon}`}>{f.icon}</span>
              {f.label}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ClipsAndModelRow(
  numClips: number,
  setNumClips: (n: number) => void,
  processing: boolean,
) {
  return (
    <div className={styles.configRow}>
      <div className={styles.configItem}>
        <span className={styles.configLabel}>Number of Clips</span>
        <div className={styles.clipBtns}>
          {CLIP_OPTIONS.map((n) => (
            <button
              key={n}
              type="button"
              className={`${styles.clipBtn} ${numClips === n ? styles.clipBtnOn : ''}`}
              onClick={() => setNumClips(n)}
              disabled={processing}
              aria-pressed={numClips === n}
            >
              {n}
            </button>
          ))}
        </div>
      </div>
      <div className={styles.configItem}>
        <span className={styles.configLabel}>AI Model</span>
        <div className={styles.modelBadge}>
          <span className={`material-symbols-outlined ${styles.modelIcon}`}>psychology</span>
          Gemini 2.5 Flash
        </div>
      </div>
    </div>
  );
}
