const ADMIN_MODE = window.location.pathname === '/ashmil2010';
const API_BASE_URL = ADMIN_MODE ? `${window.location.origin}/ashmil2010` : window.location.origin;
const POLL_INTERVAL = 3000;
const MAX_POLL_ERRORS = 5;
const STORAGE_PREFIX = ADMIN_MODE ? 'shortmaker_admin' : 'shortmaker';
const API_KEY_STORAGE_KEY = `${STORAGE_PREFIX}_api_key`;
const ACTIVE_JOB_STORAGE_KEY = `${STORAGE_PREFIX}_active_job`;
const YOUTUBE_STATUS_STORAGE_KEY = `${STORAGE_PREFIX}_youtube_status`;
const ADMIN_PREFILL_YOUTUBE_CLIENT_ID = '378449025996-fg0klorgtirhi075nhbfhnn7nkkoe8id.apps.googleusercontent.com';
const ADMIN_PREFILL_YOUTUBE_CLIENT_SECRET = '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';
const LOCALHOST_YOUTUBE_REDIRECT_URI = 'http://localhost:8000/youtube/oauth/callback';
const LOOPBACK_YOUTUBE_REDIRECT_URI = 'http://127.0.0.1:8000/youtube/oauth/callback';

const elements = {
    appTitle: document.getElementById('app-title'),
    appTagline: document.getElementById('app-tagline'),
    urlInput: document.getElementById('youtube-url'),
    fileInput: document.getElementById('video-file'),
    uploadDropzone: document.getElementById('upload-dropzone'),
    uploadFileMeta: document.getElementById('upload-file-meta'),
    uploadSupportCopy: document.getElementById('upload-support-copy'),
    numClipsSelect: document.getElementById('num-clips'),
    generateBtn: document.getElementById('generate-btn'),
    modeYoutubeBtn: document.getElementById('mode-youtube-btn'),
    modeUploadBtn: document.getElementById('mode-upload-btn'),
    youtubeInputPanel: document.getElementById('youtube-input-panel'),
    uploadInputPanel: document.getElementById('upload-input-panel'),
    statusSection: document.getElementById('status-section'),
    statusStage: document.getElementById('status-stage'),
    progressFill: document.getElementById('progress-fill'),
    progressText: document.getElementById('progress-text'),
    statusMessage: document.getElementById('status-message'),
    errorSection: document.getElementById('error-section'),
    errorMessage: document.getElementById('error-message'),
    retryBtn: document.getElementById('retry-btn'),
    resultsSection: document.getElementById('results-section'),
    videoTitle: document.getElementById('video-title'),
    resultsSummary: document.getElementById('results-summary'),
    uploadAllYouTubeBtn: document.getElementById('upload-all-youtube-btn'),
    uploadAllYouTubeStatus: document.getElementById('upload-all-youtube-status'),
    uploadAllYouTubeLinks: document.getElementById('upload-all-youtube-links'),
    copyAllCaptionsBtn: document.getElementById('copy-all-captions-btn'),
    shortsGrid: document.getElementById('shorts-grid'),
    newVideoBtn: document.getElementById('new-video-btn'),
    recentJobsEmpty: document.getElementById('recent-jobs-empty'),
    recentJobsList: document.getElementById('recent-jobs-list'),
    refreshJobsBtn: document.getElementById('refresh-jobs-btn'),
    aiSettingsToggle: document.getElementById('ai-settings-toggle'),
    aiConfigSection: document.getElementById('ai-config-section'),
    aiProviderSettings: document.getElementById('ai-provider-settings'),
    aiFeaturesGrid: document.getElementById('ai-features-grid'),
    configPanelTitle: document.getElementById('config-panel-title'),
    configPanelDesc: document.getElementById('config-panel-desc'),
    saveConfigLabel: document.getElementById('save-config-label'),
    geminiApiKey: document.getElementById('gemini-api-key'),
    groqApiKey: document.getElementById('groq-api-key'),
    firecrawlApiKey: document.getElementById('firecrawl-api-key'),
    youtubeClientId: document.getElementById('youtube-client-id'),
    youtubeClientSecret: document.getElementById('youtube-client-secret'),
    youtubeDefaultPrivacy: document.getElementById('youtube-default-privacy'),
    aiModelSelect: document.getElementById('ai-model-select'),
    validateKeyBtn: document.getElementById('validate-key-btn'),
    saveAiConfigBtn: document.getElementById('save-ai-config-btn'),
    aiConfigMessage: document.getElementById('ai-config-message'),
    toggleKeyVisibility: document.getElementById('toggle-key-visibility'),
    toggleGroqKeyVisibility: document.getElementById('toggle-groq-key-visibility'),
    toggleFirecrawlKeyVisibility: document.getElementById('toggle-firecrawl-key-visibility'),
    toggleYouTubeClientIdVisibility: document.getElementById('toggle-youtube-client-id-visibility'),
    toggleYouTubeClientSecretVisibility: document.getElementById('toggle-youtube-client-secret-visibility'),
    connectYouTubeBtn: document.getElementById('connect-youtube-btn'),
    disconnectYouTubeBtn: document.getElementById('disconnect-youtube-btn'),
    youtubeRedirectHint: document.getElementById('youtube-redirect-hint'),
    youtubeConnectStatus: document.getElementById('youtube-connect-status'),
    aiStatusBadge: document.getElementById('ai-status-badge'),
    aiBadgeText: document.getElementById('ai-badge-text'),
    aiIndicator: document.getElementById('ai-indicator'),
    authPanel: document.getElementById('auth-panel'),
    authDescription: document.getElementById('auth-description'),
    browserApiKey: document.getElementById('browser-api-key'),
    toggleBrowserKeyVisibility: document.getElementById('toggle-browser-key-visibility'),
    saveBrowserKeyBtn: document.getElementById('save-browser-key-btn'),
    clearBrowserKeyBtn: document.getElementById('clear-browser-key-btn'),
    capabilityAuth: document.getElementById('capability-auth'),
    capabilityInputs: document.getElementById('capability-inputs'),
    capabilityScale: document.getElementById('capability-scale'),
    authModePill: document.getElementById('auth-mode-pill'),
    uploadSupportPill: document.getElementById('upload-support-pill'),
    recentJobsPill: document.getElementById('recent-jobs-pill'),
    trendTopic: document.getElementById('trend-topic'),
    trendLocation: document.getElementById('trend-location'),
    discoverTrendsBtn: document.getElementById('discover-trends-btn'),
    autoTrendBtn: document.getElementById('auto-trend-btn'),
    trendStatus: document.getElementById('trend-status'),
    trendResultsEmpty: document.getElementById('trend-results-empty'),
    trendResultsList: document.getElementById('trend-results-list'),
};

const state = {
    currentJobId: null,
    pollInterval: null,
    pollErrorCount: 0,
    aiConfigVisible: false,
    authMode: null,
    capabilities: null,
    sourceMode: 'youtube',
    recentJobs: [],
    lastResults: [],
    lastShortEntries: [],
    trendCandidates: [],
    youtubeStatus: {
        hasClientConfig: false,
        connected: false,
        defaultPrivacyStatus: 'private',
    },
    previewUrls: [],
};

if (ADMIN_MODE) {
    document.title = 'ShortMaker Admin - YouTube OAuth';
}

function configureAdminExperience() {
    if (!ADMIN_MODE) return;
    if (elements.appTitle) elements.appTitle.textContent = 'YouTube OAuth Admin';
    if (elements.appTagline) {
        elements.appTagline.textContent = 'Save the Google OAuth client, confirm the redirect URI, and connect the YouTube account used for publishing.';
    }
}

function showSection(section) {
    elements.statusSection.classList.add('hidden');
    elements.errorSection.classList.add('hidden');
    elements.resultsSection.classList.add('hidden');
    if (section === 'status') elements.statusSection.classList.remove('hidden');
    if (section === 'error') elements.errorSection.classList.remove('hidden');
    if (section === 'results') elements.resultsSection.classList.remove('hidden');
}

