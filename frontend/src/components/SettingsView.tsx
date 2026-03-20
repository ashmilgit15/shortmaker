import React, { useEffect, useState } from 'react';
import { AdminConfig, SessionData, YouTubeStatus } from '../types';
import styles from './SettingsView.module.css';

interface SettingsViewProps {
  config: AdminConfig | null;
  youtubeStatus: YouTubeStatus | null;
  session: SessionData | null;
  isAdmin: boolean;
  adminConfigError?: string | null;
  onRetryAdminConfig?: () => Promise<void>;
  onSaveAIConfig: (payload: object) => Promise<void>;
  onSaveYouTubeConfig: (payload: object) => Promise<void>;
  onConnectYouTube: () => Promise<void>;
  onDisconnectYouTube: () => Promise<void>;
  saving: boolean;
  youtubeSaving: boolean;
}

const DEFAULT_PRIVACY = 'private';

export default function SettingsView({
  config,
  youtubeStatus,
  session,
  isAdmin,
  adminConfigError,
  onRetryAdminConfig,
  onSaveAIConfig,
  onSaveYouTubeConfig,
  onConnectYouTube,
  onDisconnectYouTube,
  saving,
  youtubeSaving,
}: SettingsViewProps) {
  const [geminiKey, setGeminiKey] = useState('');
  const [groqKey, setGroqKey] = useState('');
  const [firecrawlKey, setFirecrawlKey] = useState('');
  const [ytClientId, setYtClientId] = useState('');
  const [ytClientSec, setYtClientSec] = useState('');
  const [ytPrivacy, setYtPrivacy] = useState(youtubeStatus?.default_privacy_status || DEFAULT_PRIVACY);
  const [connecting, setConnecting] = useState(false);

  useEffect(() => {
    setYtPrivacy(youtubeStatus?.default_privacy_status || DEFAULT_PRIVACY);
  }, [youtubeStatus?.default_privacy_status]);

  const usagePct = session
    ? Math.max(0, Math.min(100, Math.round((session.usage.used / Math.max(session.usage.limit, 1)) * 100)))
    : 0;

  const handleSaveAdmin = async (e: React.FormEvent) => {
    e.preventDefault();
    const payload: Record<string, string> = {};
    if (geminiKey.trim()) payload.gemini_api_key = geminiKey.trim();
    if (groqKey.trim()) payload.groq_api_key = groqKey.trim();
    if (firecrawlKey.trim()) payload.firecrawl_api_key = firecrawlKey.trim();
    await onSaveAIConfig(payload);
    setGeminiKey('');
    setGroqKey('');
    setFirecrawlKey('');
  };

  const handleSaveYouTube = async (e: React.FormEvent) => {
    e.preventDefault();
    const payload: Record<string, string> = {
      youtube_default_privacy: ytPrivacy,
    };
    if (ytClientId.trim()) payload.youtube_client_id = ytClientId.trim();
    if (ytClientSec.trim()) payload.youtube_client_secret = ytClientSec.trim();
    await onSaveYouTubeConfig(payload);
    setYtClientId('');
    setYtClientSec('');
  };

  const handleConnect = async () => {
    setConnecting(true);
    try {
      await onConnectYouTube();
    } finally {
      setConnecting(false);
    }
  };

  const canConnectYouTube = Boolean(youtubeStatus?.has_client_config || (ytClientId.trim() && ytClientSec.trim()));

  return (
    <div className={`${styles.view} animate-in`}>
      {!isAdmin && (
        <div className={`card ${styles.roleBanner} ${styles.roleBannerUser}`}>
          <span className={`material-symbols-outlined ${styles.roleBannerIcon}`}>person</span>
          <div>
            <h4 className={styles.roleBannerTitle}>Your account settings</h4>
            <p className={styles.roleBannerDesc}>
              Set up your own YouTube client credentials and connect your own YouTube account here.
            </p>
          </div>
        </div>
      )}

      {isAdmin && adminConfigError && (
        <div className={`card ${styles.roleBanner} ${styles.roleBannerAdmin}`}>
          <span className={`material-symbols-outlined ${styles.roleBannerIcon}`}>admin_panel_settings</span>
          <div className={styles.roleBannerBody}>
            <div>
              <h4 className={styles.roleBannerTitle}>Admin settings unavailable</h4>
              <p className={styles.roleBannerDesc}>{adminConfigError}</p>
            </div>
            {onRetryAdminConfig && (
              <button type="button" className="btn btn-secondary" onClick={() => { void onRetryAdminConfig(); }}>
                Retry
              </button>
            )}
          </div>
        </div>
      )}

      {!youtubeStatus?.has_client_config && (
        <div className={`card ${styles.youtubeSetupAlert}`}>
          <span className={`material-symbols-outlined ${styles.youtubeSetupIcon}`}>info</span>
          <div>
            <h4 className={styles.youtubeSetupTitle}>YouTube Publishing Not Configured</h4>
            <p className={styles.youtubeSetupDesc}>
              Add your YouTube OAuth client credentials below, or use the workspace-provided client if your admin has configured one.
              <br />
              <a
                href="https://developers.google.com/youtube/v3/quickstart/login#authorize_credentials"
                target="_blank"
                rel="noopener noreferrer"
                className={styles.youtubeSetupLink}
              >
                Learn how to create OAuth credentials
              </a>
            </p>
          </div>
        </div>
      )}

      {session && (
        <div className={`card ${styles.section}`}>
          <div className={styles.sectionHead}>
            <span className={`material-symbols-outlined ${styles.sectionIcon} ${styles.iconBlue}`}>data_usage</span>
            <div>
              <h3 className={styles.sectionTitle}>Usage &amp; Quota</h3>
              <p className={styles.sectionDesc}>Your daily processing allowance.</p>
            </div>
          </div>
          <div className={styles.usageRow}>
            <div className={styles.usageStat}>
              <span className={styles.usageNum}>{session.usage.used}</span>
              <span className={styles.usageLabel}>Jobs Used</span>
            </div>
            <div className={styles.usageStat}>
              <span className={styles.usageNum}>{session.usage.remaining}</span>
              <span className={styles.usageLabel}>Remaining</span>
            </div>
            <div className={styles.usageStat}>
              <span className={styles.usageNum}>{session.usage.limit}</span>
              <span className={styles.usageLabel}>Daily Limit</span>
            </div>
          </div>
          <div className={styles.usageBarWrap}>
            <div className="progress-track">
              <div
                className="progress-fill"
                style={{ width: `${usagePct}%`, background: usagePct > 80 ? 'linear-gradient(90deg, var(--warning), var(--error))' : undefined }}
              />
            </div>
            <span className={`mono ${styles.usagePct}`}>{usagePct}%</span>
          </div>
          <p className={styles.usageReset}>Resets {session.usage.reset_basis}</p>
        </div>
      )}

      <form onSubmit={handleSaveYouTube} className={`card ${styles.section}`}>
        <div className={styles.sectionHead}>
          <span className={`material-symbols-outlined ${styles.sectionIcon} ${styles.iconYt}`}>smart_display</span>
          <div>
            <h3 className={styles.sectionTitle}>YouTube Credentials</h3>
            <p className={styles.sectionDesc}>
              Save your personal YouTube OAuth client ID, client secret, and preferred upload privacy.
            </p>
          </div>
        </div>

        <div className={styles.formGrid}>
          <KeyField
            label="Client ID"
            icon="fingerprint"
            placeholder="xxxx.apps.googleusercontent.com"
            value={ytClientId}
            onChange={setYtClientId}
            isSet={Boolean(youtubeStatus?.has_personal_client_config || youtubeStatus?.using_shared_fallback)}
            hint={youtubeStatus?.using_shared_fallback ? 'Workspace-provided Google OAuth client is available' : 'OAuth2 client ID from Google Cloud'}
          />
          <KeyField
            label="Client Secret"
            icon="lock"
            placeholder="GOCSPX-…"
            value={ytClientSec}
            onChange={setYtClientSec}
            isSet={Boolean(youtubeStatus?.has_personal_client_config || youtubeStatus?.using_shared_fallback)}
            hint={youtubeStatus?.using_shared_fallback ? 'Save your own if you do not want to use the workspace client' : 'OAuth2 client secret from Google Cloud'}
          />
        </div>

        <div className={styles.privacyRow}>
          <div className={styles.privacyLabel}>
            <span className={`material-symbols-outlined ${styles.privacyIcon}`}>visibility</span>
            Default Upload Privacy
          </div>
          <select
            value={ytPrivacy}
            onChange={(e) => setYtPrivacy(e.target.value)}
            className={styles.privacySelect}
          >
            <option value="private">Private</option>
            <option value="unlisted">Unlisted</option>
            <option value="public">Public</option>
          </select>
        </div>

        {youtubeStatus?.using_shared_fallback && (
          <div className={styles.localNotice}>
            <span className={`material-symbols-outlined ${styles.localNoticeIcon}`}>info</span>
            <p>
              The workspace already provides a YouTube OAuth client from environment settings. You only need to save your own client ID and secret if you want a separate Google OAuth app.
            </p>
          </div>
        )}

        <button
          type="submit"
          className={`btn btn-primary ${styles.saveBtn}`}
          disabled={youtubeSaving}
        >
          {youtubeSaving ? (
            <><span className={`material-symbols-outlined ${styles.spinning}`}>autorenew</span>Saving…</>
          ) : (
            <><span className="material-symbols-outlined">save</span>Save YouTube Settings</>
          )}
        </button>
      </form>

      <div className={`card ${styles.section}`}>
        <div className={styles.sectionHead}>
          <span className={`material-symbols-outlined ${styles.sectionIcon} ${styles.iconYt}`}>link</span>
          <div>
            <h3 className={styles.sectionTitle}>YouTube Account</h3>
            <p className={styles.sectionDesc}>{youtubeStatus?.message || 'Connect your YouTube account to publish clips directly.'}</p>
          </div>
        </div>

        {youtubeStatus?.connected ? (
          <div className={styles.ytConnected}>
            <div className={styles.ytStatus}>
              <span className={`material-symbols-outlined ${styles.ytStatusIcon}`}>check_circle</span>
              <div>
                <p className={styles.ytStatusLabel}>Connected</p>
                {youtubeStatus.authorized_at && (
                  <p className={styles.ytStatusSub}>
                    Authorized {new Date(youtubeStatus.authorized_at).toLocaleDateString()}
                  </p>
                )}
              </div>
            </div>
            <button className={`btn btn-secondary ${styles.ytBtn}`} onClick={() => { void onDisconnectYouTube(); }}>
              <span className="material-symbols-outlined">link_off</span>
              Disconnect
            </button>
          </div>
        ) : (
          <div className={styles.ytDisconnected}>
            {!canConnectYouTube ? (
              <div className={styles.ytWarning}>
                <span className={`material-symbols-outlined ${styles.ytWarnIcon}`}>info</span>
                <p>Set your YouTube Client ID &amp; Secret above first, then connect.</p>
              </div>
            ) : (
              <div className={styles.ytConnectRow}>
                <p className={styles.ytConnectDesc}>
                  Authorize ShortMaker to upload videos to your own YouTube account.
                </p>
                <button
                  className={`btn btn-primary ${styles.ytConnectBtn}`}
                  onClick={() => { void handleConnect(); }}
                  disabled={connecting || !canConnectYouTube}
                >
                  {connecting ? (
                    <><span className={`material-symbols-outlined ${styles.spinning}`}>autorenew</span>Opening…</>
                  ) : (
                    <><span className="material-symbols-outlined">link</span>Connect YouTube</>
                  )}
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {isAdmin && config && (
        <>
          <form onSubmit={handleSaveAdmin} className={`card ${styles.section}`}>
            <div className={styles.sectionHead}>
              <span className={`material-symbols-outlined ${styles.sectionIcon} ${styles.iconViolet}`}>key</span>
              <div>
                <h3 className={styles.sectionTitle}>Workspace API Keys</h3>
                <p className={styles.sectionDesc}>Admin-only AI services and trend discovery keys for the whole workspace.</p>
              </div>
            </div>

            <div className={styles.formGrid}>
              <KeyField
                label="Gemini API Key"
                icon="auto_awesome"
                placeholder="AIzaSy…"
                value={geminiKey}
                onChange={setGeminiKey}
                isSet={!!config.has_api_key}
                hint="Powers AI highlight detection and virality scoring"
              />
              <KeyField
                label="Groq API Key"
                icon="record_voice_over"
                placeholder="gsk_…"
                value={groqKey}
                onChange={setGroqKey}
                isSet={!!config.has_groq_key}
                hint="Used for fast audio transcription"
              />
              <KeyField
                label="Firecrawl API Key"
                icon="travel_explore"
                placeholder="fc-…"
                value={firecrawlKey}
                onChange={setFirecrawlKey}
                isSet={!!config.has_firecrawl_key}
                hint="Enables live trend discovery from the web"
              />
            </div>

            <button type="submit" className={`btn btn-primary ${styles.saveBtn}`} disabled={saving}>
              {saving ? (
                <><span className={`material-symbols-outlined ${styles.spinning}`}>autorenew</span>Saving…</>
              ) : (
                <><span className="material-symbols-outlined">save</span>Save Workspace Settings</>
              )}
            </button>
          </form>

          <div className={`card ${styles.section}`}>
            <div className={styles.sectionHead}>
              <span className={`material-symbols-outlined ${styles.sectionIcon} ${styles.iconGreen}`}>tune</span>
              <div>
                <h3 className={styles.sectionTitle}>Capabilities</h3>
                <p className={styles.sectionDesc}>Current workspace AI features and the current user’s YouTube connection status.</p>
              </div>
            </div>
            <div className={styles.capsGrid}>
              <CapRow label="AI Processing" isOn={!!config.ai_enabled} icon="auto_awesome" />
              <CapRow label="Gemini API" isOn={!!config.has_api_key} icon="psychology" />
              <CapRow label="Groq Transcription" isOn={!!config.has_groq_key} icon="record_voice_over" />
              <CapRow label="Trend Discovery" isOn={!!config.has_firecrawl_key} icon="travel_explore" />
              <CapRow label="YouTube Client Ready" isOn={!!youtubeStatus?.has_client_config} icon="smart_display" />
              <CapRow label="YouTube Connected" isOn={!!youtubeStatus?.connected} icon="link" />
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function KeyField({
  label,
  icon,
  placeholder,
  value,
  onChange,
  isSet,
  hint,
}: {
  label: string;
  icon: string;
  placeholder: string;
  value: string;
  onChange: (v: string) => void;
  isSet: boolean;
  hint: string;
}) {
  return (
    <div className={styles.keyField}>
      <label className={styles.keyLabel}>
        <span className={`material-symbols-outlined ${styles.keyLabelIcon}`}>{icon}</span>
        {label}
        {isSet && (
          <span className={styles.keySetBadge}>
            <span className={`material-symbols-outlined ${styles.keySetIcon}`}>check</span>
            Set
          </span>
        )}
      </label>
      <input
        type="password"
        placeholder={isSet ? '••••••••••••••••' : placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete="off"
        spellCheck={false}
      />
      <p className={styles.keyHint}>{hint}</p>
    </div>
  );
}

function CapRow({ label, isOn, icon }: { label: string; isOn: boolean; icon: string }) {
  return (
    <div className={`${styles.capRow} ${isOn ? styles.capRowOn : styles.capRowOff}`}>
      <span className={`material-symbols-outlined ${styles.capIcon}`}>{icon}</span>
      <span className={styles.capLabel}>{label}</span>
      <span className={`${styles.capStatus} ${isOn ? styles.capOn : styles.capOff}`}>
        <span className={`material-symbols-outlined ${styles.capStatusIcon}`}>{isOn ? 'check_circle' : 'cancel'}</span>
        {isOn ? 'Active' : 'Inactive'}
      </span>
    </div>
  );
}
