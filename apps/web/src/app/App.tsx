import { Navigate, Route, Routes } from 'react-router-dom'
import { AuthPage } from '../pages/Auth'
import { Home } from '../pages/Public'

export default function App() {
  return <Routes>
    <Route path="/" element={<Home />} />
    <Route path="/login" element={<AuthPage />} />
    <Route path="/register" element={<AuthPage register />} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes>
}
