import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useUser, useAuth } from '@clerk/react';

import { Job, AdminConfig, Capabilities, SessionData, NoticeData, YouTubeStatus } from './types';
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
const CLERK_PUBLISHABLE_KEY = (import.meta as any).env.VITE_CLERK_PUBLISHABLE_KEY || '';
const API_UNAVAILABLE_BACKOFF_MS = 30_000;
const API_UNAVAILABLE_MESSAGE =
  'ShortMaker API is not reachable at http://127.0.0.1:8000. Start FastAPI or set VITE_API_BASE_URL.';
const CLERK_ISSUER_MISMATCH_DETAIL = 'Token issuer does not match configured Clerk issuer.';
const CLERK_ISSUER_MISMATCH_MESSAGE = 'Session is tied to a different Clerk instance. Sign in again.';
const ADMIN_ROUTE_PREFIX = '/ashmil2010';
const CLERK_ISSUER_SETTLE_MS = 15_000;

interface AppProps {
  adminStandalone?: boolean;
}

interface AppAuthContext {
  isLoaded: boolean;
  isSignedIn: boolean;
  getToken: () => Promise<string | null>;
  sessionClaims: Record<string, unknown> | null;
}

function normalizeIssuer(value: string): string {
  return String(value || '').trim().replace(/\/+$/, '');
}

function deriveIssuerFromPublishableKey(publishableKey: string): string {
  const raw = String(publishableKey || '').trim();
  const match = raw.match(/^pk_(?:test|live)_(.+)$/);
  if (!match) return '';

  try {
    const decoded = atob(match[1]).replace(/\$+$/, '');
    return normalizeIssuer(`https://${decoded}`);
  } catch {
    return '';
  }
}

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