function setLoading(loading, text) {
    elements.generateBtn.disabled = loading;
    elements.urlInput.disabled = loading;
    elements.fileInput.disabled = loading;
    elements.numClipsSelect.disabled = loading;
    elements.modeYoutubeBtn.disabled = loading;
    elements.modeUploadBtn.disabled = loading;
    elements.generateBtn.classList.toggle('loading', loading);
    elements.generateBtn.querySelector('.btn-text').textContent = text || (state.sourceMode === 'upload' ? 'Upload and Generate Shorts' : 'Generate Viral Shorts');
}

function setSourceMode(mode) {
    state.sourceMode = mode;
    elements.modeYoutubeBtn.classList.toggle('active', mode === 'youtube');
    elements.modeUploadBtn.classList.toggle('active', mode === 'upload');
    elements.youtubeInputPanel.classList.toggle('hidden', mode !== 'youtube');
    elements.uploadInputPanel.classList.toggle('hidden', mode !== 'upload');
    if (!elements.generateBtn.disabled) {
        setLoading(false);
    }
}

function formatStage(stage) {
    return {
        queued: 'Queued',
        starting: 'Starting',
        downloading: 'Acquiring Source',
        processing: 'Preparing',
        transcribing: 'Transcribing',
        analyzing: 'Analyzing',
        generating: 'Rendering Shorts',
        complete: 'Complete',
        error: 'Error',
    }[stage] || 'Processing';
}

function updateProgress(stage, progress, message) {
    elements.statusStage.textContent = formatStage(stage);
    elements.progressFill.style.width = `${Math.max(0, Math.min(100, progress || 0))}%`;
    elements.progressText.textContent = `${Math.max(0, Math.min(100, progress || 0))}%`;
    elements.statusMessage.textContent = message || 'Processing...';
}

function showError(message) {
    elements.errorMessage.textContent = message;
    showSection('error');
    setLoading(false);
    stopPolling();
}

function setTrendStatus(message, type = 'info') {
    elements.trendStatus.textContent = message;
    elements.trendStatus.dataset.state = type;
}

function clearPreviewUrls() {
    state.previewUrls.forEach((url) => URL.revokeObjectURL(url));
    state.previewUrls = [];
}

function getStoredApiKey() {
    return (localStorage.getItem(API_KEY_STORAGE_KEY) || '').trim();
}

function setStoredApiKey(value) {
    if (value && value.trim()) localStorage.setItem(API_KEY_STORAGE_KEY, value.trim());
    else localStorage.removeItem(API_KEY_STORAGE_KEY);
}

function getStoredActiveJob() {
    try {
        return JSON.parse(localStorage.getItem(ACTIVE_JOB_STORAGE_KEY) || 'null');
    } catch {
        return null;
    }
}

function setStoredActiveJob(payload) {
    localStorage.setItem(ACTIVE_JOB_STORAGE_KEY, JSON.stringify(payload));
}

function clearStoredActiveJob() {
    localStorage.removeItem(ACTIVE_JOB_STORAGE_KEY);
}

function getStoredYouTubeStatus() {
    try {
        return JSON.parse(localStorage.getItem(YOUTUBE_STATUS_STORAGE_KEY) || 'null');
    } catch {
        return null;
    }
}

function setStoredYouTubeStatus(payload) {
    if (!payload) {
        localStorage.removeItem(YOUTUBE_STATUS_STORAGE_KEY);
        return;
    }
    localStorage.setItem(YOUTUBE_STATUS_STORAGE_KEY, JSON.stringify(payload));
}

function clearStoredYouTubeStatus() {
    localStorage.removeItem(YOUTUBE_STATUS_STORAGE_KEY);
}

