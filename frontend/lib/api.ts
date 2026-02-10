import axios, { AxiosInstance } from 'axios';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

class ApiClient {
  private client: AxiosInstance;

  constructor() {
    this.client = axios.create({
      baseURL: `${API_URL}/api/v1`,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // Request interceptor to add auth token
    this.client.interceptors.request.use((config) => {
      const token = localStorage.getItem('access_token');
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
      return config;
    });

    // Response interceptor for token refresh
    this.client.interceptors.response.use(
      (response) => response,
      async (error) => {
        const originalRequest = error.config;
        
        if (error.response?.status === 401 && !originalRequest._retry) {
          originalRequest._retry = true;
          
          try {
            const refreshToken = localStorage.getItem('refresh_token');
            if (refreshToken) {
              const { data } = await axios.post(`${API_URL}/api/v1/auth/refresh`, {
                refresh_token: refreshToken,
              });
              
              localStorage.setItem('access_token', data.access_token);
              this.client.defaults.headers.common['Authorization'] = `Bearer ${data.access_token}`;
              return this.client(originalRequest);
            }
          } catch (refreshError) {
            localStorage.removeItem('access_token');
            localStorage.removeItem('refresh_token');
            window.location.href = '/';
            return Promise.reject(refreshError);
          }
        }
        
        return Promise.reject(error);
      }
    );
  }

  // Auth endpoints
  async login(username: string, password: string) {
    const { data } = await this.client.post('/auth/login', null, {
      params: { username, password },
    });
    return data;
  }

  async refreshToken(refreshToken: string) {
    const { data } = await this.client.post('/auth/refresh', {
      refresh_token: refreshToken,
    });
    return data;
  }

  // Query endpoints
  async queryText(
    query: string,
    opts?: { docIds?: number[]; sourceFilter?: string; contentTypeFilter?: string }
  ) {
    const { data } = await this.client.post('/query/text', {
      query,
      doc_ids: opts?.docIds,
      source_filter: opts?.sourceFilter,
      content_type_filter: opts?.contentTypeFilter,
      stream: false,
    });
    return data;
  }

  async queryAudio(file: File) {
    const formData = new FormData();
    formData.append('file', file);
    
    const { data } = await this.client.post('/query/audio', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return data;
  }

  async getQueryHistory(limit: number = 50) {
    const { data } = await this.client.get('/query/history', {
      params: { limit },
    });
    return data;
  }

  // Document endpoints
  async uploadDocuments(files: File[], onProgress?: (progress: number) => void) {
    const formData = new FormData();
    files.forEach((file) => {
      formData.append('files', file);
    });
    
    const { data } = await this.client.post('/docs/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      onUploadProgress: (event) => {
        if (!onProgress) return;
        const total = event.total ?? 0;
        if (total <= 0) return;
        const percent = Math.round((event.loaded * 100) / total);
        onProgress(percent);
      },
    });
    return data;
  }

  async listDocuments() {
    const { data } = await this.client.get('/docs');
    return data;
  }

  async summarizeDocument(docId: number) {
    const { data } = await this.client.post(`/docs/${docId}/summarize`);
    return data;
  }

  async answerFromDocument(docId: number, question: string) {
    const { data } = await this.client.post(`/docs/${docId}/answer`, {
      question,
    });
    return data;
  }

  // Admin endpoints
  async getMetrics() {
    const { data } = await this.client.get('/admin/metrics');
    return data;
  }

  async getSystemStatus() {
    const { data } = await this.client.get('/admin/system-status');
    return data;
  }

  // Health check
  async healthCheck() {
    const { data } = await this.client.get('/health');
    return data;
  }
}

export const api = new ApiClient();

// Types
export interface QueryResponse {
  answer: string;
  sources: Array<{
    filename: string;
    content_type: string;
    relevance: number;
    retrieval_relevance?: number;
    text: string;
    page_number?: number | null;
    timestamp_start?: number | null;
    timestamp_end?: number | null;
    language?: string | null;
    embedding_model?: string | null;
    ingestion_time?: number | null;
    confidence?: number | null;
    chunk_index?: number | null;
  }>;
  latency_ms?: number;
  tool_confidence?: {
    transcription?: { output: any; confidence: number; meta?: any };
    retrieval?: { output: any; confidence: number; meta?: any };
    llm?: { output: any; confidence: number; meta?: any };
    [key: string]: any;
  };
}

export interface QueryHistoryItem {
  id: number;
  query: string;
  response: string;
  latency_ms: number;
  created_at: string;
  sources_count: number;
}

export interface Document {
  id: number;
  filename: string;
  storage_uri: string;
  content_type?: string;
  created_at?: string;
  ocr_status?: string | null;
  ocr_pages_total?: number | null;
  ocr_pages_done?: number | null;
  ocr_error?: string | null;
  ocr_updated_at?: string | null;
}

export interface Metrics {
  total_documents: number;
  total_queries: number;
  total_users: number;
  queries_last_24h: number;
  queries_last_7d: number;
  avg_latency_ms: number;
  documents_by_type: Record<string, number>;
  rag?: {
    retrieval_hit_rate_24h?: number;
    retrieval_hit_rate_7d?: number;
    grounded_rate_24h?: number;
    grounded_rate_7d?: number;
    hallucinations_24h?: number;
    hallucinations_7d?: number;
    avg_vector_distance_24h?: number | null;
    avg_vector_distance_7d?: number | null;
    avg_retrieval_confidence_24h?: number | null;
    avg_retrieval_confidence_7d?: number | null;
    total_tokens_24h?: number;
    total_tokens_7d?: number;
    estimated_cost_usd_24h?: number;
    estimated_cost_usd_7d?: number;
  };
  queries_by_day: Array<{
    date: string;
    count: number;
  }>;
}

export interface SystemStatus {
  milvus_collection_exists: boolean;
}