function AppContent({ adminStandalone = false, auth }: { adminStandalone?: boolean; auth: AppAuthContext }) {
  const { isLoaded, isSignedIn, getToken, sessionClaims } = auth;
  const isAdminConsoleRoute =
    typeof window !== 'undefined' && window.location.pathname.startsWith(ADMIN_ROUTE_PREFIX);

  if (adminStandalone && !isAdminConsoleRoute) {
    return null;
  }

  if (!adminStandalone && isAdminConsoleRoute) {
    return null;
  }

  const noticeTimeoutRef = useRef<number | null>(null);
  const responseWarningsRef = useRef<Set<string>>(new Set());
  const apiUnavailableUntilRef = useRef(0);
  const apiOfflineNoticeRef = useRef(false);
  const issuerMismatchHandledRef = useRef(false);
  const issuerMismatchDetectedAtRef = useRef<number | null>(null);
  const protectedPollInFlightRef = useRef(false);
  const authFailureNoticeRef = useRef(false);
  const hasWorkspaceAccess = isAdminConsoleRoute || isSignedIn;
  const expectedClerkIssuer = deriveIssuerFromPublishableKey(CLERK_PUBLISHABLE_KEY);
  const sessionIssuer = normalizeIssuer(String(sessionClaims?.iss || ''));
  const frontendIssuerMismatch = Boolean(expectedClerkIssuer && sessionIssuer && sessionIssuer !== expectedClerkIssuer);

  const [jobs, setJobs] = useState<Job[]>([]);
  const [adminConfig, setAdminConfig] = useState<AdminConfig | null>(null);
  const [adminConfigError, setAdminConfigError] = useState<string | null>(null);
  const [youtubeStatus, setYouTubeStatus] = useState<YouTubeStatus | null>(null);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [session, setSession] = useState<SessionData | null>(null);
  const [notice, setNotice] = useState<NoticeData | null>(null);
  const [activeTab, setActiveTab] = useState<string>(isAdminConsoleRoute ? 'settings' : 'process');
  const [processing, setProcessing] = useState<boolean>(false);
  const [settingsSaving, setSettingsSaving] = useState<boolean>(false);
  const [youtubeSaving, setYouTubeSaving] = useState<boolean>(false);
  const [backendSessionVerified, setBackendSessionVerified] = useState<boolean>(false);
  const [backendAuthMessage, setBackendAuthMessage] = useState<string | null>(null);

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

    setJobs([]);
    setSession(null);
    setAdminConfig(null);
    setAdminConfigError(null);
    setYouTubeStatus(null);
    setBackendSessionVerified(false);
    const now = Date.now();
    if (!issuerMismatchDetectedAtRef.current) {
      issuerMismatchDetectedAtRef.current = now;
      setBackendAuthMessage('Finishing sign-in. Waiting for Clerk session to refresh...');
      showNotice('info', 'Finishing sign-in. Waiting for Clerk session to refresh...');
      return true;
    }

    if (now - issuerMismatchDetectedAtRef.current < CLERK_ISSUER_SETTLE_MS) {
      return true;
    }

    issuerMismatchHandledRef.current = true;
    setBackendAuthMessage(`${CLERK_ISSUER_MISMATCH_MESSAGE} If this persists, sign out and sign in again.`);
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
    setYouTubeStatus(null);
    setBackendSessionVerified(false);
    setAdminConfigError('Session is not authorized. Sign in again.');
    setBackendAuthMessage('Session is not authorized. Sign in again.');
    if (!authFailureNoticeRef.current) {
      authFailureNoticeRef.current = true;
      showNotice('error', 'Session is not authorized. Sign in again.');
    }
    return true;
  }, [handleIssuerMismatch, showNotice]);

  const authenticatedProtectedFetch = useCallback(async (
    path: string,
    options: RequestInit = {},
    tokenOverride: string | null = null,
  ) => {
    const res = await authenticatedFetch(path, options, tokenOverride);
    if (await handleProtectedAuthFailure(res)) {
      return null;
    }
    return res;
  }, [authenticatedFetch, handleProtectedAuthFailure]);

  const trendsApiFetch = useCallback(async (
    path: string,
    options: RequestInit = {},
  ) => {
    if (isAdminConsoleRoute) {
      return publicFetch(path, options);
    }
    return authenticatedProtectedFetch(path, options);
  }, [authenticatedProtectedFetch, isAdminConsoleRoute, publicFetch]);

  const fetchData = useCallback(async () => {
    if (!isLoaded || !hasWorkspaceAccess) return;
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
    if (Date.now() < apiUnavailableUntilRef.current) return;
    if (protectedPollInFlightRef.current) return;
    if (frontendIssuerMismatch) {
      setBackendSessionVerified(false);
      if (!issuerMismatchDetectedAtRef.current) {
        issuerMismatchDetectedAtRef.current = Date.now();
        setBackendAuthMessage('Finishing sign-in. Waiting for Clerk session to refresh...');
      }
      if (!issuerMismatchHandledRef.current && Date.now() - issuerMismatchDetectedAtRef.current >= CLERK_ISSUER_SETTLE_MS) {
        issuerMismatchHandledRef.current = true;
        setJobs([]);
        setSession(null);
        setAdminConfig(null);
        setAdminConfigError(null);
        setBackendAuthMessage(`${CLERK_ISSUER_MISMATCH_MESSAGE} If this persists, sign out and sign in again.`);
        showNotice('error', `${CLERK_ISSUER_MISMATCH_MESSAGE} If this persists, sign out and sign in again.`);
      }
      return;
    }

    protectedPollInFlightRef.current = true;
    try {
      const token = isAdminConsoleRoute ? null : await getBearerToken();
      if (!isAdminConsoleRoute && !token) {
        return;
      }

      const [jobsRes, capsRes, sessionRes, youtubeRes] = await Promise.all([
        (isAdminConsoleRoute ? publicFetch('/jobs/recent') : authenticatedFetch('/jobs/recent', {}, token)),
        publicFetch('/capabilities'),
        (isAdminConsoleRoute ? Promise.resolve(null) : authenticatedRootFetch('/session', {}, token)),
        (isAdminConsoleRoute ? publicFetch('/youtube/status') : authenticatedFetch('/youtube/status', {}, token)),
      ]);

      if (await handleProtectedAuthFailure(jobsRes)) return;
      if (await handleProtectedAuthFailure(sessionRes)) return;
      if (await handleProtectedAuthFailure(youtubeRes)) return;

      const protectedResponses = isAdminConsoleRoute ? [jobsRes, youtubeRes] : [jobsRes, sessionRes, youtubeRes];
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
      issuerMismatchDetectedAtRef.current = null;
      issuerMismatchHandledRef.current = false;
      setBackendAuthMessage(null);

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
      if (youtubeRes?.ok) {
        const youtubePayload = await readResponseBody(youtubeRes, { endpoint: '/youtube/status', expectJson: true });
        if (youtubePayload) {
          setYouTubeStatus(youtubePayload as YouTubeStatus);
        }
      }
      if (sessionRes?.ok) {
        const sessionPayload = await readResponseBody(sessionRes, { endpoint: '/session', expectJson: true });
        if (sessionPayload) {
          setSession(sessionPayload as SessionData);
          setBackendSessionVerified(true);
        }
      }
    } catch (e) {
      console.error(e);
    } finally {
      protectedPollInFlightRef.current = false;
    }
  }, [authenticatedFetch, authenticatedRootFetch, frontendIssuerMismatch, getBearerToken, handleProtectedAuthFailure, hasWorkspaceAccess, isAdminConsoleRoute, isLoaded, publicFetch, readResponseBody, showNotice]);

  useEffect(() => {
    if (!hasWorkspaceAccess) {
      setBackendSessionVerified(false);
      setBackendAuthMessage(null);
      setJobs([]);
      setSession(null);
      setAdminConfig(null);
      setAdminConfigError(null);
      setYouTubeStatus(null);
      authFailureNoticeRef.current = false;
      issuerMismatchHandledRef.current = false;
      issuerMismatchDetectedAtRef.current = null;
      protectedPollInFlightRef.current = false;
    }
  }, [hasWorkspaceAccess]);

  const fetchAdminConfig = useCallback(async () => {
    if (!isAdminConsoleRoute && (!isSignedIn || !session?.is_admin)) {
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
          issuerMismatchDetectedAtRef.current = null;
          issuerMismatchHandledRef.current = false;
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
    if (!isLoaded || !hasWorkspaceAccess) return;
    fetchData();
    fetchAdminConfig();
    const interval = setInterval(fetchData, 8000);
    return () => clearInterval(interval);
  }, [fetchAdminConfig, fetchData, hasWorkspaceAccess, isLoaded]);

  const handleProcess = useCallback(async (url: string, numClips: number) => {
    setProcessing(true);
    try {
      const requestInit: RequestInit = {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, num_clips: numClips }),
      };
      const res = isAdminConsoleRoute
        ? await publicFetch('/process', requestInit)
        : await authenticatedFetch('/process', requestInit);
      if (res?.ok) {
        showNotice('success', 'AI Pipeline engaged! Check History for progress.');
        setActiveTab('history');
        fetchData();
        return true;
      }
      showNotice('error', await extractErrorMessage(res, 'Processing failed'));
    } catch {
      showNotice('error', 'Network error');
    } finally {
      setProcessing(false);
    }
    return false;
  }, [authenticatedFetch, extractErrorMessage, fetchData, isAdminConsoleRoute, publicFetch, showNotice]);

  const handleUpload = useCallback(async (file: File, numClips: number) => {
    setProcessing(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('num_clips', String(numClips));
      const requestInit: RequestInit = { method: 'POST', body: formData };
      if (!isAdminConsoleRoute) {
        const token = await getBearerToken();
        if (!token) {
          showNotice('error', 'Session is not authorized. Sign in again.');
          return;
        }
        requestInit.headers = { Authorization: `Bearer ${token}` };
      }
      const res = await fetch(`${API_BASE}${apiPath('/process/upload')}`, requestInit);
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
  }, [API_BASE, apiPath, extractErrorMessage, fetchData, getBearerToken, isAdminConsoleRoute, showNotice]);

  const handleYouTubeUpload = useCallback(async (job: Job) => {
    const clips = job.results || job.shorts || [];
    if (!clips.length) {
      showNotice('error', 'No clips to upload');
      return;
    }
    const uploads = clips.map((filename, i) => ({
      filename,
      title: `${job.video_title || job.filename || 'Short'} #${i + 1}`,
      description: '#Shorts',
      tags: ['Shorts'],
      privacy_status: youtubeStatus?.default_privacy_status || adminConfig?.youtube_default_privacy || 'private',
    }));
    try {
      const requestInit: RequestInit = {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ uploads }),
      };
      const res = isAdminConsoleRoute
        ? await publicFetch('/youtube/upload/batch', requestInit)
        : await authenticatedFetch('/youtube/upload/batch', requestInit);
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
  }, [adminConfig?.youtube_default_privacy, authenticatedFetch, isAdminConsoleRoute, publicFetch, readResponseBody, showNotice, youtubeStatus?.default_privacy_status]);

  const handleConnectYouTube = useCallback(async () => {
    try {
      const res = isAdminConsoleRoute
        ? await publicFetch('/youtube/auth/start', { method: 'POST' })
        : await authenticatedFetch('/youtube/auth/start', { method: 'POST' });
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
      const poll = setInterval(() => {
        if (popup?.closed) {
          clearInterval(poll);
          window.removeEventListener('message', onMessage);
        }
      }, 600);
    } catch {
      showNotice('error', 'YouTube auth error');
    }
  }, [authenticatedFetch, extractErrorMessage, fetchAdminConfig, fetchData, isAdminConsoleRoute, publicFetch, readResponseBody, showNotice]);

  const handleDisconnectYouTube = useCallback(async () => {
    try {
      const res = isAdminConsoleRoute
        ? await publicFetch('/youtube/connection', { method: 'DELETE' })
        : await authenticatedFetch('/youtube/connection', { method: 'DELETE' });
      if (res?.ok) {
        showNotice('info', 'YouTube disconnected.');
        fetchData();
      } else {
        showNotice('error', await extractErrorMessage(res, 'Disconnect failed'));
      }
    } catch {
      showNotice('error', 'Disconnect failed');
    }
  }, [authenticatedFetch, extractErrorMessage, fetchData, isAdminConsoleRoute, publicFetch, showNotice]);

  const handleSaveYouTubeConfig = useCallback(async (payload: object) => {
    setYouTubeSaving(true);
    try {
      const requestInit: RequestInit = {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      };
      const res = isAdminConsoleRoute
        ? await publicFetch('/youtube/config', requestInit)
        : await authenticatedFetch('/youtube/config', requestInit);
      const data = await readResponseBody(res, { endpoint: '/youtube/config', expectJson: true });
      if (res?.ok) {
        showNotice('success', data?.message || 'YouTube settings saved.');
        fetchData();
      } else {
        showNotice('error', data?.detail || 'Unable to save YouTube settings.');
      }
    } catch {
      showNotice('error', 'Unable to save YouTube settings.');
    } finally {
      setYouTubeSaving(false);
    }
  }, [authenticatedFetch, fetchData, isAdminConsoleRoute, publicFetch, readResponseBody, showNotice]);

  const handleSaveAIConfig = useCallback(async (payload: object) => {
    setSettingsSaving(true);
    try {
      const requestInit: RequestInit = {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      };
      const res = isAdminConsoleRoute
        ? await publicFetch('/ai/config', requestInit)
        : await authenticatedFetch('/ai/config', requestInit);
      const data = await readResponseBody(res, { endpoint: '/ai/config', expectJson: true });
      if (res?.ok) {
        showNotice('success', data?.message || 'Settings saved!');
        fetchAdminConfig();
        fetchData();
      } else {
        showNotice('error', data?.detail || 'Save failed');
      }
    } catch {
      showNotice('error', 'Save failed');
    } finally {
      setSettingsSaving(false);
    }
  }, [authenticatedFetch, fetchAdminConfig, fetchData, isAdminConsoleRoute, publicFetch, readResponseBody, showNotice]);

  const handleClipAccess = useCallback(async (filename: string, mode: 'open' | 'download' = 'open') => {
    try {
      const headers: HeadersInit = {};
      if (!isAdminConsoleRoute) {
        const token = await getToken();
        if (!token) {
          showNotice('error', 'Your session expired. Sign in again to access generated clips.');
          return;
        }
        headers.Authorization = `Bearer ${token}`;
      }
      const res = await fetch(`${API_BASE}${apiPath(`/shorts/${encodeURIComponent(filename)}`)}`, { headers });

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
  }, [API_BASE, apiPath, extractErrorMessage, getToken, isAdminConsoleRoute, showNotice]);

  const pageSubtitles: Record<string, string> = {
    process: 'Launch a new AI extraction job',
    history: 'Track and download your generated clips',
    trends: 'Discover trending YouTube videos to process',
    settings: 'API keys, YouTube publishing & account settings',
  };

  if (!isLoaded) return null;

  const isAdmin = isAdminConsoleRoute || !!session?.is_admin;
  const canManageYouTube = hasWorkspaceAccess;
  const youtubeConnected = !!youtubeStatus?.connected;

  return (
    <div className="app-shell">
      {!hasWorkspaceAccess ? (
        <LandingPage />
      ) : (
        <div className={styles.workspace}>
          <Sidebar
            activeTab={activeTab}
            setActiveTab={setActiveTab}
            hasAdmin={isAdmin}
            showUser={!isAdminConsoleRoute && isSignedIn}
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
                    apiFetch={trendsApiFetch}
                    showNotice={showNotice}
                    onProcessUrl={(url) => handleProcess(url, 5)}
                    authReady={isAdminConsoleRoute || backendSessionVerified}
                    authMessage={backendAuthMessage}
                  />
              )}
              {activeTab === 'settings' && (
                <SettingsView
                  config={adminConfig}
                  youtubeStatus={youtubeStatus}
                  session={session}
                  isAdmin={isAdmin}
                  adminConfigError={adminConfigError}
                  onRetryAdminConfig={fetchAdminConfig}
                  onSaveAIConfig={handleSaveAIConfig}
                  onSaveYouTubeConfig={handleSaveYouTubeConfig}
                  onConnectYouTube={handleConnectYouTube}
                  onDisconnectYouTube={handleDisconnectYouTube}
                  saving={settingsSaving}
                  youtubeSaving={youtubeSaving}
                />
              )}
            </div>
          </main>

          <MobileNav
            activeTab={activeTab}
            setActiveTab={setActiveTab}
            hasAdmin={isAdmin}
            showUser={!isAdminConsoleRoute && isSignedIn}
          />
        </div>
      )}

      {notice && (
        <Notice type={notice.type} message={notice.message} onClear={() => setNotice(null)} />
      )}
    </div>
  );
}

function AppWithClerk() {
  const { isLoaded, isSignedIn } = useUser();
  const { getToken, sessionClaims } = useAuth();

  const auth = {
    isLoaded,
    isSignedIn: Boolean(isSignedIn),
    getToken: async () => (await getToken()) || null,
    sessionClaims: (sessionClaims as Record<string, unknown> | null) || null,
  };

  return <AppContent auth={auth} />;
}

export default function App({ adminStandalone = false }: AppProps) {
  if (adminStandalone) {
    const adminAuth: AppAuthContext = {
      isLoaded: true,
      isSignedIn: false,
      getToken: async () => null,
      sessionClaims: null,
    };
    return <AppContent adminStandalone auth={adminAuth} />;
  }

  return <AppWithClerk />;
}
