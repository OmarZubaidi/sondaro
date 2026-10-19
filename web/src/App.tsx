import { useState } from 'react'
import { Link, NavLink, Route, Routes } from 'react-router-dom'
import { Local } from './routes/Local'
import { Favorites } from './routes/Favorites'
import { Trips } from './routes/Trips'
import { StatusPage } from './routes/StatusPage'
import { SettingsDrawer } from './components/SettingsDrawer'
import { SettingsIcon } from './components/IconButton'

const navClass = ({ isActive }: { isActive: boolean }) => (isActive ? 'active' : '')

export function App() {
  const [settingsOpen, setSettingsOpen] = useState(false)

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          {/* the wordmark goes home, because every other site's does */}
          <Link to="/" className="wordmark">
            Sondaro
          </Link>
          <nav className="mainnav" aria-label="Main">
            <NavLink to="/" end className={navClass}>
              <span>Near home</span>
            </NavLink>
            <NavLink to="/favorites" className={navClass}>
              <span>Artists</span>
            </NavLink>
            <NavLink to="/trips" className={navClass}>
              <span>Trips</span>
            </NavLink>
          </nav>
          <div className="topbar-tools">
            <NavLink
              to="/status"
              className={({ isActive }) => `status-link${isActive ? ' active' : ''}`}
            >
              Status
            </NavLink>
            {/* not a route: settings open over the page you're on, because
                that page is usually why you're changing them */}
            <button
              type="button"
              className="icon-button on-ink"
              aria-label="Settings"
              title="Settings"
              aria-expanded={settingsOpen}
              onClick={() => setSettingsOpen(true)}
            >
              <SettingsIcon />
            </button>
          </div>
        </div>
        <div className="halftone" aria-hidden="true" />
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Local />} />
          <Route path="/favorites" element={<Favorites />} />
          <Route path="/trips" element={<Trips />} />
          <Route
            path="/status"
            element={
              <div className="wrap narrow">
                <StatusPage />
              </div>
            }
          />
          <Route
            path="*"
            element={
              <div className="wrap narrow">
                <div className="empty">Not found.</div>
              </div>
            }
          />
        </Routes>
      </main>
      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </>
  )
}
