import { useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { Local } from './routes/Local'
import { Trips } from './routes/Trips'
import { StatusPage } from './routes/StatusPage'
import { SettingsDrawer } from './components/SettingsDrawer'

export function App() {
  const [settingsOpen, setSettingsOpen] = useState(false)

  return (
    <>
      <header className="topbar">
        <h1>Sondaro</h1>
        <nav>
          <NavLink to="/" end className={({ isActive }) => (isActive ? 'active' : '')}>
            Local
          </NavLink>
          <NavLink to="/trips" className={({ isActive }) => (isActive ? 'active' : '')}>
            Trips
          </NavLink>
          <NavLink to="/status" className={({ isActive }) => (isActive ? 'active' : '')}>
            Status
          </NavLink>
          {/* not a route: settings open over the page you're on, because
              that page is usually why you're changing them */}
          <button
            type="button"
            className={`navlike${settingsOpen ? ' active' : ''}`}
            aria-expanded={settingsOpen}
            onClick={() => setSettingsOpen(true)}
          >
            Settings
          </button>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Local />} />
          <Route path="/trips" element={<Trips />} />
          <Route path="/status" element={<StatusPage />} />
          <Route path="*" element={<div className="empty">Not found.</div>} />
        </Routes>
      </main>
      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </>
  )
}
