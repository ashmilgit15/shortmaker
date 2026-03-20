export interface Job {
  id: string;
  job_id?: string;
  stage:
    | 'queued'
    | 'downloading'
    | 'processing'
    | 'complete'
    | 'failed'
    | 'transcribing'
    | 'highlighting'
    | 'reframing'
    | 'analyzing'
    | 'generating'
    | 'starting'
    | 'error';
  status?: string;
  progress?: number;
  message?: string;
  filename?: string;
  url?: string;
  shorts?: string[];
  results?: string[];
  error?: string;
  video_title?: string;
  source_type?: string;
  has_ai_data?: boolean;
  short_urls?: string[];
  input_name?: string;
  num_clips?: number;
  video_duration?: number;
  ai_highlights?: AIHighlight[];
}

export interface AIHighlight {
  index: number;
  filename: string;
  title: string;
  hook_caption: string;
  trendy_caption: string;
  hashtags: string[];
  virality_score: number;
  reason: string;
  start: number;
  end: number;
}

export interface Trend {
  topic: string;
  score: number;
}

export interface TrendCandidate {
  title: string;
  description: string;
  url: string;
  score: number;
  reason: string;
  query: string;
}

export interface AdminConfig {
  model: string;
  ai_enabled: boolean;
  is_active?: boolean;
  has_api_key?: boolean;
  has_groq_key?: boolean;
  has_firecrawl_key?: boolean;
  has_youtube_client_config?: boolean;
  has_youtube_connection?: boolean;
  youtube_default_privacy?: string;
  youtube_authorized_at?: string;
  message?: string;
}

export interface YouTubeStatus {
  has_client_config: boolean;
  has_personal_config?: boolean;
  has_personal_client_config?: boolean;
  using_shared_fallback?: boolean;
  connected: boolean;
  authorized_at?: string;
  default_privacy_status?: string;
  callback_path?: string;
  message?: string;
  needs_reconnect?: boolean;
  scope?: 'shared' | 'user';
  scope_owner_id?: string | null;
  shared_status?: {
    has_client_config: boolean;
    connected: boolean;
    authorized_at?: string;
    default_privacy_status?: string;
  };
}

export interface Capabilities {
  supports_uploads: boolean;
  supports_trend_discovery: boolean;
  supports_youtube_publish: boolean;
  has_youtube_connection: boolean;
  has_youtube_client_config: boolean;
  has_firecrawl_key: boolean;
  has_gemini_key: boolean;
  has_groq_key: boolean;
  ai_enabled: boolean;
  max_clips: number;
  daily_process_limit: number;
  allowed_video_extensions: string[];
}

export interface SessionData {
  user_id: string;
  email: string;
  first_name: string;
  last_name?: string;
  image_url?: string;
  is_admin: boolean;
  usage: {
    limit: number;
    used: number;
    remaining: number;
    reset_basis: string;
  };
}

export interface NoticeData {
  type: 'success' | 'error' | 'info';
  message: string;
}
