import React, { useState, useEffect, useCallback, useRef } from 'react'
import { api, Project, Message, Fact } from './api'

// ──────────────────────────────────────────────────────────────────────
// Styles (inline)
// ──────────────────────────────────────────────────────────────────────
const styles: Record<string, React.CSSProperties> = {
  container: {
    maxWidth: 1200,
    margin: '0 auto',
    padding: '16px 24px',
    minHeight: '100vh',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '12px 0',
    borderBottom: '1px solid #21262d',
    marginBottom: 20,
  },
  title: { fontSize: 22, fontWeight: 700, color: '#58a6ff' },
  subtitle: { fontSize: 13, color: '#8b949e' },
  panel: {
    display: 'grid',
    gridTemplateColumns: '260px 1fr 300px',
    gap: 16,
    alignItems: 'start',
  },
  card: {
    background: '#161b22',
    border: '1px solid #21262d',
    borderRadius: 8,
    padding: 16,
  },
  cardTitle: { fontSize: 14, fontWeight: 600, marginBottom: 10, color: '#c9d1d9' },
  input: {
    width: '100%',
    padding: '8px 12px',
    background: '#0d1117',
    border: '1px solid #30363d',
    borderRadius: 6,
    color: '#c9d1d9',
    fontSize: 13,
    outline: 'none',
  },
  btn: {
    padding: '8px 16px',
    borderRadius: 6,
    border: '1px solid #30363d',
    background: '#21262d',
    color: '#c9d1d9',
    fontSize: 13,
    cursor: 'pointer',
    fontWeight: 500,
  },
  btnPrimary: {
    padding: '8px 16px',
    borderRadius: 6,
    border: 'none',
    background: '#238636',
    color: '#fff',
    fontSize: 13,
    cursor: 'pointer',
    fontWeight: 600,
  },
  projectItem: {
    padding: '6px 10px',
    borderRadius: 6,
    cursor: 'pointer',
    fontSize: 13,
    marginBottom: 4,
    border: '1px solid transparent',
  },
  projectItemActive: {
    padding: '6px 10px',
    borderRadius: 6,
    cursor: 'pointer',
    fontSize: 13,
    marginBottom: 4,
    background: '#1f6feb22',
    border: '1px solid #1f6feb44',
    color: '#58a6ff',
  },
  msgBubble: {
    padding: '8px 12px',
    borderRadius: 6,
    marginBottom: 8,
    fontSize: 13,
    lineHeight: 1.5,
  },
  msgUser: { background: '#1f6feb22', border: '1px solid #1f6feb33' },
  msgAssistant: { background: '#23863622', border: '1px solid #23863633' },
  msgSystem: { background: '#8b949e22', border: '1px solid #8b949e33' },
  factTag: {
    display: 'inline-block',
    padding: '3px 8px',
    borderRadius: 12,
    background: '#d2992222',
    border: '1px solid #d2992233',
    fontSize: 11,
    marginRight: 6,
    marginBottom: 4,
    color: '#d2a8ff',
  },
  statusBar: {
    fontSize: 12,
    color: '#8b949e',
    padding: '4px 0',
    marginTop: 12,
    borderTop: '1px solid #21262d',
  },
}

// ──────────────────────────────────────────────────────────────────────
// Components
// ──────────────────────────────────────────────────────────────────────

