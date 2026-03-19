import React, { useState } from 'react';
import { TrendCandidate } from '../types';
import styles from './TrendsView.module.css';

const LOCATIONS = ['India', 'United States', 'United Kingdom', 'Canada', 'Australia'];

interface TrendsViewProps {
  apiFetch: (path: string, opts?: RequestInit) => Promise<Response | null>;
  showNotice: (type: 'success' | 'error' | 'info', msg: string) => void;
  onProcessUrl: (url: string) => Promise<boolean>;
}

export default function TrendsView({ apiFetch, showNotice, onProcessUrl }: TrendsViewProps) {
  const [topic, setTopic]           = useState('');
  const [location, setLocation]     = useState('India');
  const [searching, setSearching]   = useState(false);
  const [results, setResults]       = useState<TrendCandidate[] | null>(null);
  const [processing, setProcessing] = useState<string | null>(null); // URL being processed

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!topic.trim() || searching) return;
    setSearching(true);
    try {
      const res = await apiFetch('/trends/discover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: topic.trim(), location, limit: 8 }),
      });
      if (res?.ok) {
        const data = await res.json();
        setResults(data.candidates || []);
        if (!data.candidates?.length) showNotice('info', 'No trending videos found for this topic.');
      } else {
        const err = res ? await res.json().catch(() => null) : null;
        showNotice('error', err?.detail || 'Trend search failed — check your Firecrawl API key.');
      }
    } catch {
      showNotice('error', 'Trend search failed');
    } finally {
      setSearching(false);
    }
  };

  const handleAutoProcess = async () => {
    if (!topic.trim() || searching) return;
    setSearching(true);
    try {
      const res = await apiFetch('/trends/auto-process', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: topic.trim(), location, limit: 6, num_clips: 5 }),
      });
      if (res?.ok) {
        showNotice('success', 'Auto-processing top trending video! Check History.');
      } else {
        const err = res ? await res.json().catch(() => null) : null;
        showNotice('error', err?.detail || 'Auto-process failed');
      }
    } catch {
      showNotice('error', 'Auto-process failed');
    } finally {
      setSearching(false);
    }
  };

  const handleProcess = async (url: string) => {
    setProcessing(url);
    try {
      const started = await onProcessUrl(url);
      if (started) {
        showNotice('success', 'Processing started! Check History.');
      }
    } finally {
      setTimeout(() => setProcessing(null), 1500);
    }
  };

  return (
    <div className={`${styles.view} animate-in`}>
      {/* ── Search card ── */}
      <div className={`card ${styles.searchCard}`}>
        <div className={styles.searchHeader}>
          <div className={styles.searchIcon}>
            <span className={`material-symbols-outlined ${styles.searchMIcon}`}>travel_explore</span>
          </div>
          <div>
            <h3 className={styles.searchTitle}>Discover Trending Videos</h3>
            <p className={styles.searchDesc}>Find viral YouTube videos on any topic using Firecrawl AI search.</p>
          </div>
        </div>

        <form onSubmit={handleSearch} className={styles.searchForm}>
          <div className={styles.searchInputWrap}>
            <span className={`material-symbols-outlined ${styles.searchInputIcon}`}>search</span>
            <input
              type="text"
              placeholder='e.g. "AI tools", "finance tips", "gym motivation"'
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              className={styles.searchInput}
              disabled={searching}
              required
            />
          </div>

          <div className={styles.searchControls}>
            <div className={styles.locationWrap}>
              <span className={`material-symbols-outlined ${styles.locationIcon}`}>location_on</span>
              <select
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                disabled={searching}
                className={styles.locationSelect}
              >
                {LOCATIONS.map((l) => <option key={l} value={l}>{l}</option>)}
              </select>
            </div>

            <button
              type="submit"
              className={`btn btn-secondary ${styles.searchBtn}`}
              disabled={searching || !topic.trim()}
            >
              {searching ? (
                <><span className={`material-symbols-outlined ${styles.spinning}`}>autorenew</span>Searching…</>
              ) : (
                <><span className="material-symbols-outlined">search</span>Discover</>
              )}
            </button>

            <button
              type="button"
              className={`btn btn-primary ${styles.autoBtn}`}
              onClick={handleAutoProcess}
              disabled={searching || !topic.trim()}
              title="Auto-pick top trending video and start processing"
            >
              <span className="material-symbols-outlined">bolt</span>
              Auto-Process
            </button>
          </div>
        </form>
      </div>

      {/* ── Results ── */}
      {results !== null && (
        <div className={styles.resultsSection}>
          {results.length === 0 ? (
            <div className="empty-state">
              <span className="material-symbols-outlined">sentiment_dissatisfied</span>
              <p>No trending videos found. Try a broader topic or different region.</p>
            </div>
          ) : (
            <>
              <h4 className={styles.resultsTitle}>
                <span className={`material-symbols-outlined ${styles.resultsTitleIcon}`}>trending_up</span>
                {results.length} Videos Found
              </h4>
              <div className={styles.resultsGrid}>
                {results.map((c, i) => (
                  <div key={c.url} className={`card ${styles.resultCard}`}>
                    <div className={styles.resultRank}>
                      <span className={`mono ${styles.rankNum}`}>#{String(i + 1).padStart(2, '0')}</span>
                      <div className={styles.scoreBar}>
                        <div className="progress-track">
                          <div className="progress-fill" style={{ width: `${Math.min(c.score * 5, 100)}%` }} />
                        </div>
                        <span className={`mono ${styles.scoreVal}`}>{c.score}pt</span>
                      </div>
                    </div>

                    <h4 className={styles.resultTitle} title={c.title}>{c.title}</h4>

                    {c.description && (
                      <p className={styles.resultDesc}>{c.description}</p>
                    )}

                    <div className={styles.resultMeta}>
                      <span className={`material-symbols-outlined ${styles.metaIcon}`}>label</span>
                      <span className={styles.metaText}>{c.reason}</span>
                    </div>

                    <div className={styles.resultActions}>
                      <a
                        href={c.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={`btn btn-ghost ${styles.previewBtn}`}
                      >
                        <span className="material-symbols-outlined">open_in_new</span>
                        Preview
                      </a>
                      <button
                        className={`btn btn-primary ${styles.processBtn}`}
                        onClick={() => handleProcess(c.url)}
                        disabled={processing === c.url}
                      >
                        {processing === c.url ? (
                          <><span className={`material-symbols-outlined ${styles.spinning}`}>autorenew</span>Starting…</>
                        ) : (
                          <><span className="material-symbols-outlined">bolt</span>Process</>
                        )}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {/* ── Empty prompt ── */}
      {results === null && (
        <div className={styles.emptyHint}>
          <span className={`material-symbols-outlined ${styles.emptyHintIcon}`}>tips_and_updates</span>
          <p>Enter a topic above to discover trending YouTube videos.<br />
            Requires a <strong>Firecrawl API key</strong> configured in Settings.</p>
        </div>
      )}
    </div>
  );
}
