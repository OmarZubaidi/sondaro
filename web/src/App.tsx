import { NavLink, Route, Routes } from 'react-router-dom'
import { Local } from './routes/Local'
import { Trips } from './routes/Trips'
import { TripDetail } from './routes/TripDetail'
import { Settings } from './routes/Settings'
import { StatusPage } from './routes/StatusPage'

export function App() {
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
          <NavLink to="/settings" className={({ isActive }) => (isActive ? 'active' : '')}>
            Settings
          </NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Local />} />
          <Route path="/trips" element={<Trips />} />
          <Route path="/trips/:id" element={<TripDetail />} />
          <Route path="/status" element={<StatusPage />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<div className="empty">Not found.</div>} />
        </Routes>
      </main>
    </>
  )
}
