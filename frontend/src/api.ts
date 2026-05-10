// MeshCtx API client

const BASE = '/api'

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

// Types
export interface Project {
  id: string
  name: string
  created_at: string
  updated_at: string
}

export interface Message {
  id: number
  project_id: string
  role: string
  content: string
  metadata: string
  created_at: string
}

export interface Fact {
  id: number
  project_id: string
  fact: string
  confidence: number
  source_msg: number | null
  created_at: string
}

export interface ContextData {
  project_id: string
  message_count: number
  recent_messages: Message[]
  extracted_facts: Fact[]
}

export interface SearchResult {
  query: string
  semantic_matches: { key: string; text: string; similarity: number }[]
  keyword_matches: Message[]
}

export interface AddMessageResult {
  message_id: number
  project_id: string
  vector_key: string
  facts_extracted: number
  facts: string[]
}

// API
export const api = {
  health: () => request<{ status: string }>('/../health'),

  listProjects: () => request<Project[]>('/projects'),

  createProject: (id: string, name: string) =>
    request<Project>('/projects', {
      method: 'POST',
      body: JSON.stringify({ id, name }),
    }),

  deleteProject: (id: string) =>
    request<{ deleted: boolean }>(`/projects/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  addMessage: (projectId: string, content: string, role = 'user') =>
    request<AddMessageResult>(`/projects/${encodeURIComponent(projectId)}/messages`, {
      method: 'POST',
      body: JSON.stringify({ content, role }),
    }),

  getContext: (projectId: string, limit = 20) =>
    request<ContextData>(`/projects/${encodeURIComponent(projectId)}/context?limit=${limit}`),

  search: (projectId: string, query: string, topK = 10) =>
    request<SearchResult>(
      `/projects/${encodeURIComponent(projectId)}/search?q=${encodeURIComponent(query)}&top_k=${topK}`
    ),

  getFacts: (projectId: string) =>
    request<{ facts: Fact[] }>(`/projects/${encodeURIComponent(projectId)}/facts`),
}
