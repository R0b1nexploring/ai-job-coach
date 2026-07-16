import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './AuthContext'
import { AppLayout } from '../components/Layout'
import { Home, Pricing } from '../pages/Public'
import { AuthPage } from '../pages/Auth'
import { Dashboard } from '../pages/Dashboard'
import { Resumes } from '../pages/Resumes'
import { Jobs, MatchDetail } from '../pages/Jobs'
import { Applications, Interviews, Orders } from '../pages/Workflow'
import { Settings } from '../pages/Settings'
import { Advisor, AdvisorClient } from '../pages/Advisor'
import { Onboarding } from '../pages/Onboarding'
import { AdminAccounts, AdminPackages, AdminQuotas, AdminSystem } from '../pages/Admin'

function Protected(){const {user,loading}=useAuth();if(loading)return <main className="p-10">正在验证登录状态…</main>;return user?<AppLayout/>:<Navigate to="/login" replace/>}
export default function App(){return <Routes><Route path="/" element={<Home/>}/><Route path="/pricing" element={<Pricing/>}/><Route path="/login" element={<AuthPage/>}/><Route path="/register" element={<AuthPage register/>}/><Route element={<Protected/>}><Route path="/app/onboarding" element={<Onboarding/>}/><Route path="/app/dashboard" element={<Dashboard/>}/><Route path="/app/resumes" element={<Resumes/>}/><Route path="/app/jobs" element={<Jobs/>}/><Route path="/app/matches/:id" element={<MatchDetail/>}/><Route path="/app/applications" element={<Applications/>}/><Route path="/app/interviews" element={<Interviews/>}/><Route path="/app/orders" element={<Orders/>}/><Route path="/app/settings" element={<Settings/>}/><Route path="/advisor" element={<Advisor/>}/><Route path="/advisor/clients/:id" element={<AdvisorClient/>}/><Route path="/admin/packages" element={<AdminPackages/>}/><Route path="/admin/orders" element={<AdminQuotas/>}/><Route path="/admin/accounts" element={<AdminAccounts/>}/><Route path="/admin/system" element={<AdminSystem/>}/></Route><Route path="*" element={<Navigate to="/" replace/>}/></Routes>}