function formatDuration(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) return '';
    const mins = Math.floor(value / 60);
    const secs = Math.floor(value % 60);
    if (mins >= 60) return `${Math.floor(mins / 60)}h ${mins % 60}m`;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function formatFileSize(bytes) {
    if (!bytes) return '';
    const units = ['B', 'KB', 'MB', 'GB'];
    let value = bytes;
    let index = 0;
    while (value >= 1024 && index < units.length - 1) {
        value /= 1024;
        index += 1;
    }
    return `${value.toFixed(value >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

function relativeTime(iso) {
    if (!iso) return 'Unknown';
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return 'Unknown';
    const minutes = Math.round((Date.now() - date.getTime()) / 60000);
    if (Math.abs(minutes) < 1) return 'Just now';
    if (Math.abs(minutes) < 60) return `${Math.abs(minutes)}m ${minutes >= 0 ? 'ago' : 'from now'}`;
    const hours = Math.round(minutes / 60);
    if (Math.abs(hours) < 24) return `${Math.abs(hours)}h ${hours >= 0 ? 'ago' : 'from now'}`;
    const days = Math.round(hours / 24);
    return `${Math.abs(days)}d ${days >= 0 ? 'ago' : 'from now'}`;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text ?? '';
    return div.innerHTML;
}

function truncate(text, max = 72) {
    const value = String(text || '').trim();
    return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

function isValidYouTubeUrl(value) {
    try {
        const url = new URL(value);
        const host = url.hostname.replace(/^www\./, '');
        return host === 'youtube.com' || host.endsWith('.youtube.com') || host === 'youtu.be' || host === 'youtube-nocookie.com' || host.endsWith('.youtube-nocookie.com');
    } catch {
        return false;
    }
}

function getViralityColor(score) {
    if (score >= 8) return '#14b8a6';
    if (score >= 6) return '#f59e0b';
    if (score >= 4) return '#38bdf8';
    return '#71717a';
}

function getViralityLabel(score) {
    if (score >= 9) return 'Viral';
    if (score >= 7) return 'High';
    if (score >= 5) return 'Good';
    if (score >= 3) return 'Fair';
    return 'Low';
}

function formatReason(reason) {
    return {
        question: 'Question',
        strong_statement: 'Strong Statement',
        emotional: 'Emotional',
        hook: 'Hook',
        funny: 'Funny',
        surprising: 'Surprising',
        educational: 'Educational',
        dramatic: 'Dramatic',
        controversial: 'Controversial',
        inspiring: 'Inspiring',
        highlight: 'Best Moment',
        general: 'Highlight',
    }[reason] || 'Highlight';
}

function flashButton(button, text) {
    if (!button) return;
    const previous = button.dataset.label || button.textContent;
    button.dataset.label = previous;
    button.textContent = text;
    window.setTimeout(() => {
        button.textContent = previous;
    }, 1400);
}

async function copyText(text, button) {
    if (!text) return;
    try {
        await navigator.clipboard.writeText(text);
        flashButton(button, 'Copied');
    } catch {
        flashButton(button, 'Copy failed');
    }
}

function toggleFieldVisibility(input, button) {
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    button.textContent = show ? '🙈' : '👁️';
}

function normalizeAdminYouTubeRedirectUri(value) {
    if (!ADMIN_MODE || !value) return value;
    return String(value).split(LOCALHOST_YOUTUBE_REDIRECT_URI).join(LOOPBACK_YOUTUBE_REDIRECT_URI);
}

function normalizeAdminYouTubeAuthUrl(value) {
    if (!ADMIN_MODE || !value) return value;
    return String(value)
        .split(encodeURIComponent(LOCALHOST_YOUTUBE_REDIRECT_URI)).join(encodeURIComponent(LOOPBACK_YOUTUBE_REDIRECT_URI))
        .split(LOCALHOST_YOUTUBE_REDIRECT_URI).join(LOOPBACK_YOUTUBE_REDIRECT_URI);
}

function updateUploadMeta() {
    const file = elements.fileInput.files && elements.fileInput.files[0];
    elements.uploadFileMeta.textContent = file ? `${file.name} • ${formatFileSize(file.size)}` : 'No file selected';
}

async function parseError(response) {
    try {
        const payload = await response.json();
        return payload.detail || payload.message || 'Request failed';
    } catch {
        return 'Request failed';
    }
}

async function fetchAuthMode(force = false) {
    if (state.authMode && !force) return state.authMode;
    if (ADMIN_MODE) {
        state.authMode = { requires_api_key: false, mode: 'admin', api_key_count: 0 };
        return state.authMode;
    }
    try {
        const response = await fetch(`${API_BASE_URL}/auth/mode`);
        state.authMode = response.ok ? await response.json() : { requires_api_key: false, mode: 'quick', api_key_count: 0 };
    } catch {
        state.authMode = { requires_api_key: false, mode: 'quick', api_key_count: 0 };
    }
    return state.authMode;
}

async function fetchCapabilities() {
    try {
        const response = await fetch(`${API_BASE_URL}/capabilities`);
        if (response.ok) state.capabilities = await response.json();
    } catch {
        state.capabilities = null;
    }
}

function renderCapabilities() {
    configureAdminExperience();
    const auth = state.capabilities ? {
        requires_api_key: !!state.capabilities.requires_api_key,
        mode: state.capabilities.auth_mode || (ADMIN_MODE ? 'admin' : 'quick'),
        api_key_count: state.capabilities.api_key_count || 0,
    } : (state.authMode || { requires_api_key: false, mode: ADMIN_MODE ? 'admin' : 'quick', api_key_count: 0 });
    const caps = state.capabilities || {};
    const requiresKey = !!auth.requires_api_key;
    elements.authPanel.classList.toggle('hidden', ADMIN_MODE || !requiresKey);
    elements.browserApiKey.value = getStoredApiKey();
    elements.aiSettingsToggle.classList.toggle('hidden', ADMIN_MODE);
    elements.aiProviderSettings.classList.toggle('hidden', ADMIN_MODE);
    elements.aiFeaturesGrid.classList.toggle('hidden', ADMIN_MODE);
    elements.validateKeyBtn.classList.toggle('hidden', ADMIN_MODE);
    elements.configPanelTitle.textContent = ADMIN_MODE ? 'YouTube OAuth' : 'AI Configuration';
    elements.configPanelDesc.textContent = ADMIN_MODE
        ? 'This admin page only manages the Google OAuth client and YouTube connection used for publishing.'
        : 'Configure AI-powered clip detection and transcription. Keys are stored on this server, not in the page source.';
    elements.saveConfigLabel.textContent = ADMIN_MODE ? '💾 Save OAuth Settings' : '💾 Save AI Settings';
    if (ADMIN_MODE) {
        elements.aiConfigSection.classList.remove('hidden');
    }
    elements.authDescription.textContent = ADMIN_MODE
        ? 'Admin console uses the current server-side AI configuration without browser API keys.'
        : (requiresKey
            ? (getStoredApiKey() ? 'A browser API key is saved and will be sent automatically.' : 'Save a valid API key in this browser before starting or reopening protected jobs.')
            : 'Quick mode is active. Local use does not require a browser API key.');
    elements.capabilityAuth.textContent = ADMIN_MODE
        ? 'Admin route bypasses browser API keys'
        : (requiresKey ? `Production mode (${auth.api_key_count || 0} key${auth.api_key_count === 1 ? '' : 's'})` : 'Quick mode enabled for local use');
    elements.capabilityInputs.textContent = caps.supports_uploads ? `YouTube + uploads enabled (up to ${caps.max_clips || 10} clips)` : 'YouTube processing enabled';
    elements.capabilityScale.textContent = ADMIN_MODE
        ? `Admin console is using ${caps.env_has_gemini_key || caps.env_has_groq_key ? 'server .env AI keys' : 'server defaults only'}`
        : (caps.recent_jobs_limit ? `Recent jobs keep the last ${caps.recent_jobs_limit} runs recoverable` : 'Recent job recovery available');
    if (caps.supports_trend_discovery) {
        elements.capabilityScale.textContent = `${elements.capabilityScale.textContent} • Trend discovery ready`;
    }
    if (caps.has_youtube_connection) {
        elements.capabilityScale.textContent = `${elements.capabilityScale.textContent} • YouTube publish ready`;
    }
    elements.authModePill.textContent = ADMIN_MODE ? 'Admin' : (requiresKey ? 'API Key' : 'Quick');
    elements.uploadSupportPill.textContent = caps.supports_uploads ? 'Enabled' : 'Unavailable';
    elements.recentJobsPill.textContent = caps.recent_jobs_limit ? `${caps.recent_jobs_limit} Slots` : 'Ready';
    if (Array.isArray(caps.allowed_video_extensions) && caps.allowed_video_extensions.length) {
        elements.uploadSupportCopy.textContent = `Supported formats: ${caps.allowed_video_extensions.join(', ')}`;
    }
}

async function getAuthHeaders(includeContentType = true) {
    const headers = {};
    if (includeContentType) headers['Content-Type'] = 'application/json';
    if (ADMIN_MODE) return headers;
    const auth = state.capabilities || await fetchAuthMode();
    if (auth.requires_api_key) {
        const apiKey = getStoredApiKey();
        if (!apiKey) throw new Error('This server requires an API key. Save one in the Browser API key panel first.');
        headers['X-API-Key'] = apiKey;
    }
    return headers;
}

function showAIMessage(message, type = 'info') {
    elements.aiConfigMessage.textContent = message;
    elements.aiConfigMessage.className = `ai-config-message ${type}`;
    elements.aiConfigMessage.classList.remove('hidden');
    window.setTimeout(() => elements.aiConfigMessage.classList.add('hidden'), 5000);
}

async function loadAIConfig() {
    try {
        const response = await fetch(`${API_BASE_URL}/ai/config`);
        if (!response.ok) return;
        const config = await response.json();
        elements.aiModelSelect.value = config.model || 'gemini-2.5-flash';
        elements.youtubeDefaultPrivacy.value = config.youtube_default_privacy || 'private';
        const statusActive = ADMIN_MODE ? !!config.has_youtube_client_config : !!config.is_active;
        if (ADMIN_MODE) {
            elements.youtubeClientId.value = config.youtube_client_id || ADMIN_PREFILL_YOUTUBE_CLIENT_ID;
            elements.youtubeClientSecret.value = config.youtube_client_secret || ADMIN_PREFILL_YOUTUBE_CLIENT_SECRET;
        }
        const active = !!config.is_active;
        elements.aiBadgeText.textContent = ADMIN_MODE
            ? (config.has_youtube_client_config ? 'YouTube Ready' : 'YouTube Setup')
            : (active ? 'AI Active' : (config.has_api_key ? 'AI Ready' : 'AI Not Configured'));
        elements.aiStatusBadge.classList.toggle('ai-active', statusActive);
        elements.aiStatusBadge.classList.toggle('ai-inactive', !statusActive);
        elements.aiIndicator.classList.toggle('dot-active', statusActive);
        elements.aiIndicator.classList.toggle('dot-inactive', !statusActive);
    } catch {
        if (ADMIN_MODE) {
            elements.youtubeClientId.value = ADMIN_PREFILL_YOUTUBE_CLIENT_ID;
            elements.youtubeClientSecret.value = ADMIN_PREFILL_YOUTUBE_CLIENT_SECRET;
            elements.youtubeDefaultPrivacy.value = elements.youtubeDefaultPrivacy.value || 'private';
        }
        elements.aiBadgeText.textContent = ADMIN_MODE ? 'YouTube Setup' : 'AI Not Configured';
    }
}

async function validateAPIKey() {
    const apiKey = elements.geminiApiKey.value.trim();
    if (!apiKey) {
        showAIMessage('Please enter a Gemini API key first.', 'error');
        return;
    }
    elements.validateKeyBtn.disabled = true;
    try {
        const response = await fetch(`${API_BASE_URL}/ai/validate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_key: apiKey }),
        });
        const result = await response.json();
        showAIMessage(result.message || 'Validation finished.', result.valid ? 'success' : 'error');
    } catch (error) {
        showAIMessage(error.message || 'Validation failed.', 'error');
    } finally {
        elements.validateKeyBtn.disabled = false;
    }
}

