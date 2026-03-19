import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useUser, useAuth } from '@clerk/react';

import { Job, AdminConfig, Capabilities, SessionData, NoticeData } from './types';
import LandingPage from './components/LandingPage';
import Sidebar from './components/Sidebar';
import MobileNav from './components/MobileNav';
import Notice from './components/Notice';
import ProcessView from './components/ProcessView';
import HistoryView from './components/HistoryView';
import TrendsView from './components/TrendsView';
import SettingsView from './components/SettingsView';

import styles from './App.module.css';

const API_BASE = (import.meta as any).env.VITE_API_BASE_URL || '';
const API_UNAVAILABLE_BACKOFF_MS = 30_000;
const API_UNAVAILABLE_MESSAGE =
  'ShortMaker API is not reachable at http://127.0.0.1:8000. Start FastAPI or set VITE_API_BASE_URL.';
const CLERK_ISSUER_MISMATCH_DETAIL = 'Token issuer does not match configured Clerk issuer.';
const CLERK_ISSUER_MISMATCH_MESSAGE = 'Session is tied to a different Clerk instance. Sign in again.';
const ADMIN_ROUTE_PREFIX = '/ashmil2010';

function normalizeJob(job: Partial<Job> & { job_id?: string }): Job {
  const rawProgress = typeof job.progress === 'number' ? job.progress : 0;
  const normalizedProgress = rawProgress <= 1 ? rawProgress * 100 : rawProgress;

  return {
    ...job,
    id: String(job.id || job.job_id || ''),
    stage: (job.stage || job.status || 'queued') as Job['stage'],
    progress: Math.max(0, Math.min(100, normalizedProgress)),
    source_type: job.source_type || (job.url ? 'youtube' : 'upload'),
    shorts: job.shorts || job.results || [],
    results: job.results || job.shorts || [],
  };
}