function ProjectList({
  projects,
  active,
  onSelect,
  onCreate,
  onDelete,
}: {
  projects: Project[]
  active: string
  onSelect: (id: string) => void
  onCreate: (name: string) => void
  onDelete: (id: string) => void
}) {
  const [newName, setNewName] = useState('')

  const handleCreate = () => {
    const id = newName.trim().toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9_-]/g, '') || 'default'
    onCreate(id)
    setNewName('')
  }

  return (
    <div style={styles.card}>
      <div style={styles.cardTitle}>📁 Projects</div>
      <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
        <input
          style={{ ...styles.input, flex: 1 }}
          placeholder="New project..."
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
        />
        <button style={styles.btnPrimary} onClick={handleCreate}>
          +
        </button>
      </div>
      {projects.map((p) => (
        <div
          key={p.id}
          style={active === p.id ? styles.projectItemActive : styles.projectItem}
          onClick={() => onSelect(p.id)}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>{p.id}</span>
            <button
              style={{ ...styles.btn, padding: '2px 6px', fontSize: 10, background: 'transparent', border: 'none', color: '#f85149' }}
              onClick={(e) => { e.stopPropagation(); onDelete(p.id) }}
            >
              ✕
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}

function MessageInput({ projectId, onSent }: { projectId: string; onSent: () => void }) {
  const [content, setContent] = useState('')
  const [sending, setSending] = useState(false)

  const handleSend = async () => {
    if (!content.trim() || sending) return
    setSending(true)
    try {
      await api.addMessage(projectId, content.trim(), 'user')
      setContent('')
      onSent()
    } catch (e: any) {
      alert('Error: ' + e.message)
    } finally {
      setSending(false)
    }
  }

  return (
    <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
      <input
        style={{ ...styles.input, flex: 1 }}
        placeholder="Type a message to add to context..."
        value={content}
        onChange={(e) => setContent(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && handleSend()}
      />
      <button style={styles.btnPrimary} onClick={handleSend} disabled={sending}>
        {sending ? '...' : 'Send'}
      </button>
    </div>
  )
}

function ContextView({
  messages,
  facts,
  loading,
}: {
  messages: Message[]
  facts: Fact[]
  loading: boolean
}) {
  if (loading) return <div style={{ color: '#8b949e', padding: 20 }}>Loading context...</div>

  const roleStyles: Record<string, React.CSSProperties> = {
    user: styles.msgUser,
    assistant: styles.msgAssistant,
    system: styles.msgSystem,
  }

  return (
    <div>
      {messages.length === 0 && (
        <div style={{ color: '#8b949e', padding: 40, textAlign: 'center' }}>
          No messages yet. Start by sending a message.
        </div>
      )}
      {messages.map((m) => (
        <div key={m.id} style={{ ...styles.msgBubble, ...(roleStyles[m.role] || styles.msgSystem) }}>
          <div style={{ fontSize: 10, color: '#8b949e', marginBottom: 4 }}>
            {m.role} · {new Date(m.created_at).toLocaleString()}
          </div>
          <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{m.content}</div>
        </div>
      ))}
    </div>
  )
}

function FactsPanel({ facts }: { facts: Fact[] }) {
  return (
    <div style={styles.card}>
      <div style={styles.cardTitle}>🧠 Extracted Facts</div>
      {facts.length === 0 && <div style={{ color: '#8b949e', fontSize: 12 }}>No facts extracted yet.</div>}
      {facts.map((f) => (
        <div key={f.id} style={styles.factTag}>
          {f.fact}
        </div>
      ))}
    </div>
  )
}

function SearchBar({ projectId }: { projectId: string }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<{ semantic: any[]; keyword: any[] } | null>(null)

  const handleSearch = async () => {
    if (!query.trim()) return
    try {
      const r = await api.search(projectId, query.trim())
      setResults({ semantic: r.semantic_matches, keyword: r.keyword_matches })
    } catch (e: any) {
      alert('Search error: ' + e.message)
    }
  }

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
        <input
          style={{ ...styles.input, flex: 1 }}
          placeholder="Search context..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
        />
        <button style={styles.btn} onClick={handleSearch}>🔍</button>
      </div>
      {results && (
        <div style={{ fontSize: 12 }}>
          {results.semantic.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontWeight: 600, color: '#58a6ff' }}>Semantic ({results.semantic.length})</div>
              {results.semantic.slice(0, 5).map((m, i) => (
                <div key={i} style={{ padding: '4px 0', color: '#8b949e' }}>
                  [{m.similarity}] {m.text?.slice(0, 100)}
                </div>
              ))}
            </div>
          )}
          {results.keyword.length > 0 && (
            <div>
              <div style={{ fontWeight: 600, color: '#d2a8ff' }}>Keyword ({results.keyword.length})</div>
              {results.keyword.slice(0, 5).map((m: Message) => (
                <div key={m.id} style={{ padding: '4px 0', color: '#8b949e' }}>
                  {m.content?.slice(0, 100)}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────
// Main App
// ──────────────────────────────────────────────────────────────────────

export default function App() {
  const [projects, setProjects] = useState<Project[]>([])
  const [activeProject, setActiveProject] = useState('default')
  const [messages, setMessages] = useState<Message[]>([])
  const [facts, setFacts] = useState<Fact[]>([])
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState('')

  const loadProjects = useCallback(async () => {
    try {
      const p = await api.listProjects()
      setProjects(p)
    } catch { /* offline */ }
  }, [])

  const loadContext = useCallback(async (projectId: string) => {
    setLoading(true)
    try {
      const ctx = await api.getContext(projectId)
      setMessages(ctx.recent_messages.reverse())
      setFacts(ctx.extracted_facts)
      setStatus(`${ctx.message_count} messages · ${ctx.extracted_facts.length} facts`)
    } catch {
      setStatus('Server offline')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadProjects() }, [loadProjects])
  useEffect(() => {
    if (activeProject) loadContext(activeProject)
  }, [activeProject, loadContext])

  const handleCreateProject = async (name: string) => {
    try {
      await api.createProject(name, name)
      loadProjects()
      setActiveProject(name)
    } catch (e: any) { alert(e.message) }
  }

  const handleDeleteProject = async (id: string) => {
    if (!confirm(`Delete project "${id}"?`)) return
    try {
      await api.deleteProject(id)
      if (activeProject === id) setActiveProject('default')
      loadProjects()
    } catch (e: any) { alert(e.message) }
  }

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div>
          <div style={styles.title}>MeshCtx</div>
          <div style={styles.subtitle}>Continuous Context Memory Platform</div>
        </div>
        <div style={styles.statusBar}>{status}</div>
      </div>

      <div style={styles.panel}>
        {/* Left: Projects */}
        <ProjectList
          projects={projects}
          active={activeProject}
          onSelect={setActiveProject}
          onCreate={handleCreateProject}
          onDelete={handleDeleteProject}
        />

        {/* Center: Messages */}
        <div style={styles.card}>
          <div style={styles.cardTitle}>💬 Context — {activeProject}</div>
          <MessageInput projectId={activeProject} onSent={() => loadContext(activeProject)} />
          <ContextView messages={messages} facts={facts} loading={loading} />
          <SearchBar projectId={activeProject} />
        </div>

        {/* Right: Facts */}
        <FactsPanel facts={facts} />
      </div>
    </div>
  )
}