async function saveAIConfig() {
    if (ADMIN_MODE) {
        await saveAdminYouTubeConfig();
        return;
    }
    const geminiKey = elements.geminiApiKey.value.trim();
    const groqKey = elements.groqApiKey.value.trim();
    const firecrawlKey = elements.firecrawlApiKey.value.trim();
    const youtubeClientId = elements.youtubeClientId.value.trim();
    const youtubeClientSecret = elements.youtubeClientSecret.value.trim();
    elements.saveAiConfigBtn.disabled = true;
    try {
        const response = await fetch(`${API_BASE_URL}/ai/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                gemini_api_key: geminiKey,
                groq_api_key: groqKey,
                firecrawl_api_key: firecrawlKey,
                youtube_client_id: youtubeClientId,
                youtube_client_secret: youtubeClientSecret,
                youtube_default_privacy: elements.youtubeDefaultPrivacy.value,
                ai_enabled: true,
                model: elements.aiModelSelect.value,
            }),
        });
        if (!response.ok) throw new Error(await parseError(response));
        const result = await response.json();
        showAIMessage(result.message || 'AI settings saved.', 'success');
        elements.geminiApiKey.value = '';
        elements.groqApiKey.value = '';
        elements.firecrawlApiKey.value = '';
        elements.youtubeClientId.value = '';
        elements.youtubeClientSecret.value = '';
        await loadAIConfig();
        await loadYouTubeStatus();
        await fetchCapabilities();
        renderCapabilities();
    } catch (error) {
        showAIMessage(error.message || 'Failed to save AI settings.', 'error');
    } finally {
        elements.saveAiConfigBtn.disabled = false;
    }
}

async function saveAdminYouTubeConfig() {
    const youtubeClientId = elements.youtubeClientId.value.trim();
    const youtubeClientSecret = elements.youtubeClientSecret.value.trim();
    elements.saveAiConfigBtn.disabled = true;
    try {
        const response = await fetch(`${API_BASE_URL}/youtube/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                youtube_client_id: youtubeClientId,
                youtube_client_secret: youtubeClientSecret,
                youtube_default_privacy: elements.youtubeDefaultPrivacy.value,
            }),
        });
        if (!response.ok) throw new Error(await parseError(response));
        const result = await response.json();
        showAIMessage(result.message || 'YouTube settings saved.', 'success');
        await loadAIConfig();
        await loadYouTubeStatus();
        await fetchCapabilities();
        renderCapabilities();
    } catch (error) {
        showAIMessage(error.message || 'Failed to save YouTube settings.', 'error');
    } finally {
        elements.saveAiConfigBtn.disabled = false;
    }
}

function renderRecentJobs() {
    elements.recentJobsList.innerHTML = '';
    elements.recentJobsEmpty.classList.toggle('hidden', state.recentJobs.length > 0);
    state.recentJobs.forEach((job) => {
        const card = document.createElement('article');
        card.className = 'recent-job-card';
        if (job.job_id === state.currentJobId) card.classList.add('active-job');
        const stage = job.stage || job.status || 'unknown';
        const label = truncate(job.video_title || job.input_name || job.job_id);
        const meta = [
            job.source_type === 'upload' ? 'Upload' : 'YouTube',
            (job.results || []).length ? `${job.results.length} clip${job.results.length === 1 ? '' : 's'}` : `${job.num_clips || 0} requested`,
            formatDuration(job.video_duration),
            relativeTime(job.updated_at),
        ].filter(Boolean).join(' • ');
        const action = stage === 'complete' ? 'Open' : stage === 'error' ? 'Inspect' : 'Resume';
        card.innerHTML = `
            <div class="recent-job-main">
                <div class="recent-job-topline">
                    <span class="recent-job-stage stage-${escapeHtml(stage)}">${escapeHtml(formatStage(stage))}</span>
                    <span class="recent-job-time">${escapeHtml(meta)}</span>
                </div>
                <h4>${escapeHtml(label)}</h4>
                <p>${escapeHtml(job.message || '')}</p>
            </div>
            <div class="recent-job-actions">
                <button type="button" class="ghost-btn compact-btn" data-job-id="${escapeHtml(job.job_id)}">${escapeHtml(action)}</button>
            </div>
        `;
        elements.recentJobsList.appendChild(card);
    });
}

async function fetchRecentJobs() {
    try {
        const headers = await getAuthHeaders(false);
        const response = await fetch(`${API_BASE_URL}/jobs/recent`, { headers });
        if (!response.ok) {
            if (!ADMIN_MODE && (response.status === 401 || response.status === 403) && state.capabilities && state.capabilities.requires_api_key) {
                elements.authDescription.textContent = response.status === 403
                    ? 'The saved browser API key was rejected. Replace it with a valid key.'
                    : 'Save a valid API key in this browser before starting or reopening protected jobs.';
            }
            state.recentJobs = [];
            renderRecentJobs();
            return;
        }
        const payload = await response.json();
        state.recentJobs = payload.jobs || [];
        if (!ADMIN_MODE && state.capabilities && state.capabilities.requires_api_key) {
            elements.authDescription.textContent = 'A browser API key is saved and will be sent automatically.';
        }
    } catch {
        state.recentJobs = [];
    }
    renderRecentJobs();
}

async function startProcessing(url, numClips) {
    const response = await fetch(`${API_BASE_URL}/process`, {
        method: 'POST',
        headers: await getAuthHeaders(true),
        body: JSON.stringify({ url, num_clips: numClips }),
    });
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
}

async function startUpload(file, numClips) {
    const form = new FormData();
    form.append('file', file);
    form.append('num_clips', String(numClips));
    const response = await fetch(`${API_BASE_URL}/process/upload`, {
        method: 'POST',
        headers: await getAuthHeaders(false),
        body: form,
    });
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
}

async function getStatus(jobId) {
    const response = await fetch(`${API_BASE_URL}/status/${jobId}`, {
        headers: await getAuthHeaders(false),
    });
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
}

async function getResult(jobId) {
    const response = await fetch(`${API_BASE_URL}/result/${jobId}`, {
        headers: await getAuthHeaders(false),
    });
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
}

async function discoverTrendVideos(topic, location) {
    const response = await fetch(`${API_BASE_URL}/trends/discover`, {
        method: 'POST',
        headers: await getAuthHeaders(true),
        body: JSON.stringify({ topic, location, limit: 6 }),
    });
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
}

async function autoProcessTrendVideo(topic, location, numClips) {
    const response = await fetch(`${API_BASE_URL}/trends/auto-process`, {
        method: 'POST',
        headers: await getAuthHeaders(true),
        body: JSON.stringify({ topic, location, limit: 6, num_clips: numClips }),
    });
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
}

async function fetchYouTubeStatus() {
    const response = await fetch(`${API_BASE_URL}/youtube/status`);
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
}

async function startYouTubeAuthFlow() {
    const response = await fetch(`${API_BASE_URL}/youtube/auth/start`, {
        method: 'POST',
        headers: await getAuthHeaders(false),
    });
    if (!response.ok) throw new Error(await parseError(response));
    const payload = await response.json();
    return {
        ...payload,
        auth_url: normalizeAdminYouTubeAuthUrl(payload.auth_url || ''),
        redirect_uri: normalizeAdminYouTubeRedirectUri(payload.redirect_uri || ''),
    };
}

async function disconnectYouTubeAccount() {
    const response = await fetch(`${API_BASE_URL}/youtube/connection`, {
        method: 'DELETE',
        headers: await getAuthHeaders(false),
    });
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
}