export default function App() {
  const { isLoaded, isSignedIn } = useUser();
  const { getToken } = useAuth();
  const noticeTimeoutRef = useRef<number | null>(null);
  const responseWarningsRef = useRef<Set<string>>(new Set());
  const apiUnavailableUntilRef = useRef(0);
  const apiOfflineNoticeRef = useRef(false);
  const issuerMismatchHandledRef = useRef(false);
  const protectedPollInFlightRef = useRef(false);
  const authFailureNoticeRef = useRef(false);
  const isAdminConsoleRoute = typeof window !== 'undefined' && window.location.pathname.startsWith(ADMIN_ROUTE_PREFIX);

  const [jobs, setJobs]                   = useState<Job[]>([]);
  const [adminConfig, setAdminConfig]     = useState<AdminConfig | null>(null);
  const [adminConfigError, setAdminConfigError] = useState<string | null>(null);
  const [capabilities, setCapabilities]   = useState<Capabilities | null>(null);
  const [session, setSession]             = useState<SessionData | null>(null);
  const [notice, setNotice]               = useState<NoticeData | null>(null);
  const [activeTab, setActiveTab]         = useState<string>(isAdminConsoleRoute ? 'settings' : 'process');
  const [processing, setProcessing]       = useState<boolean>(false);
  const [settingsSaving, setSettingsSaving] = useState<boolean>(false);

  const apiPath = useCallback((path: string) => {
    if (!isAdminConsoleRoute) return path;
    return `${ADMIN_ROUTE_PREFIX}${path}`;
  }, [isAdminConsoleRoute]);

  const showNotice = useCallback((type: 'success' | 'error' | 'info', message: string) => {
    if (noticeTimeoutRef.current) {
      window.clearTimeout(noticeTimeoutRef.current);
    }
    setNotice({ type, message });
    noticeTimeoutRef.current = window.setTimeout(() => setNotice(null), 6000);
  }, []);

  useEffect(() => {
    return () => {
      if (noticeTimeoutRef.current) {
        window.clearTimeout(noticeTimeoutRef.current);
      }
    };
  }, []);

  const getBearerToken = useCallback(async () => {
    try {
      return (await getToken()) || null;
    } catch (e) {
      console.error('Fetch error:', e);
      return null;
    }
  }, [getToken]);

  const authenticatedFetch = useCallback(async (
    path: string,
    options: RequestInit = {},
    tokenOverride: string | null = null,
  ) => {
    try {
      const token = tokenOverride ?? await getBearerToken();
      if (!token) return null;
      const res = await fetch(`${API_BASE}${apiPath(path)}`, {
        ...options,
        headers: {
          ...options.headers,
          Authorization: `Bearer ${token}`,
        },
      });
      return res;
    } catch (e) {
      console.error('Fetch error:', e);
      return null;
    }
  }, [apiPath, getBearerToken]);

  const publicFetch = useCallback(async (path: string, options: RequestInit = {}) => {
    try {
      return await fetch(`${API_BASE}${apiPath(path)}`, options);
    } catch (e) {
      console.error('Fetch error:', e);
      return null;
    }
  }, [apiPath]);

  const authenticatedRootFetch = useCallback(async (
    path: string,
    options: RequestInit = {},
    tokenOverride: string | null = null,
  ) => {
    try {
      const token = tokenOverride ?? await getBearerToken();
      if (!token) return null;
      const res = await fetch(`${API_BASE}${path}`, {
        ...options,
        headers: {
          ...options.headers,
          Authorization: `Bearer ${token}`,
        },
      });
      return res;
    } catch (e) {
      console.error('Fetch error:', e);
      return null;
    }
  }, [getBearerToken]);

  const reportResponseWarning = useCallback((key: string, message: string) => {
    if (!responseWarningsRef.current.has(key)) {
      responseWarningsRef.current.add(key);
      console.error(new Error(message));
    }
  }, []);

  const readResponseBody = useCallback(async (
    res: Response | null,
    options: { endpoint?: string; expectJson?: boolean } = {},
  ) => {
    if (!res) return null;

    const endpoint = options.endpoint || 'request';
    const contentType = res.headers.get('content-type') || '';

    try {
      const text = await res.text();
      if (!text) return null;

      if (options.expectJson) {
        try {
          return JSON.parse(text);
        } catch {
          const looksLikeHtml = /^\s*</.test(text);
          const responseKind = looksLikeHtml ? 'HTML' : 'non-JSON content';
          reportResponseWarning(
            `${endpoint}:expected-json`,
            `Expected JSON from ${endpoint} but received ${responseKind}${contentType ? ` (${contentType})` : ''}. Check Vite proxy or VITE_API_BASE_URL.`,
          );
          return null;
        }
      }

      if (contentType.includes('application/json')) {
        try {
          return JSON.parse(text);
        } catch {
          reportResponseWarning(
            `${endpoint}:invalid-json`,
            `Received invalid JSON from ${endpoint}${contentType ? ` (${contentType})` : ''}.`,
          );
          return null;
        }
      }

      return { detail: text };
    } catch {
      return null;
    }
  }, [reportResponseWarning]);

  const extractErrorMessage = useCallback(async (res: Response | null, fallback: string) => {
    const body = await readResponseBody(res);
    return body?.detail || body?.message || fallback;
  }, [readResponseBody]);

  const handleIssuerMismatch = useCallback(async (res: Response | null) => {
    if (!res || res.status !== 401 || issuerMismatchHandledRef.current) {
      return false;
    }

    const body = await readResponseBody(res.clone());
    const detail = String(body?.detail || body?.message || '');
    if (!detail.includes(CLERK_ISSUER_MISMATCH_DETAIL)) {
      return false;
    }

    issuerMismatchHandledRef.current = true;
    setJobs([]);
    setSession(null);
    setAdminConfig(null);
    setAdminConfigError(null);
    showNotice('error', `${CLERK_ISSUER_MISMATCH_MESSAGE} If this persists, sign out and sign in again.`);
    return true;
  }, [readResponseBody, showNotice]);

  const handleProtectedAuthFailure = useCallback(async (res: Response | null) => {
    if (!res || res.status !== 401) {
      return false;
    }
    if (await handleIssuerMismatch(res)) {
      return true;
    }

    setJobs([]);
    setSession(null);
    setAdminConfig(null);
    setAdminConfigError('Session is not authorized. Sign in again.');
    if (!authFailureNoticeRef.current) {
      authFailureNoticeRef.current = true;
      showNotice('error', 'Session is not authorized. Sign in again.');
    }
    return true;
  }, [handleIssuerMismatch, showNotice]);

  const fetchData = useCallback(async () => {
    if (!isSignedIn) return;
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
    if (Date.now() < apiUnavailableUntilRef.current) return;
    if (protectedPollInFlightRef.current) return;

    protectedPollInFlightRef.current = true;
    try {
      const token = isAdminConsoleRoute ? null : await getBearerToken();
      if (!isAdminConsoleRoute && !token) {
        return;
      }

      const [jobsRes, capsRes, sessionRes] = await Promise.all([
        (isAdminConsoleRoute ? publicFetch('/jobs/recent') : authenticatedFetch('/jobs/recent', {}, token)),
        publicFetch('/capabilities'),
        (isAdminConsoleRoute ? Promise.resolve(null) : authenticatedRootFetch('/session', {}, token)),
      ]);

      if (await handleProtectedAuthFailure(jobsRes)) return;
      if (await handleProtectedAuthFailure(sessionRes)) return;

      const protectedResponses = isAdminConsoleRoute ? [jobsRes] : [jobsRes, sessionRes];
      const apiUnavailable = [capsRes, ...protectedResponses].some((res) => !res || res.status === 503);
      if (apiUnavailable) {
        apiUnavailableUntilRef.current = Date.now() + API_UNAVAILABLE_BACKOFF_MS;
        if (!apiOfflineNoticeRef.current) {
          apiOfflineNoticeRef.current = true;
          showNotice('error', API_UNAVAILABLE_MESSAGE);
        }
        return;
      }

      apiUnavailableUntilRef.current = 0;
      apiOfflineNoticeRef.current = false;
      authFailureNoticeRef.current = false;

      if (jobsRes?.ok) {
        const jobsPayload = await readResponseBody(jobsRes, { endpoint: '/jobs/recent', expectJson: true });
        const normalizedJobs = Array.isArray(jobsPayload?.jobs)
          ? jobsPayload.jobs.map(normalizeJob).filter((job: Job) => Boolean(job.id))
          : [];
        setJobs(normalizedJobs);
      }
      if (capsRes?.ok) {
        const capabilitiesPayload = await readResponseBody(capsRes, { endpoint: '/capabilities', expectJson: true });
        if (capabilitiesPayload) {
          setCapabilities(capabilitiesPayload as Capabilities);
        }
      }
      if (sessionRes?.ok) {
        const sessionPayload = await readResponseBody(sessionRes, { endpoint: '/session', expectJson: true });
        if (sessionPayload) {
          setSession(sessionPayload as SessionData);
        }
      }
    } catch (e) {
      console.error(e);
    } finally {
      protectedPollInFlightRef.current = false;
    }
  }, [authenticatedFetch, authenticatedRootFetch, getBearerToken, handleProtectedAuthFailure, isAdminConsoleRoute, isSignedIn, publicFetch, readResponseBody, showNotice]);

  const fetchAdminConfig = useCallback(async () => {
    if (!isSignedIn || (!session?.is_admin && !isAdminConsoleRoute)) {
      setAdminConfig(null);
      setAdminConfigError(null);
      return;
    }
    try {
      const token = isAdminConsoleRoute ? null : await getBearerToken();
      if (!isAdminConsoleRoute && !token) {
        return;
      }
      const res = isAdminConsoleRoute
        ? await publicFetch('/ai/config')
        : await authenticatedFetch('/ai/config', {}, token);
      if (await handleProtectedAuthFailure(res)) {
        return;
      }
      if (res?.ok) {
        const configPayload = await readResponseBody(res, { endpoint: '/ai/config', expectJson: true });
        if (configPayload) {
          setAdminConfig(configPayload as AdminConfig);
          setAdminConfigError(null);
        }
      } else if (res?.status === 403) {
        setAdminConfig(null);
        setAdminConfigError('This account is signed in but is not allowed to access admin settings on the server.');
      } else {
        setAdminConfig(null);
        setAdminConfigError(await extractErrorMessage(res, 'Failed to load admin settings.'));
      }
    } catch {
      setAdminConfig(null);
      setAdminConfigError('Failed to load admin settings.');
    }
  }, [authenticatedFetch, extractErrorMessage, getBearerToken, handleProtectedAuthFailure, isAdminConsoleRoute, isSignedIn, publicFetch, readResponseBody, session?.is_admin]);

  useEffect(() => {
    if (isSignedIn) {
      fetchData();
      fetchAdminConfig();
      const interval = setInterval(fetchData, 8000);
      return () => clearInterval(interval);
    }
  }, [fetchAdminConfig, fetchData, isSignedIn]);

  // ── Process (YouTube URL) ──────────────────────────────────────────────
  const handleProcess = async (url: string, numClips: number) => {
    setProcessing(true);
    try {
      const res = await authenticatedFetch('/process', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, num_clips: numClips }),
      });
      if (res?.ok) {
        showNotice('success', 'AI Pipeline engaged! Check History for progress.');
        setActiveTab('history');
        fetchData();
        return true;
      } else {
        showNotice('error', await extractErrorMessage(res, 'Processing failed'));
      }
    } catch {
      showNotice('error', 'Network error');
    } finally {
      setProcessing(false);
    }
    return false;
  };

  // ── Process (File Upload) ─────────────────────────────────────────────
  const handleUpload = async (file: File, numClips: number) => {
    setProcessing(true);
    try {
      const token = await getBearerToken();
      if (!token) {
        showNotice('error', 'Session is not authorized. Sign in again.');
        return;
      }
      const formData = new FormData();
      formData.append('file', file);
      formData.append('num_clips', String(numClips));
      const res = await fetch(`${API_BASE}${apiPath('/process/upload')}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });
      if (res?.ok) {
        showNotice('success', 'Upload started! Check History for progress.');
        setActiveTab('history');
        fetchData();
      } else {
        showNotice('error', await extractErrorMessage(res, 'Upload failed'));
      }
    } catch {
      showNotice('error', 'Upload failed');
    } finally {
      setProcessing(false);
    }
  };

  // ── YouTube batch upload ───────────────────────────────────────────────
  const handleYouTubeUpload = async (job: Job) => {
    const clips = job.results || job.shorts || [];
    if (!clips.length) { showNotice('error', 'No clips to upload'); return; }
    const uploads = clips.map((filename, i) => ({
      filename,
      title: `${job.video_title || job.filename || 'Short'} #${i + 1}`,
      description: '#Shorts',
      tags: ['Shorts'],
      privacy_status: adminConfig?.youtube_default_privacy || 'private',
    }));
    try {
      const res = await authenticatedFetch('/youtube/upload/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ uploads }),
      });
      const data = await readResponseBody(res, { endpoint: '/youtube/upload/batch', expectJson: true });
      if (res?.ok && data?.uploaded_count > 0) {
        showNotice('success', `Uploaded ${data.uploaded_count} clip${data.uploaded_count > 1 ? 's' : ''} to YouTube!`);
      } else {
        const errorMsg = data?.detail || data?.message || 'YouTube upload failed';
        showNotice('error', errorMsg);
      }
    } catch (e) {
      console.error('YouTube upload error:', e);
      showNotice('error', 'YouTube upload failed - check configuration and connection');
    }
  };

  // ── YouTube OAuth ──────────────────────────────────────────────────────
  const handleConnectYouTube = useCallback(async () => {
    try {
      const res = await authenticatedFetch('/youtube/auth/start', { method: 'POST' });
      if (!res?.ok) {
        showNotice('error', await extractErrorMessage(res, 'Failed to start YouTube auth'));
        return;
      }
      const data = await readResponseBody(res, { endpoint: '/youtube/auth/start', expectJson: true });
      if (!data?.auth_url) {
        showNotice('error', 'YouTube auth returned an invalid response.');
        return;
      }
      const popup = window.open(data.auth_url, 'youtube-auth', 'width=620,height=720,scrollbars=yes');
      if (!popup) {
        showNotice('error', 'Popup was blocked. Allow popups and try again.');
        return;
      }
      const onMessage = (e: MessageEvent) => {
        if (e.data?.type === 'shortmaker-youtube-auth') {
          window.removeEventListener('message', onMessage);
          if (e.data.success) {
            showNotice('success', 'YouTube account connected!');
            fetchAdminConfig();
            fetchData();
          } else {
            showNotice('error', e.data.message || 'YouTube connection failed');
          }
        }
      };
      window.addEventListener('message', onMessage);
      const poll = setInterval(() => { if (popup?.closed) { clearInterval(poll); window.removeEventListener('message', onMessage); } }, 600);
    } catch { showNotice('error', 'YouTube auth error'); }
  }, [authenticatedFetch, extractErrorMessage, fetchAdminConfig, fetchData, readResponseBody]);

  const handleDisconnectYouTube = async () => {
    try {
      const res = await authenticatedFetch('/youtube/connection', { method: 'DELETE' });
      if (res?.ok) {
        showNotice('info', 'YouTube disconnected.');
        fetchAdminConfig();
        fetchData();
      } else {
        showNotice('error', await extractErrorMessage(res, 'Disconnect failed'));
      }
    } catch {
      showNotice('error', 'Disconnect failed');
    }
  };

  // ── AI Config save ─────────────────────────────────────────────────────
  const handleSaveAIConfig = async (payload: object) => {
    setSettingsSaving(true);
    try {
      const res = await authenticatedFetch('/ai/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await readResponseBody(res, { endpoint: '/ai/config', expectJson: true });
      if (res?.ok) {
        showNotice('success', data?.message || 'Settings saved!');
        fetchAdminConfig();
        fetchData();
      } else {
        showNotice('error', data?.detail || 'Save failed');
      }
    } catch { showNotice('error', 'Save failed'); } finally { setSettingsSaving(false); }
  };

  const handleClipAccess = useCallback(async (filename: string, mode: 'open' | 'download' = 'open') => {
    const token = await getToken();
    if (!token) {
      showNotice('error', 'Your session expired. Sign in again to access generated clips.');
      return;
    }

    try {
      const res = await fetch(`${API_BASE}${apiPath(`/shorts/${encodeURIComponent(filename)}`)}`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!res.ok) {
        showNotice('error', await extractErrorMessage(res, 'Unable to access clip'));
        return;
      }

      const blob = await res.blob();
      const objectUrl = window.URL.createObjectURL(blob);

      if (mode === 'download') {
        const link = document.createElement('a');
        link.href = objectUrl;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
      } else {
        const preview = window.open(objectUrl, '_blank', 'noopener,noreferrer');
        if (!preview) {
          const link = document.createElement('a');
          link.href = objectUrl;
          link.target = '_blank';
          link.rel = 'noopener noreferrer';
          document.body.appendChild(link);
          link.click();
          link.remove();
        }
      }

      window.setTimeout(() => window.URL.revokeObjectURL(objectUrl), 60_000);
    } catch (error) {
      console.error(error);
      showNotice('error', 'Unable to access clip');
    }
  }, [apiPath, extractErrorMessage, getToken]);

  const pageSubtitles: Record<string, string> = {
    process:  'Launch a new AI extraction job',
    history:  'Track and download your generated clips',
    trends:   'Discover trending YouTube videos to process',
    settings: 'API keys, YouTube publishing & account settings',
  };

  if (!isLoaded) return null;

  const isAdmin = isAdminConsoleRoute || !!session?.is_admin;
  const canManageYouTube = isSignedIn;
  const youtubeConnected = !!(capabilities?.has_youtube_connection || adminConfig?.has_youtube_connection);

  return (
    <div className="app-shell">
      {!isSignedIn ? (
        <LandingPage />
      ) : (
        <div className={styles.workspace}>
          <Sidebar
            activeTab={activeTab}
            setActiveTab={setActiveTab}
            hasAdmin={isAdmin}
          />

          <main className={styles.main}>
            <div className={styles.contentHeader}>
              <div className={styles.pageTitle}>
                <h2>{activeTab.charAt(0).toUpperCase() + activeTab.slice(1)}</h2>
                <p className={styles.pageSubtitle}>{pageSubtitles[activeTab]}</p>
              </div>
              <div className={styles.headerActions}>
                {session && (
                  <div className={styles.quotaBadge} title={`${session.usage.used} of ${session.usage.limit} daily jobs used`}>
                    <span className={`material-symbols-outlined ${styles.quotaIcon}`}>data_usage</span>
                    {session.usage.used}/{session.usage.limit} today
                  </div>
                )}
                <div className={styles.liveIndicator}>
                  <span className="status-dot" />
                  AI Cloud Active
                </div>
              </div>
            </div>

            <div className={styles.tabContent}>
              {activeTab === 'process' && (
                <ProcessView
                  onProcess={async (url, numClips) => { await handleProcess(url, numClips); }}
                  onUpload={handleUpload}
                  processing={processing}
                  capabilities={capabilities}
                />
              )}
              {activeTab === 'history' && (
                <HistoryView
                  jobs={jobs}
                  apiBase={API_BASE}
                  youtubeConnected={youtubeConnected}
                  canManageYouTube={canManageYouTube}
                  onYouTubeUpload={handleYouTubeUpload}
                  onOpenClip={handleClipAccess}
                />
              )}
              {activeTab === 'trends' && (
                <TrendsView
                  apiFetch={authenticatedFetch}
                  showNotice={showNotice}
                  onProcessUrl={(url) => handleProcess(url, 5)}
                />
              )}
              {activeTab === 'settings' && (
                adminConfig ? (
                  <SettingsView
                    config={adminConfig}
                    session={session}
                    onSaveAIConfig={handleSaveAIConfig}
                    onConnectYouTube={handleConnectYouTube}
                    onDisconnectYouTube={handleDisconnectYouTube}
                    saving={settingsSaving}
                  />
                ) : (
                  <div className="empty-state">
                    <span className="material-symbols-outlined">settings</span>
                    <p>{adminConfigError || 'Loading admin settings...'}</p>
                    <button type="button" className="btn btn-secondary" onClick={fetchAdminConfig}>
                      Retry
                    </button>
                  </div>
                )
              )}
            </div>
          </main>

          <MobileNav
            activeTab={activeTab}
            setActiveTab={setActiveTab}
            hasAdmin={isAdmin}
          />
        </div>
      )}

      {notice && (
        <Notice type={notice.type} message={notice.message} onClear={() => setNotice(null)} />
      )}
    </div>
  );
}
