import { useState, useEffect, useReducer, FormEvent } from 'react'
import './App.css'
import Dashboard from './Dashboard'

const STORAGE_KEY = 'api_key'

interface Item {
  id: number
  type: string
  title: string
  created_at: string
}

type FetchState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'success'; items: Item[] }
  | { status: 'error'; message: string }

type FetchAction =
  | { type: 'fetch_start' }
  | { type: 'fetch_success'; data: Item[] }
  | { type: 'fetch_error'; message: string }

type View = 'items' | 'dashboard'

function fetchReducer(_state: FetchState, action: FetchAction): FetchState {
  switch (action.type) {
    case 'fetch_start':
      return { status: 'loading' }
    case 'fetch_success':
      return { status: 'success', items: action.data }
    case 'fetch_error':
      return { status: 'error', message: action.message }
  }
}

function App() {
  const [token, setToken] = useState(
    () => localStorage.getItem(STORAGE_KEY) ?? '',
  )
  const [draft, setDraft] = useState('')
  const [fetchState, dispatch] = useReducer(fetchReducer, { status: 'idle' })
  const [currentView, setCurrentView] = useState<View>('items')

  useEffect(() => {
    if (!token) return

    dispatch({ type: 'fetch_start' })

    fetch('/items/', {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then((data: Item[]) => dispatch({ type: 'fetch_success', data }))
      .catch((err: Error) =>
        dispatch({ type: 'fetch_error', message: err.message }),
      )
  }, [token])

  function handleConnect(e: FormEvent) {
    e.preventDefault()
    const trimmed = draft.trim()
    if (!trimmed) return
    localStorage.setItem(STORAGE_KEY, trimmed)
    setToken(trimmed)
  }

  function handleDisconnect() {
    localStorage.removeItem(STORAGE_KEY)
    setToken('')
    setDraft('')
    setCurrentView('items') // Reset to items view on disconnect
  }

  if (!token) {
    return (
      <form className="token-form" onSubmit={handleConnect}>
        <h1>API Key</h1>
        <p>Enter your API key to connect.</p>
        <input
          type="password"
          placeholder="Token"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button type="submit">Connect</button>
      </form>
    )
  }

  return (
    <div>
      <header className="app-header">
        <div className="header-left">
          <h1>{currentView === 'items' ? 'Items' : 'Analytics Dashboard'}</h1>
          <nav className="header-nav">
            <button
              className={`nav-button ${currentView === 'items' ? 'active' : ''}`}
              onClick={() => setCurrentView('items')}
            >
              Items
            </button>
            <button
              className={`nav-button ${currentView === 'dashboard' ? 'active' : ''}`}
              onClick={() => setCurrentView('dashboard')}
            >
              Dashboard
            </button>
          </nav>
        </div>
        <button className="btn-disconnect" onClick={handleDisconnect}>
          Disconnect
        </button>
      </header>

      {currentView === 'items' ? (
        <>
          {fetchState.status === 'loading' && <p>Loading...</p>}
          {fetchState.status === 'error' && <p>Error: {fetchState.message}</p>}

          {fetchState.status === 'success' && (
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>ItemType</th>
                  <th>Title</th>
                  <th>Created at</th>
                </tr>
              </thead>
              <tbody>
                {fetchState.items.map((item) => (
                  <tr key={item.id}>
                    <td>{item.id}</td>
                    <td>{item.type}</td>
                    <td>{item.title}</td>
                    <td>{item.created_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      ) : (
        <Dashboard />
      )}
    </div>
  )
}

export default App