async function uploadShortToYouTube(payload) {
    const response = await fetch(`${API_BASE_URL}/youtube/upload`, {
        method: 'POST',
        headers: await getAuthHeaders(true),
        body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
}

async function uploadShortBundleToYouTube(payload) {
    const response = await fetch(`${API_BASE_URL}/youtube/upload/batch`, {
        method: 'POST',
        headers: await getAuthHeaders(true),
        body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(await parseError(response));
    return response.json();
}

async function loadYouTubeStatus() {
    try {
        const rawStatus = await fetchYouTubeStatus();
        const status = {
            ...rawStatus,
            expected_redirect_uri: normalizeAdminYouTubeRedirectUri(rawStatus.expected_redirect_uri || ''),
        };
        state.youtubeStatus = {
            hasClientConfig: !!status.has_client_config,
            connected: !!status.connected,
            defaultPrivacyStatus: status.default_privacy_status || 'private',
            authorizedAt: status.authorized_at || null,
            expectedRedirectUri: status.expected_redirect_uri || '',
        };
        setStoredYouTubeStatus(state.youtubeStatus);
        if (elements.youtubeRedirectHint) {
            elements.youtubeRedirectHint.innerHTML = status.expected_redirect_uri
                ? `Authorized Google redirect URI: <code>${status.expected_redirect_uri}</code>`
                : 'Authorize the Google OAuth redirect URI for this server in your Google Cloud credentials.';
        }
        elements.youtubeDefaultPrivacy.value = state.youtubeStatus.defaultPrivacyStatus;
        const redirectHint = state.youtubeStatus.expectedRedirectUri
            ? ` Authorized redirect URI: ${state.youtubeStatus.expectedRedirectUri}`
            : '';
        elements.youtubeConnectStatus.textContent = status.connected
            ? `YouTube connected. Default uploads: ${state.youtubeStatus.defaultPrivacyStatus}.${redirectHint}`
            : (status.has_client_config
                ? `OAuth client is saved on the server. Click Connect YouTube to finish authorization.${redirectHint}`
                : `Save a YouTube OAuth client ID and secret, then connect.${redirectHint}`);
        elements.disconnectYouTubeBtn.disabled = !status.connected;
    } catch (error) {
        state.youtubeStatus = {
            hasClientConfig: false,
            connected: false,
            defaultPrivacyStatus: elements.youtubeDefaultPrivacy.value || 'private',
        };
        const storedStatus = getStoredYouTubeStatus();
        if (storedStatus?.connected) {
            state.youtubeStatus = {
                hasClientConfig: !!storedStatus.hasClientConfig,
                connected: true,
                defaultPrivacyStatus: storedStatus.defaultPrivacyStatus || elements.youtubeDefaultPrivacy.value || 'private',
                authorizedAt: storedStatus.authorizedAt || null,
                expectedRedirectUri: storedStatus.expectedRedirectUri || '',
            };
            elements.youtubeDefaultPrivacy.value = state.youtubeStatus.defaultPrivacyStatus;
            elements.youtubeConnectStatus.textContent = 'Using saved YouTube connection from this browser while live status refresh retries.';
            elements.disconnectYouTubeBtn.disabled = false;
        } else {
            elements.youtubeConnectStatus.textContent = error.message || 'Unable to load YouTube status.';
            elements.disconnectYouTubeBtn.disabled = true;
        }
    }
}

function buildUploadTitle(highlight, fallbackTitle) {
    const base = String(highlight.title || fallbackTitle || 'Short clip').trim();
    if (base.toLowerCase().includes('#shorts')) {
        return base.length > 100 ? `${base.slice(0, 97)}...` : base;
    }
    const suffix = '#Shorts';
    const maxBaseLength = 100 - (suffix.length + 1);
    const trimmed = base.length > maxBaseLength ? `${base.slice(0, Math.max(0, maxBaseLength - 3)).trim()}...` : base;
    return `${trimmed} ${suffix}`.trim();
}

function buildUploadDescription(highlight) {
    const parts = [];
    if (highlight.trendy_caption) parts.push(highlight.trendy_caption.trim());
    if (highlight.hook_caption && highlight.hook_caption !== highlight.trendy_caption) {
        parts.push(highlight.hook_caption.trim());
    }
    if (Array.isArray(highlight.hashtags) && highlight.hashtags.length) {
        parts.push(highlight.hashtags.join(' '));
    }
    const description = parts.filter(Boolean).join('\n\n').trim();
    return description || '#Shorts';
}

function buildShortUploadPayload(entry, index, highlight) {
    const tags = Array.isArray(highlight.hashtags) ? highlight.hashtags : [];
    return {
        filename: entry.filename,
        title: buildUploadTitle(highlight, `Short ${index + 1}`),
        description: buildUploadDescription(highlight),
        tags,
        privacy_status: state.youtubeStatus.defaultPrivacyStatus || 'private',
    };
}

function updateSingleShortUploadUI(filename, payload) {
    const card = elements.shortsGrid.querySelector(`.short-card[data-filename="${CSS.escape(filename)}"]`);
    if (!card) return;
    const status = card.querySelector('.short-upload-status');
    const linkRow = card.querySelector('.youtube-link-row');
    if (!status || !linkRow) return;

    if (payload.success) {
        status.textContent = `Uploaded as ${payload.privacy_status}.`;
        status.dataset.state = 'success';
        linkRow.classList.remove('hidden');
        linkRow.innerHTML = `
            <a href="${escapeHtml(payload.url)}" target="_blank" rel="noopener" class="youtube-link">Watch on YouTube</a>
            <a href="${escapeHtml(payload.studio_url)}" target="_blank" rel="noopener" class="youtube-link">Open in Studio</a>
        `;
    } else {
        status.textContent = payload.error || 'YouTube upload failed.';
        status.dataset.state = 'error';
        linkRow.classList.add('hidden');
        linkRow.innerHTML = '';
    }
}

function renderBatchUploadLinks(uploads) {
    const successfulUploads = (uploads || []).filter((item) => item.success);
    if (!successfulUploads.length) {
        elements.uploadAllYouTubeLinks.classList.add('hidden');
        elements.uploadAllYouTubeLinks.innerHTML = '';
        return;
    }

    elements.uploadAllYouTubeLinks.classList.remove('hidden');
    elements.uploadAllYouTubeLinks.innerHTML = successfulUploads.map((item, index) => `
        <a href="${escapeHtml(item.studio_url)}" target="_blank" rel="noopener" class="youtube-link">Short ${index + 1} in Studio</a>
    `).join('');
}

async function handleUploadAllShorts() {
    if (!state.lastShortEntries.length) {
        showAIMessage('Generate shorts first.', 'error');
        return;
    }
    if (!state.youtubeStatus.hasClientConfig) {
        showAIMessage('Save a YouTube OAuth client first.', 'error');
        return;
    }
    if (!state.youtubeStatus.connected) {
        showAIMessage('Connect a YouTube account before uploading.', 'error');
        return;
    }

    const uploads = state.lastShortEntries.map((entry, index) => buildShortUploadPayload(entry, index, state.lastResults[index] || {}));
    elements.uploadAllYouTubeBtn.disabled = true;
    elements.uploadAllYouTubeStatus.classList.remove('hidden');
    elements.uploadAllYouTubeStatus.dataset.state = 'idle';
    elements.uploadAllYouTubeStatus.textContent = `Uploading ${uploads.length} short${uploads.length === 1 ? '' : 's'} to YouTube...`;
    elements.uploadAllYouTubeLinks.classList.add('hidden');
    elements.uploadAllYouTubeLinks.innerHTML = '';

    try {
        const payload = await uploadShortBundleToYouTube({ uploads });
        (payload.uploads || []).forEach((item) => updateSingleShortUploadUI(item.filename, item));
        renderBatchUploadLinks(payload.uploads || []);
        if (payload.failed_count) {
            elements.uploadAllYouTubeStatus.dataset.state = 'error';
            elements.uploadAllYouTubeStatus.textContent = `Uploaded ${payload.uploaded_count}/${uploads.length} shorts. ${payload.failed_count} failed.`;
        } else {
            elements.uploadAllYouTubeStatus.dataset.state = 'success';
            elements.uploadAllYouTubeStatus.textContent = `Uploaded all ${payload.uploaded_count} shorts to YouTube.`;
        }
    } catch (error) {
        elements.uploadAllYouTubeStatus.dataset.state = 'error';
        elements.uploadAllYouTubeStatus.textContent = error.message || 'YouTube bundle upload failed.';
    } finally {
        elements.uploadAllYouTubeBtn.disabled = false;
    }
}

async function hydrateProtectedVideoPreview(videoElement, shortUrl) {
    if (ADMIN_MODE || !state.capabilities?.requires_api_key) return;
    try {
        const response = await fetch(shortUrl, {
            headers: await getAuthHeaders(false),
        });
        if (!response.ok) throw new Error(await parseError(response));
        const blob = await response.blob();
        const blobUrl = URL.createObjectURL(blob);
        state.previewUrls.push(blobUrl);
        videoElement.src = blobUrl;
    } catch {
        videoElement.removeAttribute('src');
    }
}

function stopPolling() {
    if (state.pollInterval) window.clearInterval(state.pollInterval);
    state.pollInterval = null;
}

function startPolling(jobId) {
    stopPolling();
    state.currentJobId = jobId;
    state.pollErrorCount = 0;
    pollStatus();
    state.pollInterval = window.setInterval(pollStatus, POLL_INTERVAL);
}

async function pollStatus() {
    if (!state.currentJobId) return;
    try {
        const status = await getStatus(state.currentJobId);
        state.pollErrorCount = 0;
        updateProgress(status.stage, status.progress, status.message);
        if (status.stage === 'complete') {
            clearStoredActiveJob();
            stopPolling();
            await showResults(state.currentJobId, status.results, status.ai_highlights, status);
            await fetchRecentJobs();
        } else if (status.stage === 'error' || status.error) {
            clearStoredActiveJob();
            stopPolling();
            await fetchRecentJobs();
            showError(status.error || status.message || 'Processing failed.');
        }
    } catch (error) {
        state.pollErrorCount += 1;
        if (state.pollErrorCount >= MAX_POLL_ERRORS) showError(`Connection lost: ${error.message}`);
    }
}

function buildCaptionPack(highlights) {
    return (highlights || []).map((highlight, index) => {
        const parts = [`Short ${index + 1}: ${highlight.title || `Short #${index + 1}`}`];
        if (highlight.trendy_caption) parts.push(`Caption: ${highlight.trendy_caption}`);
        if (highlight.hook_caption && highlight.hook_caption !== highlight.trendy_caption) parts.push(`Hook: ${highlight.hook_caption}`);
        if (Array.isArray(highlight.hashtags) && highlight.hashtags.length) parts.push(`Hashtags: ${highlight.hashtags.join(' ')}`);
        return parts.join('\n');
    }).join('\n\n');
}

async function downloadShort(filename, shortUrl = null) {
    try {
        const response = await fetch(shortUrl || `${API_BASE_URL}/shorts/${encodeURIComponent(filename)}`, {
            headers: await getAuthHeaders(false),
        });
        if (!response.ok) throw new Error(await parseError(response));
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(url);
    } catch (error) {
        showError(error.message || 'Download failed.');
    }
}

function createShortCard(entry, index, highlight) {
    const filename = entry.filename;
    const shortUrl = entry.url || `${API_BASE_URL}/shorts/${encodeURIComponent(filename)}`;
    const directPreviewSrc = (ADMIN_MODE || !state.capabilities?.requires_api_key) ? escapeHtml(shortUrl) : '';
    const score = Number(highlight.virality_score || 0);
    const duration = Math.max(0, Number(highlight.end || 0) - Number(highlight.start || 0));
    const tags = Array.isArray(highlight.hashtags) ? highlight.hashtags : [];
    const card = document.createElement('article');
    card.className = 'short-card';
    card.dataset.filename = filename;
    card.innerHTML = `
        <div class="short-thumbnail">
            <video class="short-preview" ${directPreviewSrc ? `src="${directPreviewSrc}"` : ''} controls preload="metadata" playsinline></video>
        </div>
        <div class="short-info">
            <div class="short-headline-row">
                <div class="short-title">${escapeHtml(highlight.title || `Short #${index}`)}</div>
                ${score > 0 ? `<span class="virality-tag" style="color:${getViralityColor(score)}; border-color:${getViralityColor(score)}30;">${escapeHtml(getViralityLabel(score))} ${escapeHtml(String(score))}/10</span>` : ''}
            </div>
            ${highlight.trendy_caption ? `<div class="short-caption">${escapeHtml(highlight.trendy_caption)}</div>` : ''}
            ${highlight.hook_caption ? `<div class="short-hook">${escapeHtml(highlight.hook_caption)}</div>` : ''}
            <div class="short-meta">
                <span>${escapeHtml(formatReason(highlight.reason || 'highlight'))}</span>
                ${duration ? `<span>${escapeHtml(formatDuration(duration))}</span>` : ''}
                <span>9:16</span>
            </div>
            ${tags.length ? `<div class="hashtag-row">${tags.map((tag) => `<span class="hashtag-chip">${escapeHtml(tag)}</span>`).join('')}</div>` : ''}
            <div class="short-actions-row">
                <button type="button" class="download-btn">Download</button>
                <button type="button" class="secondary-btn compact-btn upload-youtube-btn">Upload to YouTube</button>
                <button type="button" class="ghost-btn compact-btn copy-caption-btn">Copy Caption</button>
                <button type="button" class="ghost-btn compact-btn copy-link-btn">Copy Link</button>
            </div>
            <div class="short-upload-status" data-state="idle"></div>
            <div class="youtube-link-row hidden"></div>
        </div>
    `;
    const previewElement = card.querySelector('.short-preview');
    hydrateProtectedVideoPreview(previewElement, shortUrl);
    card.querySelector('.download-btn').addEventListener('click', () => downloadShort(filename, shortUrl));
    card.querySelector('.copy-caption-btn').addEventListener('click', (event) => copyText(buildCaptionPack([highlight]) || shortUrl, event.currentTarget));
    card.querySelector('.copy-link-btn').addEventListener('click', (event) => copyText(shortUrl, event.currentTarget));
    card.querySelector('.upload-youtube-btn').addEventListener('click', async (event) => {
        const button = event.currentTarget;
        const status = card.querySelector('.short-upload-status');
        const linkRow = card.querySelector('.youtube-link-row');
        if (!state.youtubeStatus.hasClientConfig) {
            status.textContent = 'Save a YouTube OAuth client first.';
            status.dataset.state = 'error';
            return;
        }
        if (!state.youtubeStatus.connected) {
            status.textContent = 'Connect a YouTube account before uploading.';
            status.dataset.state = 'error';
            return;
        }

        button.disabled = true;
        status.textContent = 'Uploading to YouTube...';
        status.dataset.state = 'idle';
        linkRow.classList.add('hidden');
        try {
            const payload = await uploadShortToYouTube(buildShortUploadPayload(entry, index - 1, highlight));
            updateSingleShortUploadUI(filename, { success: true, ...payload });
        } catch (error) {
            status.textContent = error.message || 'YouTube upload failed.';
            status.dataset.state = 'error';
        } finally {
            button.disabled = false;
        }
    });
    return card;
}

async function showResults(jobId, results, aiHighlights, payload = null) {
    let activePayload = payload;
    let shorts = results || [];
    let highlights = aiHighlights || [];
    if (!shorts.length) {
        activePayload = await getResult(jobId);
        shorts = activePayload.results || activePayload.shorts || [];
        highlights = activePayload.ai_highlights || [];
    }
    if (!shorts.length) {
        showError('No shorts were generated. Try a different source video.');
        return;
    }
    const shortUrls = activePayload?.short_urls || [];
    const shortEntries = shorts.map((item, index) => ({
        filename: typeof item === 'string' ? item : String(item?.filename || item?.name || `short_${index + 1}.mp4`),
        url: shortUrls[index] || null,
    }));
    state.lastResults = highlights;
    state.lastShortEntries = shortEntries;
    elements.videoTitle.textContent = activePayload?.video_title || 'Processing complete';
    elements.resultsSummary.textContent = [
        activePayload?.source_type === 'upload' ? 'Uploaded file' : 'YouTube source',
        `${shortEntries.length} clip${shortEntries.length === 1 ? '' : 's'}`,
        formatDuration(activePayload?.video_duration),
    ].filter(Boolean).join(' • ');
    elements.copyAllCaptionsBtn.classList.toggle('hidden', !highlights.length);
    elements.copyAllCaptionsBtn.onclick = (event) => copyText(buildCaptionPack(highlights), event.currentTarget);
    elements.uploadAllYouTubeStatus.classList.add('hidden');
    elements.uploadAllYouTubeStatus.dataset.state = 'idle';
    elements.uploadAllYouTubeStatus.textContent = '';
    elements.uploadAllYouTubeLinks.classList.add('hidden');
    elements.uploadAllYouTubeLinks.innerHTML = '';
    clearPreviewUrls();
    elements.shortsGrid.innerHTML = '';
    shortEntries.forEach((entry, index) => elements.shortsGrid.appendChild(createShortCard(entry, index + 1, highlights[index] || {})));
    showSection('results');
    setLoading(false);
}

async function handleGenerate() {
    const numClips = parseInt(elements.numClipsSelect.value, 10);
    try {
        setLoading(true, state.sourceMode === 'upload' ? 'Uploading and Processing...' : 'Processing...');
        showSection('status');
        updateProgress('queued', 0, 'Starting process...');
        let response;
        let label;
        if (state.sourceMode === 'upload') {
            const file = elements.fileInput.files && elements.fileInput.files[0];
            if (!file) throw new Error('Select a video file to upload.');
            response = await startUpload(file, numClips);
            label = file.name;
        } else {
            const url = elements.urlInput.value.trim();
            if (!url) throw new Error('Please enter a YouTube URL.');
            if (!isValidYouTubeUrl(url)) throw new Error('Please enter a valid YouTube URL.');
            response = await startProcessing(url, numClips);
            label = url;
        }
        if (!response.job_id) throw new Error('The server did not return a job ID.');
        setStoredActiveJob({ jobId: response.job_id, label, sourceMode: state.sourceMode, startedAt: new Date().toISOString() });
        startPolling(response.job_id);
        await fetchRecentJobs();
    } catch (error) {
        showError(error.message || 'Failed to start processing.');
    }
}

function renderTrendResults() {
    elements.trendResultsList.innerHTML = '';
    elements.trendResultsEmpty.classList.toggle('hidden', state.trendCandidates.length > 0);
    state.trendCandidates.forEach((candidate) => {
        const card = document.createElement('article');
        card.className = 'trend-card';
        const description = truncate(candidate.description || 'No description available', 180);
        card.innerHTML = `
            <div class="trend-card-copy">
                <div class="trend-card-topline">
                    <span class="trend-score">Score ${escapeHtml(String(candidate.score || 0))}</span>
                    <span class="trend-reason">${escapeHtml(candidate.reason || 'trend rank')}</span>
                </div>
                <h4>${escapeHtml(candidate.title || 'Trend candidate')}</h4>
                <p>${escapeHtml(description)}</p>
                <a href="${escapeHtml(candidate.url)}" target="_blank" rel="noopener" class="trend-link">${escapeHtml(candidate.url)}</a>
            </div>
            <div class="trend-card-actions">
                <button type="button" class="secondary-btn compact-btn" data-trend-action="generate" data-trend-url="${escapeHtml(candidate.url)}" data-trend-title="${escapeHtml(candidate.title || '')}">Generate Shorts</button>
                <button type="button" class="ghost-btn compact-btn" data-trend-action="use" data-trend-url="${escapeHtml(candidate.url)}">Use URL</button>
            </div>
        `;
        elements.trendResultsList.appendChild(card);
    });
}

async function handleTrendDiscover() {
    const topic = elements.trendTopic.value.trim();
    const location = elements.trendLocation.value.trim() || 'India';
    if (!topic) {
        setTrendStatus('Enter a topic first.', 'error');
        return;
    }

    elements.discoverTrendsBtn.disabled = true;
    setTrendStatus('Searching Firecrawl for current YouTube candidates...', 'loading');

    try {
        const payload = await discoverTrendVideos(topic, location);
        state.trendCandidates = payload.candidates || [];
        renderTrendResults();
        setTrendStatus(
            state.trendCandidates.length
                ? `Found ${state.trendCandidates.length} ranked YouTube candidates for "${topic}".`
                : `No candidates found for "${topic}". Try a broader search.`,
            state.trendCandidates.length ? 'success' : 'error',
        );
    } catch (error) {
        state.trendCandidates = [];
        renderTrendResults();
        setTrendStatus(error.message || 'Trend discovery failed.', 'error');
    } finally {
        elements.discoverTrendsBtn.disabled = false;
    }
}

async function startTrendJob(url, title) {
    const numClips = parseInt(elements.numClipsSelect.value, 10);
    try {
        setLoading(true, 'Processing trend pick...');
        showSection('status');
        updateProgress('queued', 0, `Queueing ${title || 'trend video'}...`);
        const response = await startProcessing(url, numClips);
        setStoredActiveJob({ jobId: response.job_id, label: title || url, sourceMode: 'youtube', startedAt: new Date().toISOString() });
        startPolling(response.job_id);
        await fetchRecentJobs();
    } catch (error) {
        showError(error.message || 'Failed to process trend video.');
    }
}

async function handleTrendAutoProcess() {
    const topic = elements.trendTopic.value.trim();
    const location = elements.trendLocation.value.trim() || 'India';
    const numClips = parseInt(elements.numClipsSelect.value, 10);
    if (!topic) {
        setTrendStatus('Enter a topic first.', 'error');
        return;
    }

    elements.autoTrendBtn.disabled = true;
    setTrendStatus('Picking the strongest candidate and starting a job...', 'loading');

    try {
        const payload = await autoProcessTrendVideo(topic, location, numClips);
        const candidate = payload.candidate || {};
        setStoredActiveJob({ jobId: payload.job_id, label: candidate.title || topic, sourceMode: 'youtube', startedAt: new Date().toISOString() });
        setLoading(true, 'Processing trend pick...');
        showSection('status');
        updateProgress('queued', 0, `Picked ${candidate.title || candidate.url || topic}`);
        startPolling(payload.job_id);
        await fetchRecentJobs();
        setTrendStatus(`Auto-picked: ${candidate.title || candidate.url || topic}`, 'success');
    } catch (error) {
        setTrendStatus(error.message || 'Auto trend processing failed.', 'error');
    } finally {
        elements.autoTrendBtn.disabled = false;
    }
}

function handleRetry() {
    stopPolling();
    state.currentJobId = null;
    showSection(null);
    setLoading(false);
}

function handleNewVideo() {
    stopPolling();
    state.currentJobId = null;
    clearStoredActiveJob();
    clearPreviewUrls();
    elements.urlInput.value = '';
    elements.fileInput.value = '';
    updateUploadMeta();
    showSection(null);
    setLoading(false);
    setSourceMode('youtube');
    elements.urlInput.focus();
}

function saveBrowserApiKey() {
    const value = elements.browserApiKey.value.trim();
    if (!value) {
        flashButton(elements.saveBrowserKeyBtn, 'Missing key');
        return;
    }
    setStoredApiKey(value);
    renderCapabilities();
    fetchRecentJobs();
    flashButton(elements.saveBrowserKeyBtn, 'Saved');
}

function clearBrowserApiKey() {
    setStoredApiKey('');
    elements.browserApiKey.value = '';
    renderCapabilities();
    state.recentJobs = [];
    renderRecentJobs();
    flashButton(elements.clearBrowserKeyBtn, 'Cleared');
}

async function handleConnectYouTube() {
    if (!state.youtubeStatus.hasClientConfig) {
        showAIMessage('Save a YouTube OAuth client ID and client secret first.', 'error');
        return;
    }
    try {
        const payload = await startYouTubeAuthFlow();
        window.open(payload.auth_url, 'shortmaker-youtube-auth', 'width=720,height=820');
        elements.youtubeConnectStatus.textContent = 'Complete the Google consent screen to finish connecting YouTube.';
    } catch (error) {
        showAIMessage(error.message || 'Failed to start YouTube connect flow.', 'error');
    }
}

async function handleDisconnectYouTube() {
    try {
        await disconnectYouTubeAccount();
        clearStoredYouTubeStatus();
        await loadYouTubeStatus();
        showAIMessage('Disconnected YouTube account.', 'success');
    } catch (error) {
        showAIMessage(error.message || 'Failed to disconnect YouTube account.', 'error');
    }
}

function handleYouTubeAuthMessage(event) {
    if (event.origin !== window.location.origin) return;
    const payload = event.data || {};
    if (payload.type !== 'shortmaker-youtube-auth') return;
    if (payload.success) {
        setStoredYouTubeStatus({
            hasClientConfig: true,
            connected: true,
            defaultPrivacyStatus: elements.youtubeDefaultPrivacy.value || 'private',
            expectedRedirectUri: elements.youtubeRedirectHint?.textContent || '',
            authorizedAt: new Date().toISOString(),
        });
    }
    showAIMessage(
        payload.message || (payload.success ? 'YouTube connected.' : 'YouTube connection failed.'),
        payload.success ? 'success' : 'error',
    );
    loadYouTubeStatus();
}

async function handleRecentJob(jobId) {
    const job = state.recentJobs.find((item) => item.job_id === jobId);
    if (!job) return;
    state.currentJobId = jobId;
    if (job.stage === 'complete') {
        await showResults(jobId, job.results, job.ai_highlights, job);
        return;
    }
    if (job.stage === 'error') {
        showError(job.error || job.message || 'This job ended with an error.');
        return;
    }
    setStoredActiveJob({ jobId, label: job.video_title || job.input_name || jobId, sourceMode: job.source_type || 'youtube', startedAt: job.created_at || new Date().toISOString() });
    setLoading(true, 'Resuming...');
    showSection('status');
    updateProgress(job.stage, job.progress, job.message);
    startPolling(jobId);
}

async function resumeStoredJob() {
    const activeJob = getStoredActiveJob();
    if (!activeJob || !activeJob.jobId) return;
    try {
        const status = await getStatus(activeJob.jobId);
        if (status.stage === 'complete') {
            clearStoredActiveJob();
            await showResults(activeJob.jobId, status.results, status.ai_highlights, status);
            return;
        }
        if (status.stage === 'error') {
            clearStoredActiveJob();
            showError(status.error || status.message || 'The last job failed.');
            return;
        }
        setLoading(true, 'Resuming...');
        showSection('status');
        updateProgress(status.stage, status.progress, status.message);
        startPolling(activeJob.jobId);
    } catch {
        clearStoredActiveJob();
    }
}

function bindUploadInteractions() {
    elements.fileInput.addEventListener('change', updateUploadMeta);
    ['dragenter', 'dragover'].forEach((name) => elements.uploadDropzone.addEventListener(name, (event) => {
        event.preventDefault();
        elements.uploadDropzone.classList.add('dragging');
    }));
    ['dragleave', 'dragend', 'drop'].forEach((name) => elements.uploadDropzone.addEventListener(name, (event) => {
        event.preventDefault();
        elements.uploadDropzone.classList.remove('dragging');
    }));
    elements.uploadDropzone.addEventListener('drop', (event) => {
        const files = event.dataTransfer && event.dataTransfer.files;
        if (!files || !files.length) return;
        elements.fileInput.files = files;
        updateUploadMeta();
    });
}

async function init() {
    configureAdminExperience();
    const storedYouTubeStatus = getStoredYouTubeStatus();
    if (storedYouTubeStatus?.connected) {
        state.youtubeStatus = {
            hasClientConfig: !!storedYouTubeStatus.hasClientConfig,
            connected: true,
            defaultPrivacyStatus: storedYouTubeStatus.defaultPrivacyStatus || 'private',
            authorizedAt: storedYouTubeStatus.authorizedAt || null,
            expectedRedirectUri: storedYouTubeStatus.expectedRedirectUri || '',
        };
        elements.youtubeDefaultPrivacy.value = state.youtubeStatus.defaultPrivacyStatus;
        elements.youtubeConnectStatus.textContent = 'Restored saved YouTube connection.';
        elements.disconnectYouTubeBtn.disabled = false;
    }
    window.addEventListener('message', handleYouTubeAuthMessage);
    elements.generateBtn.addEventListener('click', handleGenerate);
    elements.retryBtn.addEventListener('click', handleRetry);
    elements.newVideoBtn.addEventListener('click', handleNewVideo);
    elements.refreshJobsBtn.addEventListener('click', fetchRecentJobs);
    elements.modeYoutubeBtn.addEventListener('click', () => setSourceMode('youtube'));
    elements.modeUploadBtn.addEventListener('click', () => setSourceMode('upload'));
    elements.urlInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') handleGenerate();
    });
    elements.aiSettingsToggle.addEventListener('click', () => {
        state.aiConfigVisible = !state.aiConfigVisible;
        elements.aiConfigSection.classList.toggle('hidden', !state.aiConfigVisible);
        elements.aiSettingsToggle.classList.toggle('active', state.aiConfigVisible);
    });
    elements.validateKeyBtn.addEventListener('click', validateAPIKey);
    elements.saveAiConfigBtn.addEventListener('click', saveAIConfig);
    elements.toggleKeyVisibility.addEventListener('click', () => toggleFieldVisibility(elements.geminiApiKey, elements.toggleKeyVisibility));
    elements.toggleGroqKeyVisibility.addEventListener('click', () => toggleFieldVisibility(elements.groqApiKey, elements.toggleGroqKeyVisibility));
    elements.toggleFirecrawlKeyVisibility.addEventListener('click', () => toggleFieldVisibility(elements.firecrawlApiKey, elements.toggleFirecrawlKeyVisibility));
    elements.toggleYouTubeClientIdVisibility.addEventListener('click', () => toggleFieldVisibility(elements.youtubeClientId, elements.toggleYouTubeClientIdVisibility));
    elements.toggleYouTubeClientSecretVisibility.addEventListener('click', () => toggleFieldVisibility(elements.youtubeClientSecret, elements.toggleYouTubeClientSecretVisibility));
    elements.toggleBrowserKeyVisibility.addEventListener('click', () => toggleFieldVisibility(elements.browserApiKey, elements.toggleBrowserKeyVisibility));
    elements.saveBrowserKeyBtn.addEventListener('click', saveBrowserApiKey);
    elements.clearBrowserKeyBtn.addEventListener('click', clearBrowserApiKey);
    elements.connectYouTubeBtn.addEventListener('click', handleConnectYouTube);
    elements.disconnectYouTubeBtn.addEventListener('click', handleDisconnectYouTube);
    elements.uploadAllYouTubeBtn.addEventListener('click', handleUploadAllShorts);
    elements.discoverTrendsBtn.addEventListener('click', handleTrendDiscover);
    elements.autoTrendBtn.addEventListener('click', handleTrendAutoProcess);
    elements.trendTopic.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') handleTrendDiscover();
    });
    elements.trendResultsList.addEventListener('click', (event) => {
        const button = event.target.closest('[data-trend-action]');
        if (!button) return;
        const url = button.dataset.trendUrl;
        if (!url) return;
        if (button.dataset.trendAction === 'use') {
            setSourceMode('youtube');
            elements.urlInput.value = url;
            setTrendStatus('Trend URL copied into the YouTube input.', 'success');
            return;
        }
        startTrendJob(url, button.dataset.trendTitle || url);
    });
    elements.recentJobsList.addEventListener('click', (event) => {
        const button = event.target.closest('[data-job-id]');
        if (button) handleRecentJob(button.dataset.jobId);
    });
    bindUploadInteractions();
    setSourceMode('youtube');
    updateUploadMeta();
    await Promise.all([fetchAuthMode(), fetchCapabilities()]);
    renderCapabilities();
    await loadAIConfig();
    await loadYouTubeStatus();
    renderTrendResults();
    await fetchRecentJobs();
    await resumeStoredJob();
    if (ADMIN_MODE) {
        elements.connectYouTubeBtn.focus();
    } else if (!state.currentJobId) {
        elements.urlInput.focus();
    }
}

document.addEventListener('DOMContentLoaded', init);
